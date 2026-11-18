"""The worker picks up a READY payment and sends it; at startup it reconciles every wallet's nonce."""

from __future__ import annotations

import pytest
from chain_helpers import balance, needs_chain, setup_chain_org
from conftest import make_settings
from detent import devchain
from detent.clock import FrozenClock
from detent.runtime import Runtime
from detent.worker.loop import Worker
from sqlalchemy import Engine, text

pytestmark = [pytest.mark.db, *needs_chain]


def test_worker_sends_a_ready_payment(engine: Engine, clock: FrozenClock, chain: devchain.LocalChain) -> None:
    co = setup_chain_org(engine, clock, chain)
    key = co.adapter._signer._account.key.hex()  # type: ignore[attr-defined]  # the test wallet's key, generated at runtime
    from pydantic import SecretStr

    settings = make_settings(
        co.id, local_evm_rpc_url=chain.rpc_url, test_wallet_private_key_local=SecretStr(key)
    )
    pid = co.payout(engine, clock, "12.34")
    with engine.connect() as c:
        job = c.execute(
            text("SELECT kind, dedupe_key FROM jobs WHERE org_id=:o AND payment_id=:p"),
            {"o": co.id, "p": pid},
        ).one()
    assert job.kind == "payment.send" and job.dedupe_key == pid
    before = balance(chain, co.payee)
    worker = Worker(Runtime(settings=settings, engine=engine, clock=clock), worker_id="w-test")
    while worker.run_one():
        pass
    with engine.connect() as c:
        st = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": co.id, "p": pid}
        ).scalar()
    assert st == "CONFIRMED" and balance(chain, co.payee) - before == 12_340_000


def test_worker_startup_reconciles_nonces(
    engine: Engine, clock: FrozenClock, chain: devchain.LocalChain
) -> None:
    co = setup_chain_org(engine, clock, chain)
    key = co.adapter._signer._account.key.hex()  # type: ignore[attr-defined]
    from pydantic import SecretStr

    settings = make_settings(
        co.id, local_evm_rpc_url=chain.rpc_url, test_wallet_private_key_local=SecretStr(key)
    )
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO wallet_nonces (org_id, rail_id, address, next_nonce) VALUES (:o, 'local-evm', :a, 7)"
            ),
            {"o": co.id, "a": co.sender.lower()},
        )
    Worker(Runtime(settings=settings, engine=engine, clock=clock), worker_id="w-test").startup()
    with engine.connect() as c:
        why = c.execute(
            text("SELECT refused_reason FROM wallet_nonces WHERE org_id=:o"), {"o": co.id}
        ).scalar()
    assert why and why.startswith("NONCE_MISMATCH")
