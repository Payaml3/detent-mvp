"""CON-07 reconciliation screen, AUD-02 replay button, deposit cases and the overview match rate."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from conftest import login, make_settings
from decision_helpers import PEPPER, payout
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.domain.roles import Role
from fastapi.testclient import TestClient
from pydantic import SecretStr
from recon_helpers import ReconOrg, build_500
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


@pytest.fixture
def recon(engine: Engine, clock: FrozenClock) -> Iterator[tuple[ReconOrg, TestClient]]:
    ro = build_500(engine, clock)
    s = make_settings(ro.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield ro, c


def test_reconciliation_screen_runs_shows_breaks_and_applies_an_approved_fix(
    recon: tuple[ReconOrg, TestClient], engine: Engine
) -> None:
    ro, c = recon
    login(c, ro.d.org.users[Role.REVIEWER])
    assert "No run yet" in c.get("/console/reconciliation").text
    c.post("/console/reconciliation/run")
    page = c.get("/console/reconciliation").text
    assert "99.40%" in page and page.count('data-break="') == 3
    assert "match to" in page and "credit account" in page and "needs investigation" in page
    assert "Only the payments lead approves a fix" in page
    with engine.connect() as conn:
        brk = conn.execute(
            text("SELECT id FROM recon_breaks WHERE org_id=:o AND subject_key=:k"),
            {"o": ro.id, "k": ro.designed["rail_record_unbooked"]},
        ).scalar_one()
    assert (
        c.post(
            f"/console/reconciliation/breaks/{brk}/approve", data={"reason": "x"}, follow_redirects=False
        ).status_code
        == 403
    )
    login(c, ro.d.org.users[Role.PAYMENTS_LEAD])
    r = c.post(
        f"/console/reconciliation/breaks/{brk}/approve",
        data={"reason": "reference matches"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "error" not in r.headers["location"]
    page = c.get("/console/reconciliation").text
    assert page.count('data-break="') == 2 and "APPLIED" in page
    stats = c.get("/console/overview/stats").text
    assert "99.40%" in stats.split('data-stat="match"', 1)[1][:200]
    runs = c.get("/v1/reconciliation/runs", headers=ro.d.auth()).json()["data"]
    assert runs[0]["match_rate_bps"] == 9940
    assert len(c.get("/v1/reconciliation/breaks?status=OPEN", headers=ro.d.auth()).json()["data"]) == 2


def test_deposit_case_page_and_resolution_rule(recon: tuple[ReconOrg, TestClient], engine: Engine) -> None:
    ro, c = recon
    with engine.connect() as conn:
        case = conn.execute(
            text("SELECT id FROM exception_cases WHERE org_id=:o AND type='deposit'"), {"o": ro.id}
        ).scalar_one()
    login(c, ro.d.org.users[Role.REVIEWER])
    page = c.get(f"/console/exceptions/{case}").text
    assert "held in suspense" in page and "AMOUNT_MISMATCH" in page and "never by a timeout" in page
    r = c.post(f"/v1/exceptions/{case}/approve", json={"reason": "x"}, headers=ro.d.auth())
    assert r.status_code == 409 and r.json()["error"]["code"] == "resolve_via_reconciliation"


def test_payment_detail_has_replay_and_postings(recon: tuple[ReconOrg, TestClient], engine: Engine) -> None:
    ro, c = recon
    pid = c.post(
        "/v1/payment_intents",
        json=payout(
            "cpt_harbor",
            "2400.00",
            "EUR",
            {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"},
        ),
        headers={**ro.d.auth(), "Idempotency-Key": str(uuid.uuid4())},
    ).json()["id"]
    with engine.connect() as conn:
        settled = conn.execute(
            text("SELECT payment_id FROM journal_entries WHERE org_id=:o AND kind='payout.settle' LIMIT 1"),
            {"o": ro.id},
        ).scalar_one()
    login(c, ro.d.org.users[Role.REVIEWER])
    assert f'href="/console/payments/{pid}/replay"' in c.get(f"/console/payments/{pid}").text
    rp = c.get(f"/console/payments/{pid}/replay").text
    assert "Reproduced." in rp and "No model was called" in rp
    detail = c.get(f"/console/payments/{settled}").text.split("<h2>Ledger postings</h2>", 1)[1]
    assert "rail_clearing" in detail and "No postings" not in detail.split("<h2>", 1)[0]
