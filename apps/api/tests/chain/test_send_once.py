"""S2 exit check on anvil: EXE-02, EXE-03, EXE-04, RAL-02.

An EXECUTE payout sends one MockUSDC transfer and reaches CONFIRMED under its pay_ ID; a BLOCKED one
sends nothing; the kill switch or an insufficient balance holds the payment before sending; parallel
send triggers produce one transaction.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from chain_helpers import ChainOrg, balance, needs_chain, setup_chain_org, w3
from detent import devchain
from detent.clock import FrozenClock
from detent.domain.money import Currency, Money
from detent.execution import nonces
from detent.execution.send import apply_rail_status, send_payment
from detent.policy.screening import MockScreening
from detent.rails.base import AttemptView
from sqlalchemy import Engine, text

pytestmark = [pytest.mark.db, *needs_chain]


def status(engine: Engine, org: str, pid: str) -> str:
    with engine.connect() as c:
        return str(
            c.execute(
                text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org, "p": pid}
            ).scalar()
        )


def attempts(engine: Engine, org: str, pid: str) -> list[object]:
    with engine.connect() as c:
        return list(
            c.execute(
                text("SELECT * FROM attempts WHERE org_id=:o AND payment_id=:p ORDER BY attempt_no"),
                {"o": org, "p": pid},
            ).all()
        )


def send(engine: Engine, clock: FrozenClock, co: ChainOrg, pid: str) -> str:
    st = send_payment(
        engine, clock, co.adapters, org_id=co.id, payment_id=pid, screening=MockScreening.from_fixture()
    )
    # A receipt can lag the broadcast on a busy machine; the confirmation poller asks again. So do we.
    for _ in range(50):
        if st.value != "SUBMITTED":
            break
        time.sleep(0.1)
        a = attempts(engine, co.id, pid)[-1]
        view = AttemptView(
            a.id,
            pid,
            a.attempt_no,
            a.rail_id,
            a.idempotency_key,  # type: ignore[attr-defined]
            _amount(engine, co.id, pid),
            co.payee,
            a.nonce,
            a.raw_tx,
            a.tx_hash,  # type: ignore[attr-defined]
        )
        st = apply_rail_status(engine, clock, co.adapter, co.id, view)
    return st.value


def _amount(engine: Engine, org: str, pid: str) -> Money:
    with engine.connect() as c:
        minor = c.execute(
            text("SELECT amount_minor FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org, "p": pid}
        ).scalar()
    return Money(int(minor), Currency.USDC)


@pytest.fixture
def co(engine: Engine, clock: FrozenClock, chain: devchain.LocalChain) -> ChainOrg:
    return setup_chain_org(engine, clock, chain)


def test_execute_payout_sends_one_transfer_and_confirms(
    engine: Engine, clock: FrozenClock, co: ChainOrg
) -> None:
    pid = co.payout(engine, clock, "150.25")
    assert status(engine, co.id, pid) == "READY"
    before = balance(co.chain, co.payee)
    assert send(engine, clock, co, pid) == "CONFIRMED"
    assert balance(co.chain, co.payee) - before == 150_250_000
    [a] = attempts(engine, co.id, pid)
    assert a.status == "CONFIRMED" and a.attempt_no == 1 and a.rail_id == "local-evm"  # type: ignore[attr-defined]
    rcpt = w3(co.chain).eth.get_transaction_receipt(a.tx_hash)  # type: ignore[attr-defined]
    assert rcpt["status"] == 1 and rcpt["from"].lower() == co.sender.lower()
    with engine.connect() as c:
        kinds = [
            r.kind
            for r in c.execute(
                text("SELECT kind FROM audit_events WHERE org_id=:o AND subject_id=:p ORDER BY seq"),
                {"o": co.id, "p": pid},
            )
        ]
    assert (
        kinds[-3:] == ["attempt.created", "payment.status_changed", "attempt.confirmed"]
        or "attempt.confirmed" in kinds
    )


def test_sending_again_after_confirmation_does_nothing(
    engine: Engine, clock: FrozenClock, co: ChainOrg
) -> None:
    pid = co.payout(engine, clock, "10.00")
    send(engine, clock, co, pid)
    before = balance(co.chain, co.payee)
    assert send(engine, clock, co, pid) == "CONFIRMED"
    assert balance(co.chain, co.payee) == before and len(attempts(engine, co.id, pid)) == 1


def test_blocked_payment_sends_nothing(engine: Engine, clock: FrozenClock, co: ChainOrg) -> None:
    pid = co.payout(engine, clock, "200000.00")  # above the hard maximum -> BLOCKED
    assert status(engine, co.id, pid) == "BLOCKED"
    before = balance(co.chain, co.payee)
    assert send(engine, clock, co, pid) == "BLOCKED"
    assert balance(co.chain, co.payee) == before and attempts(engine, co.id, pid) == []


def test_kill_switch_holds_before_sending(engine: Engine, clock: FrozenClock, co: ChainOrg) -> None:
    pid = co.payout(engine, clock, "10.00")
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE kill_switch SET engaged=true, engaged_by='usr_oncall', engaged_at=:t WHERE org_id=:o"
            ),
            {"o": co.id, "t": clock.now()},
        )
    assert send(engine, clock, co, pid) == "HELD"
    assert attempts(engine, co.id, pid) == []
    with engine.connect() as c:
        reason = c.execute(
            text(
                "SELECT payload->>'reason' FROM audit_events WHERE org_id=:o AND subject_id=:p "
                "AND kind='payment.status_changed' ORDER BY seq DESC LIMIT 1"
            ),
            {"o": co.id, "p": pid},
        ).scalar()
    assert reason == "KILL_SWITCH_ENGAGED"


def test_insufficient_balance_holds_before_sending(
    engine: Engine, clock: FrozenClock, chain: devchain.LocalChain
) -> None:
    poor = setup_chain_org(engine, clock, chain, usdc_minor=5_000_000)  # 5 USDC
    pid = poor.payout(engine, clock, "10.00")
    assert send(engine, clock, poor, pid) == "HELD"
    assert attempts(engine, poor.id, pid) == []


def test_prefunded_daily_limit_holds(engine: Engine, clock: FrozenClock, chain: devchain.LocalChain) -> None:
    small = setup_chain_org(engine, clock, chain, prefunded_daily_limit="15.00")
    first, second = small.payout(engine, clock, "10.00"), small.payout(engine, clock, "10.00", key="second")
    assert send(engine, clock, small, first) == "CONFIRMED"
    assert send(engine, clock, small, second) == "HELD"


def test_stale_decision_reruns_policy_first(engine: Engine, clock: FrozenClock, co: ChainOrg) -> None:
    pid = co.payout(engine, clock, "10.00")
    # The payee's details change after the decision; the decision is then older than 300 s.
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE destinations SET last_changed_at=:t, last_changed_by='usr_x' WHERE org_id=:o AND id='dst_local'"
            ),
            {"o": co.id, "t": clock.now()},
        )
    clock.advance(timedelta(seconds=301))
    assert send(engine, clock, co, pid) == "HELD"
    assert attempts(engine, co.id, pid) == []
    with engine.connect() as c:
        decisions = (
            c.execute(
                text("SELECT outcome FROM decisions WHERE org_id=:o AND payment_id=:p ORDER BY decided_at"),
                {"o": co.id, "p": pid},
            )
            .scalars()
            .all()
        )
    assert decisions == ["EXECUTE", "ESCALATE"]


def test_fresh_decision_is_not_rerun(engine: Engine, clock: FrozenClock, co: ChainOrg) -> None:
    pid = co.payout(engine, clock, "10.00")
    assert send(engine, clock, co, pid) == "CONFIRMED"
    with engine.connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM decisions WHERE org_id=:o AND payment_id=:p"), {"o": co.id, "p": pid}
        ).scalar()
    assert n == 1


def test_parallel_send_triggers_produce_one_transaction(
    engine: Engine, clock: FrozenClock, co: ChainOrg
) -> None:
    pid = co.payout(engine, clock, "42.00")
    start_nonce = w3(co.chain).eth.get_transaction_count(co.sender)
    before = balance(co.chain, co.payee)
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda _: send(engine, clock, co, pid), range(8)))
    assert "CONFIRMED" in results or status(engine, co.id, pid) == "CONFIRMED"
    assert w3(co.chain).eth.get_transaction_count(co.sender) == start_nonce + 1
    assert balance(co.chain, co.payee) - before == 42_000_000
    assert len(attempts(engine, co.id, pid)) == 1


def test_concurrent_sends_from_one_wallet_get_consecutive_nonces(
    engine: Engine, clock: FrozenClock, co: ChainOrg
) -> None:
    pids = [co.payout(engine, clock, f"{i + 1}.00", key=f"n{i}") for i in range(5)]
    start = w3(co.chain).eth.get_transaction_count(co.sender)
    with ThreadPoolExecutor(5) as ex:
        assert set(ex.map(lambda p: send(engine, clock, co, p), pids)) == {"CONFIRMED"}
    used = sorted(int(attempts(engine, co.id, p)[0].nonce) for p in pids)  # type: ignore[attr-defined]
    assert used == list(range(start, start + 5))


def test_nonce_and_signed_tx_are_stored_before_broadcast(
    engine: Engine, clock: FrozenClock, co: ChainOrg, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = co.payout(engine, clock, "10.00")
    seen: dict[str, object] = {}

    def spy(view: object) -> object:
        a = attempts(engine, co.id, pid)[0]
        seen.update(nonce=a.nonce, raw=a.raw_tx, h=a.tx_hash)  # type: ignore[attr-defined]
        return original(view)

    original = co.adapter.submit
    monkeypatch.setattr(co.adapter, "submit", spy)
    send(engine, clock, co, pid)
    assert seen["nonce"] is not None and seen["raw"] and seen["h"]


def test_nonce_disagreement_refuses_to_send(engine: Engine, clock: FrozenClock, co: ChainOrg) -> None:
    pid = co.payout(engine, clock, "10.00")
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO wallet_nonces (org_id, rail_id, address, next_nonce) VALUES (:o, 'local-evm', :a, 99) "
                "ON CONFLICT (org_id, rail_id, address) DO UPDATE SET next_nonce = 99"
            ),
            {"o": co.id, "a": co.sender.lower()},
        )
    problems = nonces.reconcile(engine, clock, co.id, co.adapters)
    assert problems and problems[0].rail_id == "local-evm"
    assert send(engine, clock, co, pid) == "HELD"
    assert attempts(engine, co.id, pid) == []


def test_new_rule_version_reruns_policy_before_sending(
    engine: Engine, clock: FrozenClock, co: ChainOrg
) -> None:
    from decision_helpers import POLICY_TEXT
    from detent.policy.schema import load_ruleset
    from detent.policy.store import install_ruleset

    pid = co.payout(engine, clock, "10.00")
    tighter = POLICY_TEXT.replace("version: 1\n", "version: 2\n").replace(
        'auto_limit: {USDC: "10000.00",', 'auto_limit: {USDC: "5.00",'
    )
    with engine.begin() as c:
        install_ruleset(c, clock, co.id, load_ruleset(tighter), proposed_by="system:test")
    clock.advance(timedelta(seconds=1))  # the frozen clock would give both decisions the same timestamp
    assert send(engine, clock, co, pid) == "HELD"  # the re-run escalates ABOVE_AUTO_LIMIT under version 2
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT d.outcome, v.version FROM decisions d JOIN policy_versions v ON v.org_id = d.org_id "
                "AND v.id = d.policy_version_id WHERE d.org_id=:o AND d.payment_id=:p ORDER BY d.decided_at, d.id"
            ),
            {"o": co.id, "p": pid},
        ).all()
    assert [(r.outcome, r.version) for r in rows] == [("EXECUTE", 1), ("ESCALATE", 2)]


def test_a_send_never_logs_the_wallet_private_key(
    engine: Engine, clock: FrozenClock, co: ChainOrg, caplog: pytest.LogCaptureFixture
) -> None:
    """FND-08: a full send, with every logger at DEBUG, never writes the sending wallet's private key."""
    import logging

    from detent.logging import JsonFormatter

    caplog.set_level(logging.DEBUG)
    pid = co.payout(engine, clock, "12.00")
    assert send(engine, clock, co, pid) == "CONFIRMED"
    key = co.adapter._signer._account.key.hex().removeprefix("0x").lower()  # type: ignore[attr-defined]
    fmt = JsonFormatter()
    lines = [fmt.format(r).lower() for r in caplog.records]
    assert lines and all(key not in line for line in lines)
