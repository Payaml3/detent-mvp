"""WHK-01 to WHK-03 and API-07 over HTTP, with a real local receiver."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from conftest import make_settings
from cryptography.fernet import Fernet
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.settings import Settings
from detent.webhooks.delivery import JOB_KIND, deliver_job
from detent.webhooks.signing import SIGNATURE_HEADER, verify
from detent.worker.queue import Job
from detent.worker.registry import JobContext
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


# ------------------------------------------------------------------------------------------ receiver
class Receiver:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status = 200
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append({"headers": dict(self.headers), "body": body, "path": self.path})
                self.send_response(outer.status)
                self.end_headers()

            def log_message(self, *a: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/hooks"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def receiver() -> Iterator[Receiver]:
    r = Receiver()
    yield r
    r.close()


@pytest.fixture
def dorg(engine: Engine, clock: FrozenClock) -> DecisionOrg:
    return setup_decision_org(engine, clock)


@pytest.fixture
def wsettings(dorg: DecisionOrg) -> Settings:
    return make_settings(
        dorg.id,
        api_key_pepper=SecretStr(PEPPER),
        credentials_encryption_key=SecretStr(Fernet.generate_key().decode()),
        webhook_allow_private_urls=True,
        webhook_timeout_seconds=2.0,
    )


@pytest.fixture
def api(wsettings: Settings, engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    with TestClient(create_app(wsettings, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def _create(
    api: TestClient, dorg: DecisionOrg, url: str, types: list[str] | None = None, key: str | None = None
):  # type: ignore[no-untyped-def]
    return api.post(
        "/v1/webhook_endpoints",
        json={"url": url, "event_types": types or ["*"]},
        headers={**dorg.auth(), "Idempotency-Key": key or str(uuid.uuid4())},
    )


def _run_deliveries(engine: Engine, clock: FrozenClock, settings: Settings, org_id: str) -> int:
    """Run the due webhook.deliver jobs once each (the queue's own mechanics are tested in test_worker)."""
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT id, org_id, kind, payment_id, payload, attempts, max_attempts, run_at FROM jobs "
                "WHERE org_id=:o AND kind=:k AND done_at IS NULL AND run_at <= :now ORDER BY run_at, id"
            ),
            {"o": org_id, "k": JOB_KIND, "now": clock.now()},
        ).all()
    for r in rows:
        job = Job(
            r.id, r.org_id, r.kind, r.payment_id, dict(r.payload), r.attempts + 1, r.max_attempts, r.run_at
        )
        with engine.begin() as conn:
            deliver_job(JobContext(conn, clock, job, "test-worker", engine, settings))
            conn.execute(
                text("UPDATE jobs SET done_at=:t WHERE org_id=:o AND id=:i"),
                {"t": clock.now(), "o": org_id, "i": r.id},
            )
    return len(rows)


