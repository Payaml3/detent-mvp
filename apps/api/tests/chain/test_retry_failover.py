"""S4: deterministic retries, routing and failover under one payment ID (EXE-07, RAL-06, RAL-07)."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import timedelta

import pytest
from chain_helpers import ChainOrg, balance, needs_chain, new_wallet, setup_chain_org, w3
from detent import devchain
from detent.clock import FrozenClock
from detent.domain.money import Money
from detent.execution.send import send_payment
from detent.policy.screening import MockScreening
from detent.rails.evm import EvmAdapter
from detent.rails.registry import install_rail
from detent.rails.signer import LocalKeySigner
from faultproxy.app import create_app as proxy_app
from servers import fault, serve
from sqlalchemy import Engine, text

pytestmark = [pytest.mark.db, *needs_chain]


@pytest.fixture
def two_rails(
    engine: Engine, clock: FrozenClock, chain: devchain.LocalChain, chain_b: devchain.LocalChain
) -> Iterator[tuple[ChainOrg, str]]:
    co = setup_chain_org(engine, clock, chain)
    b_sender, b_key = new_wallet(chain_b, usdc_minor=1_000_000 * 10**6)
    with engine.begin() as c:
        install_rail(
            c,
            co.id,
            rail_id="local-evm-b",
            kind="evm",
            network="local-evm-b",
            chain_id=31337,
            currency="USDC",
            token_address=chain_b.usdc_address,
            from_address=b_sender,
            confirmations=1,
            prefunded_daily_limit=Money.parse("40000.00", "USDC"),
        )
        c.execute(
            text(
                "UPDATE rails SET est_fee_minor = CASE id WHEN 'local-evm' THEN 0 ELSE 1000 END WHERE org_id=:o"
            ),
            {"o": co.id},
        )
        c.execute(
            text(
                "INSERT INTO destinations (id, org_id, counterparty_id, kind, network, address, verified, first_seen_at, "
                "last_changed_at) VALUES ('dst_local_b', :o, 'cpt_local', 'evm_wallet', 'local-evm-b', :a, true, :f, :f)"
            ),
            {"o": co.id, "a": co.payee, "f": clock.now() - timedelta(days=100)},
        )
    with serve(proxy_app(chain.rpc_url, hold_seconds=2.0)) as url:
        a = EvmAdapter(
            rail_id="local-evm",
            rpc_url=url,
            expected_chain_id=31337,
            token_address=chain.usdc_address,
            signer=co.adapter._signer,
            confirmations=1,
            timeout_seconds=1.0,
        )  # type: ignore[attr-defined]
        b = EvmAdapter(
            rail_id="local-evm-b",
            rpc_url=chain_b.rpc_url,
            expected_chain_id=31337,
            token_address=chain_b.usdc_address,
            signer=LocalKeySigner(b_key),
            confirmations=1,
        )
        yield dataclasses.replace(co, adapter=a, adapters={"local-evm": a, "local-evm-b": b}), url


def send(engine: Engine, clock: FrozenClock, co: ChainOrg, pid: str) -> str:
    return send_payment(
        engine, clock, co.adapters, org_id=co.id, payment_id=pid, screening=MockScreening.from_fixture()
    ).value


def attempts(engine: Engine, org: str, pid: str) -> list[object]:
    with engine.connect() as c:
        return list(
            c.execute(
                text("SELECT * FROM attempts WHERE org_id=:o AND payment_id=:p ORDER BY attempt_no"),
                {"o": org, "p": pid},
            ).all()
        )


def allow_switch(engine: Engine, org: str, pid: str) -> None:
    # The flag is part of the intent (set by the platform at creation); tests set it on the row directly.
    with engine.begin() as c:
        c.execute(
            text("UPDATE payment_intents SET allow_network_switch=true WHERE org_id=:o AND id=:p"),
            {"o": org, "p": pid},
        )


def test_retryable_failure_retries_with_the_same_nonce(
    engine: Engine, clock: FrozenClock, two_rails: tuple[ChainOrg, str]
) -> None:
    co, proxy = two_rails
    pid = co.payout(engine, clock, "21.00")
    fault(proxy, "eth_sendRawTransaction", "http_503_before_accept")
    start = w3(co.chain).eth.get_transaction_count(co.sender)
    assert send(engine, clock, co, pid) == "READY"  # FAILED, then the retry rule put it back
    with engine.connect() as c:
        rule = c.execute(
            text(
                "SELECT payload FROM audit_events WHERE org_id=:o AND subject_id=:p AND kind='payment.retry_scheduled'"
            ),
            {"o": co.id, "p": pid},
        ).scalar()
        job = c.execute(
            text("SELECT run_at FROM jobs WHERE org_id=:o AND dedupe_key=:k"), {"o": co.id, "k": f"{pid}:2"}
        ).scalar()
    assert rule == {
        "rule": "retry",
        "failure_class": "TECHNICAL_RETRYABLE",
        "attempt": 1,
        "max_attempts": 3,
        "backoff_seconds": 5,
        "rail": "local-evm",
    }
    assert job == clock.now() + timedelta(seconds=5)
    before = balance(co.chain, co.payee)
    assert send(engine, clock, co, pid) == "CONFIRMED"
    a1, a2 = attempts(engine, co.id, pid)
    assert (a1.status, a1.failure_class, a2.status) == ("FAILED", "TECHNICAL_RETRYABLE", "CONFIRMED")  # type: ignore[attr-defined]
    assert a1.nonce == a2.nonce and a1.payment_id == a2.payment_id == pid  # type: ignore[attr-defined]
    assert w3(co.chain).eth.get_transaction_count(co.sender) == start + 1  # no gap, no second transfer
    assert balance(co.chain, co.payee) - before == 21_000_000


def test_retries_are_bounded_and_end_final(
    engine: Engine, clock: FrozenClock, two_rails: tuple[ChainOrg, str]
) -> None:
    co, proxy = two_rails
    pid = co.payout(engine, clock, "22.00")
    fault(proxy, "eth_sendRawTransaction", "http_503_before_accept", count=-1)
    results = [send(engine, clock, co, pid) for _ in range(3)]
    assert results == ["READY", "READY", "FAILED_FINAL"]  # max_attempts 3, no network switch allowed
    assert len(attempts(engine, co.id, pid)) == 3
    with engine.connect() as c:
        used = c.execute(
            text("SELECT amount_minor FROM counters WHERE org_id=:o AND scope='counterparty:cpt_local:USDC'"),
            {"o": co.id},
        ).scalar()
    assert used == 0  # FAILED_FINAL released the cap


def test_reverted_transaction_fails_over_under_the_same_payment_id(
    engine: Engine, clock: FrozenClock, two_rails: tuple[ChainOrg, str]
) -> None:
    co, proxy = two_rails
    pid = co.payout(engine, clock, "23.00")
    allow_switch(engine, co.id, pid)
    fault(proxy, "eth_estimateGas", "low_gas_estimate", count=2)  # the transfer runs out of gas on chain
    b_before = balance(co.chain, co.payee)
    assert (
        send(engine, clock, co, pid) == "READY"
    )  # receipt status 0 -> TECHNICAL_FINAL -> failover scheduled
    a1 = attempts(engine, co.id, pid)[0]
    assert (a1.rail_id, a1.status, a1.failure_class) == ("local-evm", "FAILED", "TECHNICAL_FINAL")  # type: ignore[attr-defined]
    assert w3(co.chain).eth.get_transaction_receipt(a1.tx_hash)["status"] == 0  # type: ignore[attr-defined]
    assert balance(co.chain, co.payee) == b_before  # the revert moved nothing
    assert send(engine, clock, co, pid) == "CONFIRMED"
    a1, a2 = attempts(engine, co.id, pid)
    assert (a2.rail_id, a2.status, a2.attempt_no, a2.idempotency_key) == (
        "local-evm-b",
        "CONFIRMED",
        2,
        f"{pid}:local-evm-b",
    )  # type: ignore[attr-defined]
    with engine.connect() as c:
        ev = c.execute(
            text(
                "SELECT payload FROM audit_events WHERE org_id=:o AND subject_id=:p AND kind='payment.failover_scheduled'"
            ),
            {"o": co.id, "p": pid},
        ).scalar()
    assert ev["from"] == "local-evm" and ev["to"] == "local-evm-b"


def test_no_failover_without_permission(
    engine: Engine, clock: FrozenClock, two_rails: tuple[ChainOrg, str]
) -> None:
    co, proxy = two_rails
    pid = co.payout(engine, clock, "24.00")
    fault(proxy, "eth_estimateGas", "low_gas_estimate", count=2)
    assert send(engine, clock, co, pid) == "FAILED_FINAL"
    assert len(attempts(engine, co.id, pid)) == 1


def test_route_is_stored_with_every_candidate(
    engine: Engine, clock: FrozenClock, two_rails: tuple[ChainOrg, str]
) -> None:
    co, _ = two_rails
    pid = co.payout(engine, clock, "25.00")
    allow_switch(engine, co.id, pid)
    assert send(engine, clock, co, pid) == "CONFIRMED"
    with engine.connect() as c:
        r = c.execute(
            text(
                "SELECT route FROM decisions WHERE org_id=:o AND payment_id=:p ORDER BY decided_at DESC LIMIT 1"
            ),
            {"o": co.id, "p": pid},
        ).scalar()
    cands = {x["rail"]: x for x in r["candidates"]}
    assert r["chosen"] == "local-evm" and r["reason"].startswith("lowest score")
    assert cands["local-evm"]["eligible"] and cands["local-evm-b"]["eligible"]
    assert float(cands["local-evm"]["score"]) < float(cands["local-evm-b"]["score"])
    assert not cands["base-sepolia"]["eligible"] if "base-sepolia" in cands else True


def test_a_block_never_reaches_routing(
    engine: Engine, clock: FrozenClock, two_rails: tuple[ChainOrg, str]
) -> None:
    co, _ = two_rails
    pid = co.payout(engine, clock, "200000.00")  # above the hard maximum
    assert send(engine, clock, co, pid) == "BLOCKED"
    with engine.connect() as c:
        r = c.execute(
            text("SELECT route FROM decisions WHERE org_id=:o AND payment_id=:p"), {"o": co.id, "p": pid}
        ).scalar()
    assert r is None and attempts(engine, co.id, pid) == []
