"""LED-06, LED-07: statement import, the reconciliation run, proposed fixes and applying them."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from bank_helpers import pay, send, settle, setup_bank_org
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.ledger.checks import disagreements
from detent.ledger.journal import balances
from detent.ledger.statements import import_statement, parse_csv
from detent.reconciliation.fixes import FixError, approve_fix, reject_fix
from recon_helpers import build_500, reconcile
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


def _breaks(engine: Engine, org: str) -> dict[str, dict[str, object]]:
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT id, kind, subject_key, proposed_fix, rationale, case_id, status FROM recon_breaks WHERE org_id=:o"
            ),
            {"o": org},
        ).all()
    return {r.subject_key: dict(r._mapping) for r in rows}


def test_500_items_match_at_least_99_percent_and_every_break_gets_a_fix(
    engine: Engine, clock: FrozenClock
) -> None:
    ro = build_500(engine, clock)
    res = reconcile(engine, clock, ro.id)
    assert res.counted == 500 and res.matched == 497 and res.pending == 0
    assert res.match_rate_bps >= 9900 and res.rate_text() == "99.40%"
    b = _breaks(engine, ro.id)
    assert set(b) == set(ro.designed.values())
    fixes = {k: b[v]["proposed_fix"] for k, v in ro.designed.items()}
    assert fixes["payout_missing_on_rail"] == {"action": "needs_investigation", "target": None}
    assert fixes["unallocated_inbound"]["action"] == "match_to"  # type: ignore[index]
    assert fixes["rail_record_unbooked"] == {"action": "credit_account", "target": "acct_c"}
    assert all(x["case_id"] for x in b.values())  # each break is an exception case
    assert all(x["rationale"]["claims"] for x in b.values())  # type: ignore[index]
    # A second run finds the same breaks; it doesn't duplicate them.
    again = reconcile(engine, clock, ro.id)
    assert sorted(again.breaks) == sorted(res.breaks) and len(_breaks(engine, ro.id)) == 3
    with engine.connect() as c:
        assert disagreements(c, ro.id) == []


def test_fixes_apply_only_after_approval_as_new_entries(engine: Engine, clock: FrozenClock) -> None:
    ro = build_500(engine, clock)
    reconcile(engine, clock, ro.id)
    b = _breaks(engine, ro.id)
    unalloc = str(b[ro.designed["unallocated_inbound"]]["id"])
    unbooked = str(b[ro.designed["rail_record_unbooked"]]["id"])
    missing = str(b[ro.designed["payout_missing_on_rail"]]["id"])
    with engine.connect() as c:
        before = {(x["kind"], x["ref"]): x["balance_minor"] for x in balances(c, ro.id)}
        target = c.execute(
            text("SELECT account_ref FROM deposit_intents WHERE org_id=:o AND id=:i"),
            {"o": ro.id, "i": b[ro.designed["unallocated_inbound"]]["proposed_fix"]["target"]},  # type: ignore[index]
        ).scalar_one()
    assert target == "acct_b"
    rv = Actor(ro.d.org.users[Role.REVIEWER], Role.REVIEWER.value)
    pl = Actor(ro.d.org.users[Role.PAYMENTS_LEAD], Role.PAYMENTS_LEAD.value)
    with pytest.raises(FixError, match="may not"):
        approve_fix(engine, clock, org_id=ro.id, break_id=unalloc, actor=rv, reason="ok")
    with pytest.raises(FixError, match="question"):
        approve_fix(engine, clock, org_id=ro.id, break_id=missing, actor=pl, reason="ok")
    approve_fix(
        engine,
        clock,
        org_id=ro.id,
        break_id=unalloc,
        actor=pl,
        reason="Supplier confirmed it was meant for B",
    )
    approve_fix(
        engine, clock, org_id=ro.id, break_id=unbooked, actor=pl, reason="Reference matches C's intent"
    )
    with pytest.raises(FixError, match="APPLIED"):
        approve_fix(engine, clock, org_id=ro.id, break_id=unalloc, actor=pl, reason="twice")
    reject_fix(engine, clock, org_id=ro.id, break_id=missing, actor=pl, reason="Chasing the bank")
    with engine.connect() as c:
        after = {(x["kind"], x["ref"]): x["balance_minor"] for x in balances(c, ro.id)}
        adj = c.execute(
            text(
                "SELECT kind, adjustment_of FROM journal_entries WHERE org_id=:o AND kind LIKE 'adjustment.%'"
            ),
            {"o": ro.id},
        ).all()
        cases = (
            c.execute(
                text(
                    "SELECT status FROM exception_cases WHERE org_id=:o AND id IN (SELECT case_id FROM recon_breaks WHERE org_id=:o)"
                ),
                {"o": ro.id},
            )
            .scalars()
            .all()
        )
        assert disagreements(c, ro.id) == []
    assert after[("user_balance", "acct_b")] == -20_000 and after[("user_balance", "acct_c")] == -7_700
    assert after[("suspense", "suspense")] == before[("suspense", "suspense")] + 20_000
    assert sorted(a.adjustment_of for a in adj) == sorted([unalloc, unbooked])
    assert sorted(cases) == ["OPEN", "RESOLVED", "RESOLVED"]
    res = reconcile(engine, clock, ro.id)
    assert res.counted == 500 and res.matched == 499  # only the rejected payout break remains


def test_statement_import_is_idempotent_per_date_json_and_csv(
    engine: Engine, clock: FrozenClock, bank: str
) -> None:
    bo = setup_bank_org(engine, clock, bank)
    pid = pay(engine, clock, bo, "250.00")
    send(engine, clock, bo, pid)
    assert settle(engine, clock, bo, pid) == "CONFIRMED"
    bo.adapter.receiving_account = bo.id
    day = datetime.now(UTC).date()  # the simulator dates its statement by its own clock
    first = import_statement(
        engine, clock, org_id=bo.id, rail_id="banksim-sepa-inst", adapter=bo.adapter, day=day, fmt="csv"
    )
    again = import_statement(
        engine, clock, org_id=bo.id, rail_id="banksim-sepa-inst", adapter=bo.adapter, day=day
    )
    assert first.new and not again.new and first.lines == again.lines
    with engine.connect() as c:
        n = c.execute(text("SELECT count(*) FROM rail_records WHERE org_id=:o"), {"o": bo.id}).scalar_one()
    assert n == first.lines
    csv_lines = parse_csv(bo.adapter.statement(day.isoformat(), "csv"))
    assert all(ln.direction in ("in", "out") for ln in csv_lines)


def test_real_bank_payout_reconciles_against_the_imported_statement(
    engine: Engine, clock: FrozenClock, bank: str
) -> None:
    bo = setup_bank_org(engine, clock, bank)
    bo.adapter.receiving_account = bo.id
    pid = pay(engine, clock, bo, "321.00")
    send(engine, clock, bo, pid)
    assert settle(engine, clock, bo, pid) == "CONFIRMED"
    assert reconcile(engine, clock, bo.id).pending == 1  # no statement yet: pending, not a break
    import_statement(
        engine,
        clock,
        org_id=bo.id,
        rail_id="banksim-sepa-inst",
        adapter=bo.adapter,
        day=datetime.now(UTC).date(),
    )
    res = reconcile(engine, clock, bo.id)
    assert (res.counted, res.matched, res.breaks) == (1, 1, [])
