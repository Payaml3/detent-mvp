"""CON-09 and DEM-03: the demo scenario runner, end to end on a local rehearsal of the demo's three rails.

Two local anvil chains (chain 31337, with MockUSDC; `devchain.deploy` is local-only) stand in for Base Sepolia
and Ethereum Sepolia: after seeding, this test points the organisation's two EVM rails at chain 31337. The bank
simulator is the bank rail and the fault proxy sits in front of "Base Sepolia". The demo organisation is seeded
from the fixtures and the real worker sends. Test networks only (invariant 14).
"""

from __future__ import annotations

import secrets
import socket
import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from chain_helpers import needs_chain, new_wallet, usdc, w3
from conftest import CREATED_ORGS, FAKE_TEST, login, make_settings
from decision_helpers import PEPPER
from detent import devchain
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.demo.generations import demo_user_id
from detent.demo.scenarios import batch, run_scenario
from detent.exceptions.cases import approve
from detent.runtime import Runtime, build_runtime
from detent.seed import seed_demo
from detent.worker.loop import Worker
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

pytestmark = [pytest.mark.db, *needs_chain]

MANDATE_KEY = SecretStr("test-mandate-key-0123456789abcdef")


def _anvil() -> Iterator[devchain.LocalChain]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    proc = devchain.start_anvil(port)
    try:
        yield devchain.deploy(f"http://127.0.0.1:{port}")
    finally:
        proc.terminate()


@pytest.fixture(scope="module")
def base_chain() -> Iterator[devchain.LocalChain]:
    yield from _anvil()


@pytest.fixture(scope="module")
def eth_chain() -> Iterator[devchain.LocalChain]:
    yield from _anvil()


@pytest.fixture
def proxy(base_chain: devchain.LocalChain) -> Iterator[str]:
    from faultproxy.app import create_app as proxy_app
    from servers import serve

    with serve(proxy_app(base_chain.rpc_url, hold_seconds=3.0, demo_mode=True)) as url:
        yield url


@pytest.fixture
def demo(engine: Any, clock: FrozenClock, base_chain: Any, eth_chain: Any, bank: str, proxy: str) -> Runtime:
    org = f"org_t{secrets.token_hex(6)}"
    CREATED_ORGS.append(org)
    big = 10**12
    _, sender_base = new_wallet(base_chain, usdc_minor=big)
    _, sender_eth = new_wallet(eth_chain, usdc_minor=big)
    _, payer_base = new_wallet(base_chain, usdc_minor=big)
    _, payer_eth = new_wallet(eth_chain, usdc_minor=big)
    s = make_settings(
        org,
        api_key_pepper=SecretStr(PEPPER),
        mandate_signing_key_demo=MANDATE_KEY,
        agent_api_key=SecretStr(FAKE_TEST + "agent" + secrets.token_hex(16)),
        agent_llm="recorded",
        base_sepolia_rpc_url=proxy,
        eth_sepolia_rpc_url=eth_chain.rpc_url,
        usdc_address_base_sepolia=base_chain.usdc_address,
        usdc_address_eth_sepolia=eth_chain.usdc_address,
        test_wallet_private_key_base=sender_base,
        test_wallet_private_key_eth=sender_eth,
        demo_payer_private_key_base=payer_base,
        demo_payer_private_key_eth=payer_eth,
        banksim_url=bank,
        faultproxy_url=proxy,
        rail_timeout_seconds=1.0,
    )
    rt = build_runtime(s, engine=engine, clock=clock)
    seed_demo(rt, org_id=org)
    with engine.begin() as c:  # the local stand-ins are chain 31337 (see the module docstring)
        c.execute(
            text("UPDATE rails SET chain_id=31337 WHERE org_id=:o AND id IN ('base-sepolia','eth-sepolia')"),
            {"o": org},
        )
    return rt


def _drain(rt: Runtime, chains: list[devchain.LocalChain], rounds: int = 120) -> None:
    """Run the organisation's worker until nothing is due or in flight, mining blocks and moving the clock."""
    worker = Worker(rt, org_id=rt.settings.demo_org_id)
    org = rt.settings.demo_org_id
    assert isinstance(rt.clock, FrozenClock)
    for _ in range(rounds):
        while worker.run_one():
            pass
        for ch in chains:
            w3(ch).provider.make_request("anvil_mine", ["0x3"])  # type: ignore[arg-type]
        with rt.engine.connect() as c:
            busy = c.execute(
                text(
                    "SELECT count(*) FROM payment_intents WHERE org_id=:o "
                    "AND status IN ('READY','SUBMITTED','UNKNOWN')"
                ),
                {"o": org},
            ).scalar_one()
        if not busy:
            return
        rt.clock.advance(timedelta(seconds=15))
        time.sleep(0.05)  # the bank simulator settles in real time
    raise AssertionError("payments still in flight after the worker drained")


