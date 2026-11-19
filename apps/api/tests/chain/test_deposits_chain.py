"""LED-04, LED-05 on a chain rail (local anvil): Transfer logs to deposit addresses, credited once."""

from __future__ import annotations

import uuid

import pytest
from chain_helpers import needs_chain, send_usdc, setup_chain_org
from detent import devchain
from detent.clock import FrozenClock
from detent.ledger.credit import process_pending
from detent.ledger.deposits import DepositRequest, create_deposit_intent
from detent.ledger.watchers import watch_evm
from detent.policy.screening import MockScreening
from sqlalchemy import Engine, text

pytestmark = [pytest.mark.db, *needs_chain]
SCREEN = MockScreening.from_fixture()
FLAGGED = "0x000000000000000000000000000000000000dEaD"


def intent(engine: Engine, clock: FrozenClock, org: str, account: str, amount: str) -> dict[str, object]:
    req = DepositRequest.model_validate(
        {
            "account_ref": account,
            "currency": "USDC",
            "network": "local-evm",
            "expected_amount": {"amount": amount, "currency": "USDC"},
        }
    )
    code, body = create_deposit_intent(
        engine, clock, org_id=org, actor_id="usr_api", idempotency_key=str(uuid.uuid4()), request=req
    )
    assert code == 201, body
    return body


def test_chain_deposit_is_seen_once_and_credited_once(
    engine: Engine, clock: FrozenClock, chain: devchain.LocalChain
) -> None:
    co = setup_chain_org(engine, clock, chain)
    d = intent(engine, clock, co.id, "acct_u1001", "500.00")
    addr = str(d["instructions"]["address"])  # type: ignore[index]
    payer = chain.accounts[2]
    send_usdc(chain, payer, addr, 500 * 10**6)
    assert watch_evm(engine, clock, co.id, "local-evm", co.adapter) == 1
    with engine.begin() as c:  # a restarted watcher rescans from scratch: still one row
        c.execute(text("DELETE FROM watch_cursors WHERE org_id=:o"), {"o": co.id})
    assert watch_evm(engine, clock, co.id, "local-evm", co.adapter) == 0
    [o] = process_pending(engine, clock, org_id=co.id, screening=SCREEN)
    assert o.status == "CREDITED"
    assert process_pending(engine, clock, org_id=co.id, screening=SCREEN) == []
    with engine.connect() as c:
        inb = c.execute(
            text("SELECT from_address, network, currency FROM inbound_transfers WHERE org_id=:o"),
            {"o": co.id},
        ).one()
        rec = c.execute(
            text("SELECT direction, source FROM rail_records WHERE org_id=:o"), {"o": co.id}
        ).all()
    assert inb.from_address.lower() == payer.lower() and inb.network == "local-evm" and inb.currency == "USDC"
    assert [(r.direction, r.source) for r in rec] == [("in", "chain")]


def test_flagged_sender_is_held_in_suspense(
    engine: Engine, clock: FrozenClock, chain: devchain.LocalChain
) -> None:
    co = setup_chain_org(engine, clock, chain)
    addr = str(intent(engine, clock, co.id, "acct_u1002", "60.00")["instructions"]["address"])  # type: ignore[index]
    send_usdc(chain, FLAGGED, addr, 60 * 10**6)
    watch_evm(engine, clock, co.id, "local-evm", co.adapter)
    [o] = process_pending(engine, clock, org_id=co.id, screening=SCREEN)
    assert o.status == "SUSPENSE" and o.reasons == ["SCREENING_HIT"] and o.case_id


def test_outbound_payouts_are_recorded_for_reconciliation(
    engine: Engine, clock: FrozenClock, chain: devchain.LocalChain
) -> None:
    from detent.execution.send import send_payment

    co = setup_chain_org(engine, clock, chain)
    pid = co.payout(engine, clock, "12.00")
    send_payment(engine, clock, co.adapters, org_id=co.id, payment_id=pid, screening=SCREEN)
    watch_evm(engine, clock, co.id, "local-evm", co.adapter)
    with engine.connect() as c:
        rec = c.execute(
            text("SELECT direction, amount_minor, party FROM rail_records WHERE org_id=:o"), {"o": co.id}
        ).all()
    assert [(r.direction, int(r.amount_minor), r.party.lower()) for r in rec] == [
        ("out", 12_000_000, co.payee.lower())
    ]
