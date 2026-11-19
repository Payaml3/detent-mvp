"""LED-05, LED-06 AC5 on the demo batch (fixtures/batches/demo-batch-20.yaml): every demo deposit credits
once (the duplicate notification included) and reconciliation shows exactly one designed break, dep-07.

Two local anvil chains stand in for Base Sepolia and Ethereum Sepolia (test only). The batch's platform
payouts run on the simulated bank rail. Its user payouts (p07 to p20) are not run: user payouts are
deferred (founder decision before S1)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import yaml
from chain_helpers import needs_chain, send_usdc
from decision_helpers import payout, setup_decision_org
from detent import devchain
from detent.clock import FrozenClock
from detent.execution.send import send_payment
from detent.intents.service import IntentRequest, submit_intent
from detent.ledger.credit import process_pending
from detent.ledger.deposits import DepositRequest, create_deposit_intent, deposit_address
from detent.ledger.statements import import_statement
from detent.ledger.watchers import watch_bank, watch_evm
from detent.policy.screening import MockScreening
from detent.rails.banksim import BankAdapter
from detent.rails.evm import EvmAdapter
from detent.rails.registry import install_rail
from detent.rails.signer import LocalKeySigner
from detent.settings import REPO_ROOT
from recon_helpers import reconcile
from sqlalchemy import Engine, text

pytestmark = [pytest.mark.db, *needs_chain]
BATCH = yaml.safe_load((REPO_ROOT / "fixtures" / "batches" / "demo-batch-20.yaml").read_text())
SCREEN = MockScreening.from_fixture()
HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}


def _minor(amount: str) -> int:
    whole, frac = amount.split(".")
    return int(whole) * 100 + int(frac)


def test_demo_batch_credits_once_and_dep07_is_the_only_break(
    engine: Engine, clock: FrozenClock, chain: devchain.LocalChain, chain_b: devchain.LocalChain, bank: str
) -> None:
    from chain_helpers import new_wallet

    d = setup_decision_org(engine, clock)
    org = d.id
    chains = {"base-sepolia": (chain, 84532), "eth-sepolia": (chain_b, 11155111)}
    evm: dict[str, EvmAdapter] = {}
    with engine.begin() as c:
        for rid, (ch, cid) in chains.items():
            sender, key = new_wallet(ch, usdc_minor=10**12)
            install_rail(
                c,
                org,
                rail_id=rid,
                kind="evm",
                network=rid,
                chain_id=cid,
                currency="USDC",
                token_address=ch.usdc_address,
                from_address=sender,
                confirmations=1,
            )
            evm[rid] = EvmAdapter(
                rail_id=rid,
                rpc_url=ch.rpc_url,
                expected_chain_id=cid,
                token_address=ch.usdc_address,
                signer=LocalKeySigner(key),
                confirmations=1,
                check_chain=False,
            )
        for rid, cur in (("banksim-fps", "GBP"), ("banksim-sepa-inst", "EUR")):
            install_rail(c, org, rail_id=rid, kind="banksim", network=rid, currency=cur, fee_flat_minor=20)
    banks = {
        rid: BankAdapter(
            rail_id=rid,
            base_url=bank,
            scheme=sch,
            currency=cur,
            per_payment_limit_minor=None,
            receiving_account=org,
        )
        for rid, sch, cur in (("banksim-fps", "fps", "GBP"), ("banksim-sepa-inst", "sepa_inst", "EUR"))
    }

    # Platform payouts in the batch that move money on the bank rail.
    for p in BATCH["payouts"]:
        if p.get("counterparty") != "cpt_harbor":
            continue
        req = IntentRequest.model_validate(
            payout("cpt_harbor", p["amount"], "EUR", HARBOR, reference=p["ref"])
        )
        _, body = submit_intent(
            engine,
            clock,
            org_id=org,
            actor_id="usr_api",
            idempotency_key=f"demo-{p['ref']}",
            request=req,
            decision_only=False,
            screening=SCREEN,
        )
        if body["status"] == "READY":
            send_payment(engine, clock, dict(banks), org_id=org, payment_id=str(body["id"]), screening=SCREEN)

    # The eight demo deposits.
    intents: dict[str, dict[str, Any]] = {}
    for dep in BATCH["deposits"]:
        network = dep.get("network") or dep.get("rail")
        req = DepositRequest.model_validate(
            {
                "account_ref": dep["account"],
                "currency": dep["currency"],
                "network": network,
                "expected_amount": {"amount": dep["amount"], "currency": dep["currency"]},
            }
        )
        _, intents[dep["ref"]] = create_deposit_intent(
            engine, clock, org_id=org, actor_id="usr_api", idempotency_key=f"demo-{dep['ref']}", request=req
        )
    payer = chain.accounts[3]
    for dep in BATCH["deposits"]:
        minor = _minor(dep["amount"])
        if dep.get("rail"):
            ref = intents[dep["ref"]]["instructions"]["reference"]
            body = {
                "scheme": "fps",
                "amount_minor": minor,
                "reference": ref,
                "payer": "Demo payer (fictional)",
                "account": org,
                "id": f"bin_demo_{org[-8:]}_{dep['ref']}",
            }
            httpx.post(f"{bank}/inbound", json=body)
            if dep.get("duplicate_notification"):
                httpx.post(f"{bank}/inbound", json=body)
            continue
        if dep.get("sent_to"):  # dep-07: sent on Base Sepolia to acct_u1002's address instead
            ch, to = chain, deposit_address(org, "acct_u1002", "base-sepolia")
        else:
            ch, to = chains[dep["network"]][0], str(intents[dep["ref"]]["instructions"]["address"])
        send_usdc(ch, payer if ch is chain else ch.accounts[3], to, minor * 10**4)

    # Watch (dep-08's duplicate notification is a second pass over the same blocks), decide, import, reconcile.
    for _ in range(2):
        for rid, a in evm.items():
            watch_evm(engine, clock, org, rid, a)
        with engine.begin() as c:
            c.execute(
                text("DELETE FROM watch_cursors WHERE org_id=:o AND rail_id='base-sepolia'"), {"o": org}
            )
        for rid, b in banks.items():
            watch_bank(engine, clock, org, rid, b)
    process_pending(engine, clock, org_id=org, screening=SCREEN)
    import time

    from bank_helpers import BankOrg, settle

    with engine.connect() as c:
        ready = (
            c.execute(
                text("SELECT id FROM payment_intents WHERE org_id=:o AND status='SUBMITTED'"), {"o": org}
            )
            .scalars()
            .all()
        )
    for pid in ready:
        assert settle(engine, clock, BankOrg(d, bank, banks["banksim-sepa-inst"]), pid) == "CONFIRMED"
    time.sleep(0.2)
    for rid, b in banks.items():
        import_statement(engine, clock, org_id=org, rail_id=rid, adapter=b, day=datetime.now(UTC).date())
    for rid, a in evm.items():
        watch_evm(engine, clock, org, rid, a)
    res = reconcile(engine, clock, org)

    with engine.connect() as c:
        credited = c.execute(
            text(
                "SELECT d.reference, d.deposit_address, count(cr.id) AS n FROM deposit_intents d LEFT JOIN credits cr "
                "ON cr.org_id=d.org_id AND cr.deposit_intent_id=d.id WHERE d.org_id=:o GROUP BY d.id"
            ),
            {"o": org},
        ).all()
        brk = c.execute(text("SELECT kind, subject FROM recon_breaks WHERE org_id=:o"), {"o": org}).all()
        settled = c.execute(
            text("SELECT count(*) FROM payment_intents WHERE org_id=:o AND status='CONFIRMED'"), {"o": org}
        ).scalar_one()
    assert (
        sorted(int(r.n) for r in credited) == [0] + [1] * 7
    )  # dep-07's intent waits; every other deposit credited once
    assert [(b.kind, int(b.subject["amount_minor"])) for b in brk] == [("unallocated_inbound", 200 * 10**6)]
    assert res.counted == settled + 8 and res.matched == res.counted - 1
