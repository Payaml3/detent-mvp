"""CON-02 overview, CON-06 policy and mandates, and the S6 console paths (EXC-03, EXC-06, EXE-09, POL-07)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from conftest import login, make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.exceptions.deadlines import sweep
from fastapi.testclient import TestClient
from policy_helpers import v2
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db
HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}


def client(engine: Engine, clock: FrozenClock, mode: str = "auto") -> tuple[DecisionOrg, TestClient]:
    d = setup_decision_org(engine, clock, mode=mode)
    app = create_app(
        make_settings(d.id, api_key_pepper=SecretStr(PEPPER)),
        engine=engine,
        clock=clock,
        configure_logging=False,
    )
    return d, TestClient(app)


@pytest.fixture
def auto(engine: Engine, clock: FrozenClock) -> Iterator[tuple[DecisionOrg, TestClient]]:
    d, c = client(engine, clock)
    with c:
        yield d, c


def bluefin(c: TestClient, d: DecisionOrg) -> dict[str, Any]:
    dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": d.wallets["WALLET_BLUEFIN_BASE"]}
    r = c.post(
        "/v1/payment_intents",
        json=payout("cpt_bluefin", "18500.00", "USDC", dest, reference="INV-2026-0142"),
        headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())},
    )
    return dict(r.json())


def harbor(c: TestClient, d: DecisionOrg) -> dict[str, Any]:
    r = c.post(
        "/v1/payment_intents",
        json=payout("cpt_harbor", "2000.00", "EUR", HARBOR),
        headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())},
    )
    return dict(r.json())


# ------------------------------------------------------------------------------------------ CON-02
def test_overview_counts_and_polls(
    auto: tuple[DecisionOrg, TestClient], clock: FrozenClock, engine: Engine
) -> None:
    d, c = auto
    harbor(c, d)
    bluefin(c, d)
    clock.advance(timedelta(hours=3))
    sweep(engine, clock, d.id)
    login(c, d.org.users[Role.PAYMENTS_LEAD])
    html = c.get("/console/").text
    assert 'hx-get="/console/overview/stats"' in html and 'hx-trigger="every 5s"' in html
    assert "/static/htmx-2.0.4.min.js" in html
    part = c.get("/console/overview/stats").text
    assert "<html" not in part  # a fragment for htmx to swap in
    for stat, value in (
        ("execute", "1"),
        ("escalate", "1"),
        ("block", "0"),
        ("auto", "50%"),
        ("overdue", "1"),
        ("timeout", "0"),
        ("unknown", "0"),
    ):
        chunk = part.split(f'data-stat="{stat}"', 1)[1][:120]
        assert f">{value}<" in chunk, (stat, chunk)
    assert "Match rate: no reconciliation run yet" in part
    assert "case.overdue" in part  # recent events
    assert "Mode: <strong>auto</strong>" in part
    assert c.get("/static/htmx-2.0.4.min.js").status_code == 200


# ---------------------------------------------------------------------------------- CON-06, POL-07
def test_policy_screen_propose_diff_and_two_person_activation(
    auto: tuple[DecisionOrg, TestClient], engine: Engine
) -> None:
    d, c = auto
    login(c, d.org.users[Role.PAYMENTS_LEAD])
    page = c.get("/console/policy").text
    assert "Active: version 1" in page and "version: 2" in page  # the template draft is the next version
    looser = v2(('auto_limit: {USDC: "10000.00"', 'auto_limit: {USDC: "15000.00"'))
    r = c.post("/console/policy/propose", data={"yaml_text": looser}, follow_redirects=False)
    assert r.status_code == 303 and "error" not in r.headers["location"]
    page = c.get("/console/policy").text
    assert "Draft: version 2" in page and ">loosening<" in page and "LIMIT_RAISED" in page
    assert "checks.limits.auto_limit.USDC" in page and "15000.00" in page
    assert "Approve and activate" not in page  # the proposer can't approve
    r = c.post(f"/console/policy/{_draft(engine, d)}/approve", data={}, follow_redirects=False)
    assert "error" in r.headers["location"]
    login(c, d.org.users[Role.COMPLIANCE_LEAD])
    page = c.get("/console/policy").text
    assert "Approve and activate version 2" in page and 'name="attest"' in page
    r = c.post(f"/console/policy/{_draft(engine, d)}/approve", data={"attest": "yes"}, follow_redirects=False)
    assert "error" not in r.headers["location"]
    page = c.get("/console/policy").text
    assert "Active: version 2" in page and "AML accountability" in page
    assert "superseded" in page.split('data-section="history"', 1)[1]


def _draft(engine: Engine, d: DecisionOrg) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                text("SELECT id FROM policy_versions WHERE org_id=:o AND status='draft'"), {"o": d.id}
            ).scalar_one()
        )


def test_reviewer_sees_policy_but_cannot_propose(auto: tuple[DecisionOrg, TestClient]) -> None:
    d, c = auto
    login(c, d.org.users[Role.REVIEWER])
    assert "Propose a new version" not in c.get("/console/policy").text
    assert (
        c.post("/console/policy/propose", data={"yaml_text": v2()}, follow_redirects=False).status_code == 403
    )


def test_mandates_screen_shows_scope_usage_expiry_and_revoke(
    auto: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    from detent.mandates.store import fixture_mandate, issue_mandate

    d, c = auto
    with engine.begin() as conn:
        m = issue_mandate(
            conn,
            clock,
            d.id,
            fixture_mandate(clock, d.id),
            SecretStr("test-mandate-key-0123456789"),
            actor=Actor(d.org.users[Role.PAYMENTS_LEAD], Role.PAYMENTS_LEAD.value),
        )
    login(c, d.org.users[Role.PAYMENTS_LEAD])
    page = c.get("/console/mandates").text
    assert m in page and "used of" in page and "Valid" in page and "Revoke mandate" in page


# --------------------------------------------------------------------------------------- EXE-09
def test_settings_mode_change_needs_both_leads(auto: tuple[DecisionOrg, TestClient], engine: Engine) -> None:
    d, c = auto
    login(c, d.org.users[Role.PAYMENTS_LEAD])
    page = c.get("/console/settings").text
    assert "Mode: auto" in page and "Orchestrate" in page
    c.post("/console/settings/mode/propose", data={"to_mode": "assist", "reason": "pilot"})
    page = c.get("/console/settings").text
    assert "Change to <strong>assist</strong>" in page and "Approve the change" not in page
    login(c, d.org.users[Role.COMPLIANCE_LEAD])
    page = c.get("/console/settings").text
    assert "Approve the change to assist" in page
    with engine.connect() as conn:
        ch = conn.execute(text("SELECT id FROM mode_changes WHERE org_id=:o"), {"o": d.id}).scalar_one()
    c.post(f"/console/settings/mode/{ch}/approve")
    assert "Mode: assist" in c.get("/console/settings").text
    login(c, d.org.users[Role.REVIEWER])
    assert (
        c.post(
            "/console/settings/mode/propose", data={"to_mode": "auto", "reason": "x"}, follow_redirects=False
        ).status_code
        == 403
    )


def test_assist_send_button(engine: Engine, clock: FrozenClock) -> None:
    d, c = client(engine, clock, mode="assist")
    with c:
        pid = harbor(c, d)["id"]
        login(c, d.org.users[Role.PAYMENTS_LEAD])  # the initiator: no Send button
        page = c.get(f"/console/payments/{pid}").text
        assert 'data-section="send"' in page and f'action="/console/payments/{pid}/send"' not in page
        login(c, d.org.users[Role.REVIEWER])
        page = c.get(f"/console/payments/{pid}").text
        assert f'action="/console/payments/{pid}/send"' in page
        r = c.post(f"/console/payments/{pid}/send", follow_redirects=False)
        assert r.status_code == 303 and "error" not in r.headers["location"]
        assert 'data-section="send"' not in c.get(f"/console/payments/{pid}").text


# --------------------------------------------------------------------------------- EXC-03, EXC-06
def test_case_page_shows_cited_claims_and_overdue_rules(
    auto: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    from detent.runtime import Runtime
    from detent.worker.loop import Worker

    d, c = auto
    case_id = bluefin(c, d)["exception"]["id"]
    login(c, d.org.users[Role.REVIEWER])
    page = c.get(f"/console/exceptions/{case_id}").text
    assert "still working" in page and "Approve and re-run" in page  # usable before the agent finishes
    w = Worker(Runtime(make_settings(d.id), engine, clock), worker_id="console-test")
    while w.run_one():
        pass
    page = c.get(f"/console/exceptions/{case_id}").text
    agent = page.split('data-section="agent-evidence"', 1)[1]
    assert page.index('data-section="raw-facts"') < page.index('data-section="agent-evidence"')
    assert "Recommendation: <strong>approve</strong>" in agent and "UNCITED_CLAIMS_REMOVED" in agent
    assert "by phone" not in agent  # the uncited claim is not shown
    assert "[ev_cpt_cpt_bluefin]" in agent and "offline stand-in" in agent
    clock.advance(timedelta(hours=2, minutes=5))
    sweep(engine, clock, d.id)
    page = c.get(f"/console/exceptions/{case_id}").text
    assert "HELD_OVERDUE" in page and "Approve and re-run" not in page
    assert "only the case's current owner or the payments lead" in page
    login(c, d.org.users[Role.BACKUP_OWNER])
    assert "Approve and re-run" in c.get(f"/console/exceptions/{case_id}").text
    q = c.get("/console/exceptions?overdue=1").text
    assert case_id in q
