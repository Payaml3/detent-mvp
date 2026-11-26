"""P2 group 3b: the sandbox reset starts a new data generation (SBX-04, C-04, D-08; DSH-07's reset button).

Nothing is deleted: earlier rows stay and are hidden from the API and the dashboard. Keys, webhook endpoints,
members and settings stay. The reset is audited and refused while a payout could still be sent.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from conftest import make_settings
from cryptography.fernet import Fernet
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.dashboard import access, sandbox
from detent.dashboard.access import Member
from detent.domain.roles import Role
from detent.sandbox.generations import GENERATED_TABLES
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from test_dashboard_access import PASSWORD, _email, audit_kinds, owner_of, sign_in, token_of
from test_sandbox_rails import PEPPER, SETTINGS, drain, key_for, pay

pytestmark = pytest.mark.db

WEBHOOKS = make_settings(
    "org_detent",
    api_key_pepper=SecretStr(PEPPER),
    credentials_encryption_key=SecretStr(Fernet.generate_key().decode()),
)


@pytest.fixture
def owner(engine: Engine, clock: FrozenClock) -> Member:
    with engine.begin() as conn:
        staff = access.create_staff(
            conn, clock, email=_email("staff"), display_name="Staff", password=PASSWORD
        )
    _org, member = owner_of(engine, clock, staff)
    with engine.begin() as conn:  # sandbox organisations start in shadow mode; these tests send
        conn.execute(text("UPDATE organisations SET mode='auto' WHERE org_id=:o"), {"o": member.org_id})
    return member


@pytest.fixture
def api(engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    with TestClient(create_app(WEBHOOKS, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


@pytest.fixture
def web(engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    with TestClient(create_app(SETTINGS, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def _reset(engine: Engine, clock: FrozenClock, m: Member, confirm: str = "reset") -> int:
    with engine.begin() as conn:
        return sandbox.reset_sandbox(conn, clock, by=m, confirm=confirm)


def _counts(engine: Engine, org_id: str) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            t: int(
                conn.execute(text(f"SELECT count(*) FROM {t} WHERE org_id=:o"), {"o": org_id}).scalar_one()
            )
            for t in (*GENERATED_TABLES, "attempts", "audit_events", "api_keys", "webhook_endpoints", "users")
        }


def _escalate(api: TestClient, auth: dict[str, str], key: str | None = None) -> Any:
    return api.post(
        "/v1/payment_intents",
        json={
            "kind": "payout", "source": "platform", "counterparty_id": "cpt_nova",
            "destination": {"kind": "evm_wallet", "network": "eth-sepolia", "destination_id": "dst_nova_eth"},
            "amount": {"amount": "90.00", "currency": "USDC"},
        },
        headers={**auth, "Idempotency-Key": key or str(uuid.uuid4())},
    )  # fmt: skip


def test_a_reset_hides_earlier_data_from_the_api_and_deletes_nothing(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    auth = key_for(engine, clock, owner)
    hook = api.post(
        "/v1/webhook_endpoints",
        json={"url": "https://hooks.example.test/dekern", "event_types": ["payment_intent.confirmed"]},
        headers={**auth, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert hook.status_code == 201, hook.text
    paid = pay(api, auth, "90.00")
    drain(engine, clock, owner.org_id)
    case_id = _escalate(api, auth).json()["exception"]["id"]
    events = api.get("/v1/events", headers=auth).json()["data"]
    assert events and api.get("/v1/exceptions", headers=auth).json()["data"]
    assert api.get("/v1/request_logs", headers=auth).json()["data"]
    before = _counts(engine, owner.org_id)

    assert _reset(engine, clock, owner) == 1

    # Hidden from every read of the API ...
    assert api.get(f"/v1/payment_intents/{paid['id']}", headers=auth).status_code == 404
    assert api.get(f"/v1/payment_intents/{paid['id']}/replay", headers=auth).status_code == 404
    assert api.get("/v1/payment_intents", headers=auth).json()["data"] == []
    assert api.get("/v1/exceptions", headers=auth).json()["data"] == []
    assert api.get(f"/v1/exceptions/{case_id}", headers=auth).status_code == 404
    approve = api.post(f"/v1/exceptions/{case_id}/approve", json={"reason": "ok"}, headers=auth)
    assert approve.status_code == 404
    assert api.get("/v1/events", headers=auth).json()["data"] == []
    assert api.get(f"/v1/events/{events[0]['id']}", headers=auth).status_code == 404
    logs = api.get("/v1/request_logs", headers=auth).json()["data"]
    assert all(r["at"] >= clock.now().isoformat()[:19] for r in logs)  # only calls made after the reset
    # ... and nothing deleted: the counts only grew (the calls above were logged).
    after = _counts(engine, owner.org_id)
    assert all(after[t] >= before[t] for t in before), (before, after)
    assert after["payment_intents"] == before["payment_intents"]
    assert after["audit_events"] == before["audit_events"] + 1
    assert "sandbox.reset" in audit_kinds(engine, owner.org_id)

    # Keys and webhook endpoints stay; new data is visible.
    assert api.get(f"/v1/webhook_endpoints/{hook.json()['id']}", headers=auth).status_code == 200
    fresh = pay(api, auth, "90.00")
    listed = api.get("/v1/payment_intents", headers=auth).json()["data"]
    assert [p["id"] for p in listed] == [fresh["id"]]
    with engine.connect() as conn:
        gens: dict[str, int] = dict(
            conn.execute(
                text("SELECT id, generation FROM payment_intents WHERE org_id=:o"), {"o": owner.org_id}
            ).all()
        )
    assert gens[paid["id"]] == 0 and gens[fresh["id"]] == 1


def test_an_insert_cannot_choose_its_generation(owner: Member, engine: Engine, clock: FrozenClock) -> None:
    _reset(engine, clock, owner)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO request_logs (org_id, method, path, status, latency_ms, request_id, at, generation) "
                "VALUES (:o, 'GET', '/v1/x', 200, 1, 'req_x', :t, 0)"
            ),
            {"o": owner.org_id, "t": clock.now()},
        )
        g = conn.execute(
            text("SELECT generation FROM request_logs WHERE org_id=:o AND path='/v1/x'"), {"o": owner.org_id}
        ).scalar_one()
    assert g == 1


def test_an_idempotency_key_replayed_after_a_reset_never_pays_twice(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    auth = key_for(engine, clock, owner)
    key = str(uuid.uuid4())
    first = _escalate(api, auth, key)
    _reset(engine, clock, owner)
    again = _escalate(api, auth, key)
    assert again.json()["id"] == first.json()["id"]
    with engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM payment_intents WHERE org_id=:o"), {"o": owner.org_id}
        ).scalar_one()
    assert n == 1


def test_a_reset_is_refused_while_a_payout_can_still_be_sent(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    with pytest.raises(access.AccessError, match="Type reset"):
        _reset(engine, clock, owner, confirm="yes")
    out = pay(api, key_for(engine, clock, owner), "90.13")  # READY, then UNKNOWN on the simulated chain
    with pytest.raises(access.AccessError, match="can still be sent"):
        _reset(engine, clock, owner)
    drain(engine, clock, owner.org_id)
    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"),
            {"o": owner.org_id, "p": out["id"]},
        ).scalar_one()
    assert status == "UNKNOWN"
    with pytest.raises(access.AccessError, match="can still be sent"):
        _reset(engine, clock, owner)
    drain(engine, clock, owner.org_id, seconds=20, rounds=4)
    assert _reset(engine, clock, owner) == 1
    assert "sandbox.reset" not in audit_kinds(engine, owner.org_id)[:-1]


def test_the_demo_organisation_cannot_be_reset_here(
    owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE organisations SET kind='demo' WHERE org_id=:o"), {"o": owner.org_id})
    with pytest.raises(access.AccessError, match="can't be reset"):
        _reset(engine, clock, owner)


def test_the_sandbox_page_resets_and_hides_earlier_logs(
    web: TestClient, api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    auth = key_for(engine, clock, owner)
    old = pay(api, auth, "90.00")
    drain(engine, clock, owner.org_id)
    assert sign_in(web, owner.email).status_code == 303
    page = web.get("/dashboard/sandbox").text
    assert "Reset test data" in page and old["id"] in page
    assert "No requests match" not in web.get("/dashboard/logs").text
    r = web.post(
        "/dashboard/sandbox/reset",
        data={"confirm": "reset", "csrf": token_of(web, "/dashboard/sandbox")},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    page = web.get(r.headers["location"]).text
    assert "Test data reset" in page and old["id"] not in page and "Resets so far: 1" in page
    assert "No requests match" in web.get("/dashboard/logs").text
    assert web.get("/dashboard/keys").status_code == 200


def test_roles_without_sandbox_control_cannot_reset(
    web: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    email = _email("rev")
    with engine.begin() as conn:
        token = access.invite(
            conn, clock, SETTINGS, org_id=owner.org_id, email=email, role=Role.REVIEWER, by=owner
        )
        access.accept_invite(conn, clock, token=token, display_name="Rae", password=PASSWORD)
    assert sign_in(web, email).status_code == 303
    r = web.post("/dashboard/sandbox/reset", data={"confirm": "reset", "csrf": token_of(web, "/dashboard/")})
    assert r.status_code == 403
    with engine.connect() as conn:
        g = conn.execute(
            text("SELECT data_generation FROM organisations WHERE org_id=:o"), {"o": owner.org_id}
        ).scalar_one()
    assert g == 0