def _statuses(rt: Runtime) -> dict[str, str]:
    with rt.engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT reference, status FROM payment_intents WHERE org_id=:o AND reference LIKE 'demo batch %'"
            ),
            {"o": rt.settings.demo_org_id},
        ).all()
    return {r.reference.removeprefix("demo batch "): r.status for r in rows}


def _transfers_to(ch: devchain.LocalChain, to: str) -> int:
    logs = usdc(ch).events.Transfer.get_logs(from_block=0, argument_filters={"to": to})
    return len(logs)


def test_canonical_invoice_then_forced_timeout_pays_once(
    demo: Runtime, base_chain: devchain.LocalChain, eth_chain: devchain.LocalChain
) -> None:
    """Minutes 1 to 6: the $18,500 invoice escalates, is approved, times out to UNKNOWN, and is confirmed
    from the chain with no second send."""
    org = demo.settings.demo_org_id
    pl = Actor(demo_user_id("usr_pl", org), "payments_lead")
    inv = run_scenario(demo, org, "invoice_18500", pl)
    proposal = inv.links[0][1].rsplit("/", 1)[1]
    assert run_scenario(demo, org, "invoice_18500", pl).repeated  # idempotent: nothing new
    with demo.engine.connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM agent_calls WHERE org_id=:o AND kind='instruction'"), {"o": org}
        ).scalar_one()
    assert n == 1

    with TestClient(
        create_app(demo.settings, engine=demo.engine, clock=demo.clock, configure_logging=False)
    ) as c:
        login(c, pl.id)
        r = c.post(f"/console/invoices/{proposal}/submit", follow_redirects=False)
        assert r.status_code == 303 and "error" not in r.headers["location"], (r.status_code, r.text[:500])
    with demo.engine.connect() as c:
        pay = c.execute(
            text("SELECT payment_id FROM agent_calls WHERE org_id=:o AND id=:i"), {"o": org, "i": proposal}
        ).scalar_one()
        case = c.execute(
            text("SELECT id FROM exception_cases WHERE org_id=:o AND payment_id=:p"), {"o": org, "p": pay}
        ).scalar_one()
        status = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org, "p": pay}
        ).scalar_one()
        payee = c.execute(
            text("SELECT address FROM destinations WHERE org_id=:o AND id='dst_bluefin_base'"), {"o": org}
        ).scalar_one()
    assert status == "ESCALATED"

    run_scenario(demo, org, "forced_timeout", pl)
    run_scenario(demo, org, "forced_timeout", pl)  # idempotent: still one armed fault
    import httpx

    armed = httpx.get(f"{demo.settings.faultproxy_url}/__faults").json()
    assert [a["fault"] for a in armed] == ["timeout_after_forward"]

    approve(
        demo.engine,
        demo.clock,
        case_id=case,
        org_id=org,
        actor=Actor(demo_user_id("usr_rv", org), "reviewer"),
        reason="checked the wallet and the invoice",
        mandate_key=MANDATE_KEY,
    )
    _drain(demo, [base_chain, eth_chain])
    with demo.engine.connect() as c:
        atts = c.execute(
            text(
                "SELECT status, tx_hash FROM attempts WHERE org_id=:o AND payment_id=:p ORDER BY attempt_no"
            ),
            {"o": org, "p": pay},
        ).all()
        kinds = (
            c.execute(
                text("SELECT kind FROM audit_events WHERE org_id=:o AND subject_id=:p ORDER BY seq"),
                {"o": org, "p": pay},
            )
            .scalars()
            .all()
        )
        final = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org, "p": pay}
        ).scalar_one()
    assert final == "CONFIRMED"
    assert len(atts) == 1 and atts[0].status == "CONFIRMED"  # one attempt, never resent
    assert any("unknown" in k.lower() for k in kinds), kinds  # it went through UNKNOWN
    from web3 import Web3

    payee = Web3.to_checksum_address(payee)
    assert _transfers_to(base_chain, payee) == 1
    assert int(usdc(base_chain).functions.balanceOf(payee).call()) == 18_500 * 10**6


