"""SDK-01: the Python SDK against the sandbox API, in process (the CI sandbox: the real app and database)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from dekernai import APIError, DekernAI, verify_webhook
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.webhooks import signing
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from test_docs_guides import Org, S, auto, block, drain, org  # noqa: F401  (fixtures)
from test_sandbox_reset import WEBHOOKS

pytestmark = pytest.mark.db


@pytest.fixture
def api(engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    """The guides' settings, with webhook signing secrets enabled."""
    s = S.model_copy(update={"credentials_encryption_key": WEBHOOKS.credentials_encryption_key})
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def sdk(api: TestClient, key: dict[str, str], **kw: object) -> DekernAI:
    token = key["Authorization"].removeprefix("Bearer ")
    return DekernAI(token, base_url="http://testserver", http_client=api, **kw)  # type: ignore[arg-type]


@pytest.fixture
def owner(api: TestClient, engine: Engine, clock: FrozenClock, org: Org) -> DekernAI:  # noqa: F811
    return sdk(api, org.key(org.owner, engine, clock))


def test_create_retrieve_list_and_idempotency(
    owner: DekernAI,
    engine: Engine,
    clock: FrozenClock,
    org: Org,  # noqa: F811
) -> None:
    body = block("handle-unknown.mdx", "json unknown.json") | {
        "amount": {"amount": "50.00", "currency": "USDC"}
    }
    shadowed = owner.payment_intents.create(body)
    assert shadowed["status"] == "SHADOWED" and shadowed["id"].startswith("pay_")
    again = owner.payment_intents.create(body, idempotency_key="sdk-key-1")
    assert owner.payment_intents.create(body, idempotency_key="sdk-key-1")["id"] == again["id"]  # replayed
    assert owner.payment_intents.retrieve(shadowed["id"])["id"] == shadowed["id"]
    page = owner.payment_intents.list(status="SHADOWED", limit=1)
    assert len(page["data"]) == 1 and page["has_more"] is True and page["next_cursor"]
    nxt = owner.payment_intents.list(status="SHADOWED", limit=1, starting_after=page["next_cursor"])
    assert nxt["data"][0]["id"] != page["data"][0]["id"]
    dry = owner.decisions.create(body)
    assert dry["id"].startswith("dec_") and dry["outcome"] == "EXECUTE"  # decided, nothing created

    auto(engine, org)
    ready = owner.payment_intents.create(body)
    assert ready["status"] == "READY"
    drain(engine, clock, org.id)
    assert owner.payment_intents.retrieve(ready["id"])["status"] == "CONFIRMED"
    assert owner.payment_intents.replay(ready["id"])


def test_api_errors_carry_the_error_fields(owner: DekernAI) -> None:
    with pytest.raises(APIError) as missing:
        owner.payment_intents.retrieve("pay_doesnotexist")
    assert missing.value.status == 404 and missing.value.type == "not_found" and missing.value.request_id
    bad = block("handle-unknown.mdx", "json unknown.json") | {
        "amount": {"amount": "1.5.0", "currency": "USDC"}
    }
    with pytest.raises(APIError) as invalid:
        owner.payment_intents.create(bad)
    assert invalid.value.status in (400, 422) and invalid.value.type == "invalid_request"


def test_escalation_approval_kill_switch_and_mandates(
    api: TestClient,
    engine: Engine,
    clock: FrozenClock,
    org: Org,  # noqa: F811
) -> None:
    auto(engine, org)
    agent = sdk(api, org.key(org.owner, engine, clock, ["intents:create"]))
    lead = sdk(api, org.key(org.lead, engine, clock))
    assert lead.mandates.list()["data"][0]["mandate_id"] == "mnd_demo_ap_agent"
    got = agent.payment_intents.create(block("agent-supplier-invoice.mdx", "json agent-intent.json"))
    assert got["status"] == "ESCALATED"
    [case] = lead.exceptions.list(status="open")["data"]
    assert lead.exceptions.retrieve(case["id"])["raw_facts"]
    assert lead.exceptions.approve(case["id"], {"reason": "Invoice checked"})["payment_status"] == "READY"

    assert lead.kill_switch.engage() == {"engaged": True}
    assert lead.kill_switch.release() == {"engaged": False}
    drain(engine, clock, org.id)
    assert lead.payment_intents.retrieve(got["id"])["status"] == "CONFIRMED"
    events = lead.events.list(payment_id=got["id"])["data"]
    assert "payment_intent.confirmed" in {e["type"] for e in events}
    assert lead.policy.list_versions()["data"]
    assert lead.request_logs.list(limit=5)["data"]


def test_deposits_and_webhook_endpoints(owner: DekernAI) -> None:
    dep = owner.deposit_intents.create(block("credit-deposits.mdx", "json deposit.json"))
    assert dep["status"] == "OPEN" and owner.deposit_intents.retrieve(dep["id"])["id"] == dep["id"]
    endpoint = owner.webhook_endpoints.create(
        {"url": "https://hooks.example.test/dekernai", "event_types": ["payment_intent.confirmed"]}
    )
    assert endpoint["secret"].startswith("whsec_")
    assert [e["id"] for e in owner.webhook_endpoints.list()["data"]] == [endpoint["id"]]
    owner.webhook_endpoints.delete(endpoint["id"])


def test_verify_webhook_accepts_what_the_api_signs() -> None:
    body = b'{"id":"evt_1","type":"webhook.test","data":{"object":{}}}'
    header = signing.sign("whsec_test", 1764756000, body)
    assert verify_webhook("whsec_test", header, body, now=1764756000)["id"] == "evt_1"
