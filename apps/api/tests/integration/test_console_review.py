"""CON-01, CON-03, CON-04, EXC-02: the console shell, payments, the exceptions queue and raw facts first."""

from __future__ import annotations

import re
import uuid

import pytest
from conftest import login, make_settings
from decision_helpers import PEPPER, payout, setup_decision_org
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.domain.roles import Role
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

NAV = [
    "Overview",
    "Payments",
    "Exceptions",
    "Reconciliation",
    "Rails",
    "Policy",
    "Mandates",
    "Counterparties",
    "Outbox",
    "Incidents",
    "Audit",
    "Evaluation",
    "Settings",
]


@pytest.fixture
def setup(engine: Engine, clock: FrozenClock):  # type: ignore[no-untyped-def]
    d = setup_decision_org(engine, clock)
    app = create_app(
        make_settings(d.id, api_key_pepper=SecretStr(PEPPER)),
        engine=engine,
        clock=clock,
        configure_logging=False,
    )
    with TestClient(app) as c:
        dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": d.wallets["WALLET_BLUEFIN_BASE"]}
        r = c.post(
            "/v1/payment_intents",
            json=payout("cpt_bluefin", "18500.00", "USDC", dest, reference="INV-2026-0142"),
            headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())},
        )
        pid = r.json()["id"]
        case_id = r.json()["exception"]["id"]
        login(c, d.org.users[Role.REVIEWER])
        yield c, d, pid, case_id


def test_every_page_has_the_banner_nav_and_honest_wording(setup) -> None:  # type: ignore[no-untyped-def]
    c, *_ = setup
    for path in [
        "/console/",
        "/console/payments",
        "/console/exceptions",
        "/console/outbox",
        "/console/counterparties",
    ]:
        html = c.get(path).text
        assert "Prototype · test networks · simulated bank rail" in html, path
        for item in NAV:
            assert f">{item}<" in html, (path, item)
        low = html.lower()
        assert "payments company" not in low and "payment provider" not in low
    home = c.get("/console/").text
    assert "agentic payment controls" in home.lower()
    for layer in ("Decision", "Orchestration", "Operations"):
        assert layer in home


def test_unbuilt_sections_say_so(setup) -> None:  # type: ignore[no-untyped-def]
    c, *_ = setup
    html = c.get("/console/evaluation").text
    assert c.get("/console/evaluation").status_code == 200 and "not built yet" in html.lower()


def test_payments_list_and_detail(setup) -> None:  # type: ignore[no-untyped-def]
    c, _d, pid, _ = setup
    lst = c.get("/console/payments").text
    assert pid in lst and "ESCALATED" in lst
    det = c.get(f"/console/payments/{pid}").text
    for check in ("first_payment", "auto_limit", "screening", "travel_rule"):
        assert check in det
    assert "FIRST_PAYMENT" in det and "ABOVE_AUTO_LIMIT" in det
    assert "Attempts" in det and "Ledger postings" in det and "Timeline" in det and "Route" in det
    assert "payment.received" in det and "decision.made" in det
    assert f'href="/console/payments/{pid}/replay"' in det  # AUD-02
    assert c.get("/console/payments/pay_nope").status_code == 404


def test_exceptions_queue_filters_and_countdown(setup, clock: FrozenClock) -> None:  # type: ignore[no-untyped-def]
    c, d, _pid, case_id = setup
    q = c.get("/console/exceptions").text
    assert case_id in q and "2h 0m left" in q
    assert case_id in c.get(f"/console/exceptions?owner={d.org.users[Role.REVIEWER]}").text
    assert case_id not in c.get(f"/console/exceptions?owner={d.org.users[Role.BACKUP_OWNER]}").text
    assert case_id in c.get("/console/exceptions?tier=1").text
    assert case_id not in c.get("/console/exceptions?tier=2").text
    assert case_id not in c.get("/console/exceptions?overdue=1").text


def test_case_page_shows_raw_facts_first(setup) -> None:  # type: ignore[no-untyped-def]
    from web3 import Web3

    c, d, _pid, case_id = setup
    html = c.get(f"/console/exceptions/{case_id}").text
    full = Web3.to_checksum_address(d.wallets["WALLET_BLUEFIN_BASE"])
    facts = html.index('data-section="raw-facts"')
    assert full in html and html.index(full) > facts
    assert "Bluefin Components Ltd (fictional)" in html
    assert "First seen" in html and "Last changed" in html and "Median" in html and "Mandate scope" in html
    assert "auto_limit: 10000.00" in html  # each rule hit with its parameters
    agent = html.index('data-section="agent-evidence"')
    assert agent > facts and re.search(r'<details[^>]*data-section="agent-evidence"(?![^>]*open)', html)
    assert html.index('name="reason"') > facts


def test_console_approve_requires_reason_and_permission(setup, engine: Engine) -> None:  # type: ignore[no-untyped-def]
    c, d, pid, case_id = setup
    assert (
        c.post(
            f"/console/exceptions/{case_id}/approve", data={"reason": " "}, follow_redirects=False
        ).status_code
        == 400
    )
    login(c, d.org.users[Role.COMPLIANCE_LEAD])
    assert (
        c.post(
            f"/console/exceptions/{case_id}/approve", data={"reason": "x"}, follow_redirects=False
        ).status_code
        == 403
    )
    login(c, d.org.users[Role.REVIEWER])
    r = c.post(
        f"/console/exceptions/{case_id}/approve",
        data={"reason": "Checked the invoice"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with engine.connect() as cn:
        st = cn.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": d.id, "p": pid}
        ).scalar()
    assert st == "READY"


def test_outbox_lists_assignment_notices(setup) -> None:  # type: ignore[no-untyped-def]
    c, d, *_ = setup
    html = c.get("/console/outbox").text
    assert "case.assigned" in html and f"{d.org.users[Role.REVIEWER]}@test.invalid" in html
    assert "not sent" in html.lower()
