"""S4: a timeout is UNKNOWN, never FAILED, and only rail evidence resolves it (EXE-05, EXE-06, RAL-05).

Every test sends through the fault-injection proxy in front of anvil.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import timedelta

import pytest
from chain_helpers import ChainOrg, balance, needs_chain, setup_chain_org, w3
from detent import devchain
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.execution.attempts import AttemptNotAllowed, create_attempt
from detent.execution.resolver import resolution_times, resolve_unknown
from detent.execution.send import send_payment
from detent.policy.screening import MockScreening
from detent.rails.evm import EvmAdapter
from faultproxy.app import create_app as proxy_app
from servers import clear_faults, fault, fault_log, serve
from sqlalchemy import Engine, text

pytestmark = [pytest.mark.db, *needs_chain]


@pytest.fixture
def proxied(engine: Engine, clock: FrozenClock, chain: devchain.LocalChain) -> Iterator[tuple[ChainOrg, str]]:
    co = setup_chain_org(engine, clock, chain)
    with serve(proxy_app(chain.rpc_url, hold_seconds=2.0)) as url:
        # The same wallet, reached through the proxy, with a short client timeout.
        adapter = EvmAdapter(
            rail_id="local-evm",
            rpc_url=url,
            expected_chain_id=31337,
            token_address=chain.usdc_address,
            signer=co.adapter._signer,
            confirmations=1,
            timeout_seconds=1.0,
        )  # type: ignore[attr-defined]
        co = dataclasses.replace(co, adapter=adapter, adapters={"local-evm": adapter})
        yield co, url


def send(engine: Engine, clock: FrozenClock, co: ChainOrg, pid: str) -> str:
    return send_payment(
        engine, clock, co.adapters, org_id=co.id, payment_id=pid, screening=MockScreening.from_fixture()
    ).value


def resolve(engine: Engine, clock: FrozenClock, co: ChainOrg, pid: str) -> str:
    return resolve_unknown(engine, clock, co.adapters, org_id=co.id, payment_id=pid).value


def state(engine: Engine, org: str, pid: str) -> tuple[str, list[tuple[str, str | None]]]:
    with engine.connect() as c:
        st = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org, "p": pid}
        ).scalar()
        atts = c.execute(
            text(
                "SELECT status, failure_class FROM attempts WHERE org_id=:o AND payment_id=:p ORDER BY attempt_no"
            ),
            {"o": org, "p": pid},
        ).all()
    return str(st), [tuple(a) for a in atts]  # type: ignore[misc]


@pytest.mark.parametrize("kind", ["timeout_after_forward", "reset_after_forward"])
def test_no_answer_after_forwarding_is_unknown_then_confirmed(
    engine: Engine, clock: FrozenClock, proxied: tuple[ChainOrg, str], kind: str
) -> None:
    co, proxy = proxied
    pid = co.payout(engine, clock, "31.00")
    fault(proxy, "eth_sendRawTransaction", kind)
    before = balance(co.chain, co.payee)
    assert send(engine, clock, co, pid) == "UNKNOWN"
    assert state(engine, co.id, pid) == ("UNKNOWN", [("UNKNOWN", None)])
    # While UNKNOWN nothing can create a second attempt.
    with pytest.raises(AttemptNotAllowed), engine.begin() as c:
        create_attempt(c, clock, org_id=co.id, payment_id=pid, rail_id="local-evm")
    assert send(engine, clock, co, pid) == "UNKNOWN"  # a second send trigger does nothing
    assert resolve(engine, clock, co, pid) == "CONFIRMED"
    assert balance(co.chain, co.payee) - before == 31_000_000
    [entry] = fault_log(proxy)
    assert entry["fault"] == kind and entry["attempt"].startswith("att_")


def test_never_forwarded_is_rebroadcast_as_the_same_transaction(
    engine: Engine, clock: FrozenClock, proxied: tuple[ChainOrg, str]
) -> None:
    co, proxy = proxied
    pid = co.payout(engine, clock, "32.00")
    fault(proxy, "eth_sendRawTransaction", "timeout_before_forward")
    before = balance(co.chain, co.payee)
    assert send(engine, clock, co, pid) == "UNKNOWN"
    assert balance(co.chain, co.payee) == before  # it never left
    with engine.connect() as c:
        h = c.execute(
            text("SELECT tx_hash FROM attempts WHERE org_id=:o AND payment_id=:p"), {"o": co.id, "p": pid}
        ).scalar()
    assert resolve(engine, clock, co, pid) == "CONFIRMED"
    assert balance(co.chain, co.payee) - before == 32_000_000
    assert (
        w3(co.chain).eth.get_transaction_receipt(h)["status"] == 1
    )  # the stored hash is the one that landed
    with engine.connect() as c:
        kinds = (
            c.execute(
                text("SELECT kind FROM audit_events WHERE org_id=:o AND subject_id=:p"),
                {"o": co.id, "p": pid},
            )
            .scalars()
            .all()
        )
    assert "attempt.rebroadcast" in kinds


def test_delayed_receipt_stays_unknown_without_resending(
    engine: Engine, clock: FrozenClock, proxied: tuple[ChainOrg, str]
) -> None:
    co, proxy = proxied
    pid = co.payout(engine, clock, "33.00")
    fault(proxy, "eth_sendRawTransaction", "timeout_after_forward")
    fault(proxy, "eth_getTransactionReceipt", "hide_receipt", count=3)
    nonce_before = w3(co.chain).eth.get_transaction_count(co.sender)
    send(engine, clock, co, pid)
    for _ in range(3):
        assert resolve(engine, clock, co, pid) == "UNKNOWN"
    assert resolve(engine, clock, co, pid) == "CONFIRMED"
    assert w3(co.chain).eth.get_transaction_count(co.sender) == nonce_before + 1


def test_stuck_opens_a_case_and_cancel_by_replacement_resolves_it(
    engine: Engine, clock: FrozenClock, proxied: tuple[ChainOrg, str]
) -> None:
    from detent.execution.resolver import approve_cancel_by_replacement

    co, proxy = proxied
    pid = co.payout(engine, clock, "34.00")
    fault(proxy, "eth_sendRawTransaction", "timeout_before_forward", count=-1)  # nothing gets through
    before = balance(co.chain, co.payee)
    assert send(engine, clock, co, pid) == "UNKNOWN"
    assert resolve(engine, clock, co, pid) == "UNKNOWN"  # re-broadcast attempted, still no answer
    clock.advance(timedelta(minutes=16))  # past execution.unknown_stuck_after (PT15M)
    assert resolve(engine, clock, co, pid) == "UNKNOWN"
    with engine.connect() as c:
        case = c.execute(
            text("SELECT id, type, owner_id, tier FROM exception_cases WHERE org_id=:o AND payment_id=:p"),
            {"o": co.id, "p": pid},
        ).one()
    assert (
        case.type == "unknown_stuck"
        and case.owner_id == co.d.org.users[Role.PAYMENTS_LEAD]
        and case.tier == 1
    )
    clear_faults(proxy)
    lead = Actor(co.d.org.users[Role.PAYMENTS_LEAD], "payments_lead")
    with pytest.raises(PermissionError):
        approve_cancel_by_replacement(
            engine,
            clock,
            co.adapters,
            org_id=co.id,
            case_id=case.id,
            actor=Actor(co.d.org.users[Role.REVIEWER], "reviewer"),
            reason="x",
        )
    approve_cancel_by_replacement(
        engine,
        clock,
        co.adapters,
        org_id=co.id,
        case_id=case.id,
        actor=lead,
        reason="Rail incident; cancel and decide again",
    )
    # The chain decides: the zero-value replacement consumed the nonce, so the payment failed definitively.
    assert resolve(engine, clock, co, pid) in ("FAILED", "FAILED_FINAL")
    assert balance(co.chain, co.payee) == before
    _st, atts = state(engine, co.id, pid)
    assert atts[0] == ("FAILED", "TECHNICAL_FINAL")


def test_unknown_never_fails_without_evidence(
    engine: Engine, clock: FrozenClock, proxied: tuple[ChainOrg, str]
) -> None:
    co, proxy = proxied
    pid = co.payout(engine, clock, "35.00")
    fault(proxy, "eth_sendRawTransaction", "timeout_after_forward")
    send(engine, clock, co, pid)
    with pytest.raises(Exception, match="without evidence"), engine.begin() as c:
        c.execute(
            text(
                "UPDATE attempts SET status='FAILED', failure_class='TECHNICAL_FINAL' WHERE org_id=:o AND payment_id=:p"
            ),
            {"o": co.id, "p": pid},
        )


def test_time_to_resolve_is_recorded(
    engine: Engine, clock: FrozenClock, proxied: tuple[ChainOrg, str]
) -> None:
    co, proxy = proxied
    for i, secs in enumerate((10, 20, 30)):
        pid = co.payout(engine, clock, f"{40 + i}.00", key=f"r{i}")
        fault(proxy, "eth_sendRawTransaction", "timeout_after_forward")
        send(engine, clock, co, pid)
        clock.advance(timedelta(seconds=secs))
        assert resolve(engine, clock, co, pid) == "CONFIRMED"
    stats = resolution_times(engine, co.id)
    assert stats == {"count": 3, "median_seconds": 20, "p95_seconds": 30}


def test_a_timeout_schedules_the_resolver(
    engine: Engine, clock: FrozenClock, proxied: tuple[ChainOrg, str]
) -> None:
    co, proxy = proxied
    pid = co.payout(engine, clock, "36.00")
    fault(proxy, "eth_sendRawTransaction", "timeout_after_forward")
    send(engine, clock, co, pid)
    with engine.connect() as c:
        job = c.execute(
            text(
                "SELECT kind, run_at, payload FROM jobs WHERE org_id=:o AND payment_id=:p AND kind='payment.resolve_unknown'"
            ),
            {"o": co.id, "p": pid},
        ).one()
    assert job.run_at == clock.now() + timedelta(seconds=5) and job.payload["step"] == 0