def test_batch_moves_money_on_three_rails_with_one_break(
    demo: Runtime, base_chain: devchain.LocalChain, eth_chain: devchain.LocalChain
) -> None:
    org = demo.settings.demo_org_id
    pl = Actor(demo_user_id("usr_pl", org), "payments_lead")
    res = run_scenario(demo, org, "batch_20", pl)
    assert "p08 failover not armed" not in " ".join(res.lines)
    _drain(demo, [base_chain, eth_chain])
    st = _statuses(demo)
    assert len(st) == 20
    expect = {p["ref"]: p["expect"] for p in batch()["payouts"]}
    want = {"EXECUTE": "CONFIRMED", "ESCALATE": "ESCALATED", "BLOCK": "BLOCKED"}
    assert st == {ref: want[e] for ref, e in expect.items()}
    with demo.engine.connect() as c:
        rails_used = set(
            c.execute(
                text("SELECT DISTINCT rail_id FROM attempts WHERE org_id=:o AND status='CONFIRMED'"),
                {"o": org},
            ).scalars()
        )
        p08 = c.execute(
            text(
                "SELECT a.rail_id, a.status, a.payment_id FROM attempts a JOIN payment_intents p "
                "ON p.org_id=a.org_id AND p.id=a.payment_id WHERE a.org_id=:o AND p.reference='demo batch p08' "
                "ORDER BY a.attempt_no"
            ),
            {"o": org},
        ).all()
        blocked_attempts = c.execute(
            text(
                "SELECT count(*) FROM attempts a JOIN payment_intents p ON p.org_id=a.org_id AND p.id=a.payment_id "
                "WHERE a.org_id=:o AND p.status='BLOCKED'"
            ),
            {"o": org},
        ).scalar_one()
    assert {"base-sepolia", "eth-sepolia", "banksim-sepa-inst", "banksim-fps"} <= rails_used  # three rails
    assert [(a.rail_id, a.status) for a in p08] == [("base-sepolia", "FAILED"), ("eth-sepolia", "CONFIRMED")]
    assert len({a.payment_id for a in p08}) == 1  # failover under the same payment ID
    assert blocked_attempts == 0  # the block is never re-routed

    close = run_scenario(demo, org, "close_day", pl)
    with demo.engine.connect() as c:
        breaks = c.execute(text("SELECT kind FROM recon_breaks WHERE org_id=:o"), {"o": org}).scalars().all()
        credits = c.execute(
            text(
                "SELECT d.account_ref, count(cr.id) FROM deposit_intents d LEFT JOIN credits cr "
                "ON cr.org_id=d.org_id AND cr.deposit_intent_id=d.id WHERE d.org_id=:o GROUP BY d.id, d.account_ref"
            ),
            {"o": org},
        ).all()
    assert breaks == ["unallocated_inbound"]  # exactly one designed break: dep-07
    assert sorted(int(n) for _, n in credits) == [0] + [1] * 7  # dep-08's duplicate is credited once
    # C-10 (Confirmed, D-35): only money-moving items count: 17 settled payouts and 8 deposits, one unmatched.
    assert "24 of 25 money-moving items matched, 1 break" in " ".join(close.lines), close.lines

    again = run_scenario(demo, org, "batch_20", pl)
    assert again.repeated and len(_statuses(demo)) == 20  # idempotent: no new payments or deposits


def test_match_line_counts_approved_escalations(
    demo: Runtime, base_chain: devchain.LocalChain, eth_chain: devchain.LocalChain
) -> None:
    """C-10 (D-35): if the presenter approves both held escalations before Close the day, they move money and
    count: 19 payouts and 8 deposits, 26 matched and the one designed break (spec/11 notes)."""
    org = demo.settings.demo_org_id
    pl = Actor(demo_user_id("usr_pl", org), "payments_lead")
    run_scenario(demo, org, "batch_20", pl)
    _drain(demo, [base_chain, eth_chain])
    with demo.engine.connect() as c:
        cases = (
            c.execute(
                text(
                    "SELECT x.id FROM exception_cases x JOIN payment_intents p ON p.org_id=x.org_id "
                    "AND p.id=x.payment_id WHERE x.org_id=:o AND p.reference LIKE 'demo batch %' "
                    "AND p.status='ESCALATED' ORDER BY p.reference"
                ),
                {"o": org},
            )
            .scalars()
            .all()
        )
    assert len(cases) == 2
    for case in cases:
        approve(
            demo.engine,
            demo.clock,
            case_id=case,
            org_id=org,
            actor=Actor(demo_user_id("usr_rv", org), "reviewer"),
            reason="called the counterparty and checked the new details",
            mandate_key=MANDATE_KEY,
        )
    _drain(demo, [base_chain, eth_chain])
    st = _statuses(demo)
    assert sorted(st.values()).count("CONFIRMED") == 19 and list(st.values()).count("BLOCKED") == 1
    close = run_scenario(demo, org, "close_day", pl)
    assert "26 of 27 money-moving items matched, 1 break" in " ".join(close.lines), close.lines


def test_attack_sample_is_refused(demo: Runtime) -> None:
    org = demo.settings.demo_org_id
    pl = Actor(demo_user_id("usr_pl", org), "payments_lead")
    res = run_scenario(demo, org, "attack_sample", pl)
    text_ = "\n".join(res.lines)
    assert "Pay a screened payee: BLOCKED" in text_
    assert "refused" in text_ and "ALLOWED" not in text_
    assert "above its mandate: BLOCKED" in text_
    with demo.engine.connect() as c:
        sent = c.execute(text("SELECT count(*) FROM attempts WHERE org_id=:o"), {"o": org}).scalar_one()
    assert sent == 0  # nothing in the sample moved money
