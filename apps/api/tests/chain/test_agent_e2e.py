"""S5 exit check (demo minutes 1 to 6): invoice in, agent proposal, escalation, approval, one transfer.

The rail is called base-sepolia, as on the invoice, but runs against the local anvil chain (31337) in
this test. Nothing touches a public network.
"""

from __future__ import annotations

import time

import pytest
from chain_helpers import balance, needs_chain, new_wallet
from conftest import make_settings
from decision_helpers import PEPPER, setup_decision_org
from detent import devchain
from detent.agents.instruction import propose_from_invoice
from detent.agents.llm import RecordedLLM
from detent.agents.submit import submit_proposal
from detent.api.app import create_app
from detent.api.auth import issue_key
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.money import Money
from detent.domain.roles import Role
from detent.exceptions.cases import approve
from detent.execution.send import send_payment
from detent.mandates.store import fixture_mandate, issue_mandate
from detent.policy.screening import MockScreening
from detent.rails.evm import EvmAdapter
from detent.rails.registry import install_rail
from detent.rails.signer import LocalKeySigner
from detent.settings import REPO_ROOT
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = [pytest.mark.db, *needs_chain]

KEY = SecretStr("test-mandate-key-0123456789abcdef")
AGENT_KEY = "sk_" + "test_agente2e00000000000000000000000000"


def test_invoice_to_one_transfer(engine: Engine, clock: FrozenClock, chain: devchain.LocalChain) -> None:
    d = setup_decision_org(engine, clock)
    sender, skey = new_wallet(chain, usdc_minor=100_000 * 10**6)
    payee, _ = new_wallet(chain, eth_wei=0)
    with engine.begin() as c:
        c.execute(
            text("UPDATE destinations SET address=:a WHERE org_id=:o AND id='dst_bluefin_base'"),
            {"a": payee, "o": d.id},
        )
        install_rail(
            c,
            d.id,
            rail_id="base-sepolia",
            kind="evm",
            network="base-sepolia",
            chain_id=31337,
            currency="USDC",
            token_address=chain.usdc_address,
            from_address=sender,
            confirmations=1,
            prefunded_daily_limit=Money.parse("40000.00", "USDC"),
        )
        issue_mandate(c, clock, d.id, fixture_mandate(clock, d.id), KEY, actor=Actor.system("seed"))
        issue_key(
            c,
            clock,
            d.id,
            d.org.users[Role.PAYMENTS_LEAD],
            ["intents:create"],
            PEPPER,
            mandate_id="mnd_demo_ap_agent",
            key=AGENT_KEY,
        )
    document = (
        (REPO_ROOT / "fixtures" / "invoices" / "inv-canonical-18500-usdc.txt")
        .read_text()
        .replace("{{WALLET_BLUEFIN_BASE}}", payee)
    )
    llm = RecordedLLM.from_dir(
        REPO_ROOT / "fixtures" / "agent-recordings" / "instruction",
        placeholders={"WALLET_BLUEFIN_BASE": payee},
    )

    # 1. The agent proposes: the expected fields, no flags.
    p = propose_from_invoice(
        engine,
        clock,
        org_id=d.id,
        document=document,
        mandate_id="mnd_demo_ap_agent",
        llm=llm,
        model="claude-sonnet-5-5",
        daily_token_budget=2_000_000,
    )
    assert (
        not p.flags
        and p.proposal["amount"]["value"] == "18500.00"
        and p.proposal["wallet_address"]["value"] == payee
    )

    # 2. Submitted as the agent through the public API: escalated, never executed.
    app = create_app(
        make_settings(d.id, api_key_pepper=SecretStr(PEPPER), mandate_signing_key_demo=KEY),
        engine=engine,
        clock=clock,
        configure_logging=False,
    )
    with TestClient(app) as http:
        j = submit_proposal(engine, clock, http, agent_key=AGENT_KEY, org_id=d.id, proposal_id=p.id).json()
    assert j["status"] == "ESCALATED"
    assert {"FIRST_PAYMENT", "ABOVE_AUTO_LIMIT"} <= {c.get("reason") for c in j["decision"]["checks"]}

    # 3. The reviewer approves with a reason; the re-run executes.
    res = approve(
        engine,
        clock,
        case_id=j["exception"]["id"],
        org_id=d.id,
        actor=Actor(d.org.users[Role.REVIEWER], "reviewer"),
        reason="Invoice matches PO; new supplier onboarded",
        mandate_key=KEY,
    )
    assert res.payment_status == "READY"

    # 4. Sent once.
    adapter = EvmAdapter(
        rail_id="base-sepolia",
        rpc_url=chain.rpc_url,
        expected_chain_id=31337,
        token_address=chain.usdc_address,
        signer=LocalKeySigner(skey),
        confirmations=1,
    )
    adapters = {"base-sepolia": adapter}
    before = balance(chain, payee)
    for _ in range(3):  # extra send triggers change nothing
        send_payment(
            engine,
            clock,
            adapters,
            org_id=d.id,
            payment_id=j["id"],
            screening=MockScreening.from_fixture(),
            mandate_key=KEY,
        )
    for _ in range(50):
        if balance(chain, payee) - before == 18_500_000_000:
            break
        time.sleep(0.1)
    assert balance(chain, payee) - before == 18_500_000_000
    with engine.connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM attempts WHERE org_id=:o AND payment_id=:p"), {"o": d.id, "p": j["id"]}
        ).scalar()
        used = c.execute(text("SELECT total_minor FROM mandate_usage WHERE org_id=:o"), {"o": d.id}).scalar()
    assert n == 1 and used == 18_500_000_000  # the mandate's total counts it
