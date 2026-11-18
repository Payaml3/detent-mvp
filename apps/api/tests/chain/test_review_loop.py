"""S3 exit check on anvil: a first payment escalates into a case; the reviewer approves with a reason;
the re-run executes and exactly one transfer is sent. A blocked payment never sends."""

from __future__ import annotations

import pytest
from chain_helpers import balance, needs_chain, setup_chain_org
from detent import devchain
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.exceptions.cases import approve
from detent.execution.send import send_payment
from detent.policy.screening import MockScreening
from sqlalchemy import Engine, text

pytestmark = [pytest.mark.db, *needs_chain]


def test_first_payment_escalates_is_approved_and_sent_once(
    engine: Engine, clock: FrozenClock, chain: devchain.LocalChain
) -> None:
    co = setup_chain_org(engine, clock, chain)
    with engine.begin() as c:  # a payee we have never paid before
        c.execute(
            text(
                "UPDATE counterparties SET payment_count=0, median_amount_minor=NULL, median_currency=NULL "
                "WHERE org_id=:o AND id='cpt_local'"
            ),
            {"o": co.id},
        )
    pid = co.payout(engine, clock, "75.00")
    with engine.connect() as c:
        st = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": co.id, "p": pid}
        ).scalar()
        case = c.execute(
            text("SELECT id, reasons FROM exception_cases WHERE org_id=:o AND payment_id=:p"),
            {"o": co.id, "p": pid},
        ).one()
    assert st == "ESCALATED" and list(case.reasons) == ["FIRST_PAYMENT"]
    # Nothing is sent while the payment waits for a person.
    assert (
        send_payment(
            engine, clock, co.adapters, org_id=co.id, payment_id=pid, screening=MockScreening.from_fixture()
        ).value
        == "ESCALATED"
    )
    before = balance(chain, co.payee)
    reviewer = Actor(co.d.org.users[Role.REVIEWER], "reviewer")
    assert (
        approve(
            engine,
            clock,
            case_id=case.id,
            org_id=co.id,
            actor=reviewer,
            reason="New supplier, contract signed",
        ).payment_status
        == "READY"
    )
    import time

    st2 = send_payment(
        engine, clock, co.adapters, org_id=co.id, payment_id=pid, screening=MockScreening.from_fixture()
    ).value
    for _ in range(50):
        if balance(chain, co.payee) - before == 75_000_000:
            break
        time.sleep(0.1)
    assert st2 in ("CONFIRMED", "SUBMITTED")
    assert balance(chain, co.payee) - before == 75_000_000
    # A second send trigger after approval changes nothing.
    send_payment(
        engine, clock, co.adapters, org_id=co.id, payment_id=pid, screening=MockScreening.from_fixture()
    )
    assert balance(chain, co.payee) - before == 75_000_000
