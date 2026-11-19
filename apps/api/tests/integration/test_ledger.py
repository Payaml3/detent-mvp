"""LED-01 and LED-02: a balanced, append-only ledger, and the postings for a payout's life."""

from __future__ import annotations

import pytest
from bank_helpers import pay, send, settle, setup_bank_org
from conftest import OrgFixture
from detent.clock import FrozenClock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.ledger.journal import Line, Unbalanced, account, balances, post, trial_balance
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.db


def test_post_refuses_unbalanced_or_unreferenced(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    with transaction(engine) as c:
        a = account(c, clock, org.id, "platform_operating", "platform", "EUR")
        b = account(c, clock, org.id, "suspense", "suspense", "EUR")
        with pytest.raises(Unbalanced):
            post(
                c,
                clock,
                org_id=org.id,
                kind="x",
                currency="EUR",
                payment_id="pay_x",
                lines=[Line(a, "debit", 100), Line(b, "credit", 99)],
            )
        with pytest.raises(Unbalanced):
            post(
                c,
                clock,
                org_id=org.id,
                kind="x",
                currency="EUR",
                lines=[Line(a, "debit", 1), Line(b, "credit", 1)],
            )
        with pytest.raises(Unbalanced):
            post(
                c,
                clock,
                org_id=org.id,
                kind="x",
                currency="EUR",
                payment_id="pay_x",
                lines=[Line(a, "debit", 0), Line(b, "credit", 0)],
            )
        assert (
            account(c, clock, org.id, "suspense", "suspense", "EUR") == b
        )  # one account per kind/ref/currency


def test_database_refuses_an_unbalanced_entry_at_commit(
    engine: Engine, org: OrgFixture, clock: FrozenClock
) -> None:
    with transaction(engine) as c:
        a = account(c, clock, org.id, "platform_operating", "platform", "GBP")
    j = new_id(Prefix.JRN, clock.now())
    with pytest.raises(DBAPIError, match="unbalanced"), engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO journal_entries (id, org_id, kind, payment_id, created_at) VALUES (:j, :o, 'raw', 'pay_raw', :t)"
            ),
            {"j": j, "o": org.id, "t": clock.now()},
        )
        c.execute(
            text(
                "INSERT INTO postings (id, org_id, journal_id, account_id, direction, amount_minor, currency) "
                "VALUES (:p, :o, :j, :a, 'debit', 500, 'GBP')"
            ),
            {"p": new_id(Prefix.PST, clock.now()), "o": org.id, "j": j, "a": a},
        )
    with pytest.raises(DBAPIError, match="journal_has_reference"), engine.begin() as c:
        c.execute(
            text("INSERT INTO journal_entries (id, org_id, kind, created_at) VALUES (:j, :o, 'raw', :t)"),
            {"j": new_id(Prefix.JRN, clock.now()), "o": org.id, "t": clock.now()},
        )


def test_entries_are_append_only(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    with transaction(engine) as c:
        a = account(c, clock, org.id, "platform_operating", "platform", "EUR")
        b = account(c, clock, org.id, "suspense", "suspense", "EUR")
        j = post(
            c,
            clock,
            org_id=org.id,
            kind="test",
            currency="EUR",
            payment_id="pay_t",
            lines=[Line(a, "debit", 10), Line(b, "credit", 10)],
        )
    for sql in (
        "UPDATE postings SET amount_minor=11 WHERE org_id=:o AND journal_id=:j",
        "DELETE FROM postings WHERE org_id=:o AND journal_id=:j",
        "UPDATE journal_entries SET memo='x' WHERE org_id=:o AND id=:j",
    ):
        with pytest.raises(DBAPIError), engine.begin() as c:
            c.execute(text(sql), {"o": org.id, "j": j})


def _kinds(engine: Engine, org: str, pid: str) -> list[str]:
    """The payment's entry kinds, in life order (entries written in one frozen instant share a timestamp)."""
    order = ["payout.reserve", "payout.settle", "payout.fee", "payout.reverse"]
    with engine.connect() as c:
        ks = (
            c.execute(
                text("SELECT kind FROM journal_entries WHERE org_id=:o AND payment_id=:p"),
                {"o": org, "p": pid},
            )
            .scalars()
            .all()
        )
    return sorted(ks, key=order.index)


def _bal(engine: Engine, org: str) -> dict[tuple[str, str], int]:
    with engine.connect() as c:
        assert set(trial_balance(c, org).values()) <= {0}
        return {(str(b["kind"]), str(b["ref"])): int(b["balance_minor"]) for b in balances(c, org)}  # type: ignore[call-overload]


def test_confirmed_payout_reserves_then_settles_with_the_actual_fee(
    engine: Engine, clock: FrozenClock, bank: str
) -> None:
    bo = setup_bank_org(engine, clock, bank)
    pid = pay(engine, clock, bo, "1000.00")
    assert send(engine, clock, bo, pid) in ("SUBMITTED", "CONFIRMED")
    assert _kinds(engine, bo.id, pid)[0] == "payout.reserve"
    assert settle(engine, clock, bo, pid) == "CONFIRMED"
    assert _kinds(engine, bo.id, pid) == ["payout.reserve", "payout.settle", "payout.fee"]
    b = _bal(engine, bo.id)
    fee = 25 + 100000 * 5 // 10000
    assert b[("platform_operating", "platform")] == 100000
    assert b[("rail_clearing", "banksim-sepa-inst:pending")] == 0
    assert b[("rail_clearing", "banksim-sepa-inst:settled")] == -(100000 + fee)
    assert b[("fees", "banksim-sepa-inst")] == fee


def test_technical_failure_retries_under_one_reservation(
    engine: Engine, clock: FrozenClock, bank: str
) -> None:
    bo = setup_bank_org(engine, clock, bank)
    pid = pay(engine, clock, bo, "100.42")  # .42 fails technically on the bank rail
    send(engine, clock, bo, pid)
    kinds = _kinds(engine, bo.id, pid)
    assert kinds.count("payout.reserve") == 1
    with engine.connect() as c:
        st = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": bo.id, "p": pid}
        ).scalar_one()
    b = _bal(engine, bo.id)
    if st == "FAILED_FINAL":
        assert kinds[-1] == "payout.reverse" and b[("platform_operating", "platform")] == 0
    else:  # retrying: the reservation stays until a final answer
        assert b[("rail_clearing", "banksim-sepa-inst:pending")] == -10042


def test_unknown_keeps_the_reservation(engine: Engine, clock: FrozenClock, bank: str) -> None:
    bo = setup_bank_org(engine, clock, bank, timeout=0.5)
    pid = pay(engine, clock, bo, "100.13")  # .13: the bank holds its answer past our timeout
    assert send(engine, clock, bo, pid) == "UNKNOWN"
    assert _kinds(engine, bo.id, pid) == ["payout.reserve"]
    assert _bal(engine, bo.id)[("rail_clearing", "banksim-sepa-inst:pending")] == -10013
    assert settle(engine, clock, bo, pid) == "CONFIRMED"
    assert _kinds(engine, bo.id, pid) == ["payout.reserve", "payout.settle", "payout.fee"]
