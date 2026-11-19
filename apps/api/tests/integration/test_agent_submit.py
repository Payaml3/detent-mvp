"""AGT-02 (no submit until each flag is resolved), AGT-03 (propose only, through the public API), CON-05."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from conftest import login, make_settings
from decision_helpers import PEPPER, DecisionOrg, setup_decision_org
from detent.agents.instruction import propose_from_invoice
from detent.agents.llm import RecordedLLM
from detent.agents.submit import NotReady, intent_body, resolve_flags, submit_proposal
from detent.api.app import create_app
from detent.api.auth import issue_key
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.mandates.store import fixture_mandate, issue_mandate
from detent.settings import REPO_ROOT
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

KEY = SecretStr("test-mandate-key-0123456789abcdef")


def _agent_key() -> str:
    import secrets

    return "sk_" + "test_agent" + secrets.token_hex(16)


INVOICES = REPO_ROOT / "fixtures" / "invoices"


@pytest.fixture
def agent_key() -> str:
    return _agent_key()


@pytest.fixture
def d(engine: Engine, clock: FrozenClock, agent_key: str) -> DecisionOrg:
    org = setup_decision_org(engine, clock)
    with engine.begin() as c:
        issue_mandate(c, clock, org.id, fixture_mandate(clock, org.id), KEY, actor=Actor.system("seed"))
        issue_key(
            c,
            clock,
            org.id,
            org.org.users[Role.PAYMENTS_LEAD],
            ["intents:create"],
            PEPPER,
            mandate_id="mnd_demo_ap_agent",
            key=agent_key,
        )
    return org


@pytest.fixture
def client(d: DecisionOrg, engine: Engine, clock: FrozenClock, agent_key: str) -> Iterator[TestClient]:
    s = make_settings(
        d.id,
        api_key_pepper=SecretStr(PEPPER),
        mandate_signing_key_demo=KEY,
        agent_api_key=SecretStr(agent_key),
        agent_llm="recorded",
    )
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def doc(name: str, d: DecisionOrg) -> str:
    raw = (INVOICES / name).read_text()
    for k, v in d.wallets.items():
        raw = raw.replace("{{" + k + "}}", v)
    return raw


def propose(engine: Engine, clock: FrozenClock, d: DecisionOrg, name: str) -> Any:
    llm = RecordedLLM.from_dir(
        REPO_ROOT / "fixtures" / "agent-recordings" / "instruction", placeholders=d.wallets
    )
    return propose_from_invoice(
        engine,
        clock,
        org_id=d.id,
        document=doc(name, d),
        mandate_id="mnd_demo_ap_agent",
        llm=llm,
        model="claude-sonnet-5-5",
        daily_token_budget=2_000_000,
    )


def test_clean_proposal_submits_as_agent_and_escalates(
    agent_key: str, engine: Engine, clock: FrozenClock, d: DecisionOrg, client: TestClient
) -> None:
    p = propose(engine, clock, d, "inv-canonical-18500-usdc.txt")
    r = submit_proposal(engine, clock, client, agent_key=agent_key, org_id=d.id, proposal_id=p.id)
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["source"] == "agent" and j["status"] == "ESCALATED"
    reasons = {c.get("reason") for c in j["decision"]["checks"]}
    assert {"FIRST_PAYMENT", "ABOVE_AUTO_LIMIT"} <= reasons and j["decision"]["checks"][0]["result"] == "PASS"
    again = submit_proposal(engine, clock, client, agent_key=agent_key, org_id=d.id, proposal_id=p.id)
    assert again.json()["id"] == j["id"]  # the proposal ID is the idempotency key
    with engine.connect() as c:
        row = c.execute(
            text("SELECT status, payment_id FROM agent_calls WHERE org_id=:o AND id=:i"),
            {"o": d.id, "i": p.id},
        ).one()
    assert tuple(row) == ("submitted", j["id"])


def test_flagged_proposal_cannot_be_submitted_until_each_flag_is_resolved(
    agent_key: str, engine: Engine, clock: FrozenClock, d: DecisionOrg, client: TestClient
) -> None:
    p = propose(engine, clock, d, "inv-missing-network.txt")
    with pytest.raises(NotReady, match="MISSING_NETWORK"):
        intent_body(engine, d.id, p.id)
    lead = Actor(d.org.users[Role.REVIEWER], "reviewer")
    with pytest.raises(ValueError, match="network"):
        resolve_flags(engine, clock, org_id=d.id, proposal_id=p.id, actor=lead, values={})
    resolve_flags(
        engine,
        clock,
        org_id=d.id,
        proposal_id=p.id,
        actor=lead,
        values={"network": "base-sepolia"},
        note="Confirmed Base Sepolia with the supplier by phone",
    )
    body = intent_body(engine, d.id, p.id)
    assert body["destination"]["network"] == "base-sepolia" and body["source"] == "agent"
    r = submit_proposal(engine, clock, client, agent_key=agent_key, org_id=d.id, proposal_id=p.id)
    assert r.status_code == 201
    with engine.connect() as c:
        ev = c.execute(
            text("SELECT actor, payload FROM audit_events WHERE org_id=:o AND kind='agent.flags_resolved'"),
            {"o": d.id},
        ).one()
    assert ev.actor == lead.id and ev.payload["values"] == {"network": "base-sepolia"}


def test_injected_invoice_submits_only_what_the_document_says(
    engine: Engine, clock: FrozenClock, d: DecisionOrg
) -> None:
    p = propose(engine, clock, d, "inv-injection-body.txt")
    resolve_flags(
        engine,
        clock,
        org_id=d.id,
        proposal_id=p.id,
        actor=Actor(d.org.users[Role.REVIEWER], "reviewer"),
        values={},
        note="Instruction text ignored; amount and wallet checked against the invoice",
    )
    body = intent_body(engine, d.id, p.id)
    assert body["amount"] == {"amount": "9000.00", "currency": "USDC"}
    assert body["destination"]["address"] == d.wallets["WALLET_BLUEFIN_BASE"]
    assert "allowlist" not in str(body).lower()


def test_agent_key_cannot_call_other_write_endpoints(
    agent_key: str, engine: Engine, d: DecisionOrg, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.INFO)
    h = {"Authorization": f"Bearer {agent_key}"}
    for method, path in [
        ("post", "/v1/kill_switch"),
        ("post", "/v1/exceptions/exc_x/approve"),
        ("post", "/v1/mandates/mnd_demo_ap_agent/revoke"),
        ("post", "/v1/decisions"),
    ]:
        r = getattr(client, method)(path, headers={**h, "Idempotency-Key": "z"}, json={"reason": "x"})
        assert r.status_code in (403, 422), (path, r.status_code)
        if r.status_code == 403:
            assert r.json()["error"]["code"] in ("insufficient_scope", "mandate_mismatch")
    logged = [r for r in caplog.records if r.name == "detent.http" and getattr(r, "status", None) == 403]
    assert len(logged) >= 3


def test_console_invoice_drop_and_submit(engine: Engine, d: DecisionOrg, client: TestClient) -> None:
    login(client, d.org.users[Role.REVIEWER])
    page = client.get("/console/invoices").text
    assert "Drop an invoice" in page and "mnd_demo_ap_agent" in page
    r = client.post(
        "/console/invoices", data={"text": doc("inv-canonical-18500-usdc.txt", d)}, follow_redirects=False
    )
    assert r.status_code == 303
    html = client.get(r.headers["location"]).text
    assert "18500.00" in html and "<mark" in html and "No flags" in html
    assert "Recorded response" in html  # offline: the page says the answer was not a live model call
    assert "mnd_demo_ap_agent" in html and "20000.00 USDC" in html
    pid = r.headers["location"].rsplit("/", 1)[1]
    s = client.post(f"/console/invoices/{pid}/submit", follow_redirects=False)
    assert s.status_code == 303
    out = client.get(s.headers["location"]).text
    assert "ESCALATED" in out and "FIRST_PAYMENT" in out


def test_console_flagged_invoice_shows_flags_and_blocks_submit(
    engine: Engine, d: DecisionOrg, client: TestClient
) -> None:
    login(client, d.org.users[Role.REVIEWER])
    r = client.post("/console/invoices", data={"text": doc("inv-two-wallets.txt", d)}, follow_redirects=False)
    html = client.get(r.headers["location"]).text
    assert "MULTIPLE_WALLETS" in html and "Resolve each flag before submitting" in html
    pid = r.headers["location"].rsplit("/", 1)[1]
    assert client.post(f"/console/invoices/{pid}/submit", follow_redirects=False).status_code == 409