def _escalate(api: TestClient, dorg: DecisionOrg) -> str:
    dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": dorg.wallets["WALLET_BLUEFIN_BASE"]}
    r = api.post(
        "/v1/payment_intents",
        json=payout("cpt_bluefin", "18500.00", "USDC", dest, reference="INV-WH-1"),
        headers={**dorg.auth(), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201 and r.json()["status"] == "ESCALATED", r.text
    return str(r.json()["id"])


# ------------------------------------------------------------------------------------------ WHK-01
def test_the_secret_is_shown_once_and_stored_encrypted(
    api: TestClient, dorg: DecisionOrg, engine: Engine, receiver: Receiver
) -> None:
    key = str(uuid.uuid4())
    r = _create(api, dorg, receiver.url, key=key)
    assert r.status_code == 201, r.text
    secret = r.json()["secret"]
    assert secret.startswith("whsec_")
    again = _create(api, dorg, receiver.url, key=key)
    assert (
        again.status_code == 201 and again.json()["id"] == r.json()["id"] and again.json()["secret"] is None
    )
    with engine.connect() as c:
        row = c.execute(text("SELECT * FROM webhook_endpoints WHERE org_id=:o"), {"o": dorg.id}).one()
        stored = json.dumps([str(v) for v in row]) + json.dumps(
            [
                str(v)
                for v in c.execute(
                    text("SELECT response FROM idempotency_records WHERE org_id=:o"), {"o": dorg.id}
                ).scalars()
            ]
        )
    assert secret not in stored  # neither the endpoint row nor the replay record holds the plaintext
    assert (
        api.get(f"/v1/webhook_endpoints/{r.json()['id']}", headers=dorg.auth()).json().get("secret") is None
    )


def test_endpoint_creation_fails_closed_without_the_encryption_key(
    dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    s = make_settings(dorg.id, api_key_pepper=SecretStr(PEPPER), webhook_allow_private_urls=True)
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        r = _create(c, dorg, "http://127.0.0.1:9/hooks")
    assert r.status_code == 503 and r.json()["error"]["code"] == "webhooks_unavailable"


def test_endpoint_rules(api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock) -> None:
    bad = _create(api, dorg, "http://127.0.0.1:9/hooks", types=["payment_intent.teleported"])
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unknown_event_type"
    reader = setup_decision_org(engine, clock, scopes=["read"])
    denied = _create(api, reader, "http://127.0.0.1:9/hooks")
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "insufficient_scope"
    nokey = api.post(
        "/v1/webhook_endpoints",
        json={"url": "http://127.0.0.1:9/h", "event_types": ["*"]},
        headers=dorg.auth(),
    )
    assert nokey.status_code == 422


def test_events_carry_id_and_a_per_payment_sequence(api: TestClient, dorg: DecisionOrg) -> None:
    pid = _escalate(api, dorg)
    events = api.get(f"/v1/events?payment_id={pid}", headers=dorg.auth()).json()["data"]
    events.reverse()  # oldest first
    types = [e["type"] for e in events]
    assert types[:2] == ["payment_intent.decided", "payment_intent.escalated"]
    assert "exception.created" in types
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert all(e["id"].startswith("evt_") and e["test"] is False for e in events)
    obj = events[1]["data"]["object"]
    assert obj["object"] == "payment_intent" and obj["id"] == pid and obj["status"] == "ESCALATED"
    assert obj["amount"] == {"amount": "18500.00", "currency": "USDC"}


def test_a_refused_change_leaves_no_event(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    from detent.audit.log import Actor
    from detent.domain.states import InvalidTransition, Status
    from detent.intents.transition import apply_transition

    pid = _escalate(api, dorg)
    before = len(api.get(f"/v1/events?payment_id={pid}", headers=dorg.auth()).json()["data"])
    with pytest.raises(InvalidTransition):
        apply_transition(
            engine, clock, org_id=dorg.id, payment_id=pid, to=Status.CONFIRMED, actor=Actor.system("test")
        )
    assert len(api.get(f"/v1/events?payment_id={pid}", headers=dorg.auth()).json()["data"]) == before


# ------------------------------------------------------------------------------------------ WHK-02 and WHK-03
def test_deliveries_are_signed_and_logged(
    api: TestClient,
    dorg: DecisionOrg,
    engine: Engine,
    clock: FrozenClock,
    wsettings: Settings,
    receiver: Receiver,
) -> None:
    secret = _create(api, dorg, receiver.url, types=["payment_intent.escalated"]).json()["secret"]
    pid = _escalate(api, dorg)
    assert _run_deliveries(engine, clock, wsettings, dorg.id) == 1  # subscribed to one type only
    [req] = receiver.requests
    body = req["body"]
    assert verify(secret, req["headers"][SIGNATURE_HEADER], body, now=int(clock.now().timestamp()))
    sent = json.loads(body)
    assert sent["type"] == "payment_intent.escalated" and sent["data"]["object"]["id"] == pid
    # API-07: the polled event is the same object as the delivered one.
    polled = api.get(f"/v1/events/{sent['id']}", headers=dorg.auth()).json()
    assert polled == sent
    eid = api.get("/v1/webhook_endpoints", headers=dorg.auth()).json()["data"][0]["id"]
    log = api.get(f"/v1/webhook_endpoints/{eid}/deliveries", headers=dorg.auth()).json()["data"]
    assert len(log) == 1 and log[0]["status_code"] == 200 and log[0]["outcome"] == "succeeded"
    assert log[0]["latency_ms"] is not None and log[0]["event_type"] == "payment_intent.escalated"


def test_failures_retry_on_the_g20_schedule_then_fail(
    api: TestClient,
    dorg: DecisionOrg,
    engine: Engine,
    clock: FrozenClock,
    wsettings: Settings,
    receiver: Receiver,
) -> None:
    receiver.status = 500
    eid = _create(api, dorg, receiver.url, types=["payment_intent.escalated"]).json()["id"]
    _escalate(api, dorg)
    delays = [timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2),
              timedelta(hours=6), timedelta(hours=24)]  # fmt: skip
    assert _run_deliveries(engine, clock, wsettings, dorg.id) == 1
    for d in delays:
        clock.advance(d - timedelta(seconds=1))
        assert _run_deliveries(engine, clock, wsettings, dorg.id) == 0  # not due yet
        clock.advance(timedelta(seconds=1))
        assert _run_deliveries(engine, clock, wsettings, dorg.id) == 1
    clock.advance(timedelta(days=3))
    assert _run_deliveries(engine, clock, wsettings, dorg.id) == 0  # given up
    log = api.get(f"/v1/webhook_endpoints/{eid}/deliveries", headers=dorg.auth()).json()["data"]
    assert [x["attempt"] for x in reversed(log)] == [1, 2, 3, 4, 5, 6, 7]
    assert [x["outcome"] for x in log] == ["failed"] + ["retrying"] * 6
    assert all(x["status_code"] == 500 for x in log) and len(receiver.requests) == 7


def test_send_test_event_and_manual_resend(
    api: TestClient,
    dorg: DecisionOrg,
    engine: Engine,
    clock: FrozenClock,
    wsettings: Settings,
    receiver: Receiver,
) -> None:
    other = Receiver()
    try:
        eid = _create(api, dorg, receiver.url).json()["id"]
        _create(api, dorg, other.url)
        r = api.post(f"/v1/webhook_endpoints/{eid}/test", headers=dorg.auth())
        assert r.status_code == 202
        _run_deliveries(engine, clock, wsettings, dorg.id)
        assert other.requests == []  # the test event goes to the chosen endpoint only
        [req] = receiver.requests
        sent = json.loads(req["body"])
        assert sent["type"] == "webhook.test" and sent["test"] is True
        again = api.post(
            f"/v1/webhook_endpoints/{eid}/resend", json={"event_id": sent["id"]}, headers=dorg.auth()
        )
        assert again.status_code == 202
        _run_deliveries(engine, clock, wsettings, dorg.id)
        assert len(receiver.requests) == 2 and json.loads(receiver.requests[1]["body"])["id"] == sent["id"]
        log = api.get(f"/v1/webhook_endpoints/{eid}/deliveries", headers=dorg.auth()).json()["data"]
        assert log[0]["manual"] is True and log[1]["manual"] is False
    finally:
        other.close()


def test_a_disabled_endpoint_receives_nothing(
    api: TestClient,
    dorg: DecisionOrg,
    engine: Engine,
    clock: FrozenClock,
    wsettings: Settings,
    receiver: Receiver,
) -> None:
    eid = _create(api, dorg, receiver.url).json()["id"]
    _escalate(api, dorg)  # deliveries queued while enabled
    assert api.delete(f"/v1/webhook_endpoints/{eid}", headers=dorg.auth()).json()["status"] == "disabled"
    _escalate(api, dorg)  # nothing queued
    _run_deliveries(engine, clock, wsettings, dorg.id)
    assert receiver.requests == []


def test_another_organisation_sees_none_of_it(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock, receiver: Receiver
) -> None:
    eid = _create(api, dorg, receiver.url).json()["id"]
    pid = _escalate(api, dorg)
    event = api.get(f"/v1/events?payment_id={pid}", headers=dorg.auth()).json()["data"][0]["id"]
    other = setup_decision_org(engine, clock)
    assert api.get("/v1/events", headers=other.auth()).json()["data"] == []
    assert api.get(f"/v1/events/{event}", headers=other.auth()).status_code == 404
    assert api.get(f"/v1/webhook_endpoints/{eid}", headers=other.auth()).status_code == 404
    assert api.post(f"/v1/webhook_endpoints/{eid}/test", headers=other.auth()).status_code == 404
    assert api.get("/v1/webhook_endpoints", headers=other.auth()).json()["data"] == []


def test_events_filter_by_type_and_page(api: TestClient, dorg: DecisionOrg) -> None:
    for _ in range(3):
        _escalate(api, dorg)
    esc = api.get("/v1/events?type=payment_intent.escalated", headers=dorg.auth()).json()["data"]
    assert len(esc) == 3 and {e["type"] for e in esc} == {"payment_intent.escalated"}
    first = api.get("/v1/events?limit=2", headers=dorg.auth()).json()
    assert first["has_more"] is True
    rest = api.get(f"/v1/events?limit=100&starting_after={first['next_cursor']}", headers=dorg.auth()).json()
    ids = [e["id"] for e in first["data"]] + [e["id"] for e in rest["data"]]
    assert len(ids) == len(set(ids))
    bad = api.get("/v1/events?type=nope", headers=dorg.auth())
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unknown_event_type"
