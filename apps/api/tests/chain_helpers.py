"""A local anvil chain with MockUSDC, a fresh funded wallet per test, and an organisation whose
local-evm rail sends from that wallet. Keys are generated at runtime; none is ever written down."""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from datetime import timedelta

import pytest
from conftest import have_foundry
from decision_helpers import DecisionOrg, setup_decision_org
from detent import devchain
from detent.clock import FrozenClock
from detent.domain.money import Money
from detent.intents.service import IntentRequest, submit_intent
from detent.policy.screening import MockScreening
from detent.rails.evm import EvmAdapter
from detent.rails.registry import install_rail
from detent.rails.signer import LocalKeySigner
from pydantic import SecretStr
from sqlalchemy import Engine, text

needs_chain = [pytest.mark.chain, pytest.mark.skipif(not have_foundry(), reason="anvil not installed")]


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def w3(chain: devchain.LocalChain):  # type: ignore[no-untyped-def]
    from web3 import Web3

    return Web3(Web3.HTTPProvider(chain.rpc_url))


def usdc(chain: devchain.LocalChain):  # type: ignore[no-untyped-def]
    return w3(chain).eth.contract(address=chain.usdc_address, abi=devchain.abi())


def new_wallet(
    chain: devchain.LocalChain, *, usdc_minor: int = 0, eth_wei: int = 10**18
) -> tuple[str, SecretStr]:
    from eth_account import Account

    acct = Account.create()
    web3 = w3(chain)
    web3.provider.make_request("anvil_setBalance", [acct.address, hex(eth_wei)])  # type: ignore[arg-type]
    if usdc_minor:
        h = usdc(chain).functions.mint(acct.address, usdc_minor).transact({"from": chain.accounts[0]})
        web3.eth.wait_for_transaction_receipt(h)
    return acct.address, SecretStr(acct.key.hex())


def balance(chain: devchain.LocalChain, address: str) -> int:
    return int(usdc(chain).functions.balanceOf(address).call())


@dataclass
class ChainOrg:
    d: DecisionOrg
    chain: devchain.LocalChain
    sender: str
    payee: str
    adapter: EvmAdapter
    adapters: dict[str, EvmAdapter] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.d.id

    def payout(self, engine: Engine, clock: FrozenClock, amount: str, key: str | None = None) -> str:
        req = IntentRequest.model_validate(
            {
                "kind": "payout",
                "source": "platform",
                "counterparty_id": "cpt_local",
                "destination": {"kind": "evm_wallet", "network": "local-evm", "address": self.payee},
                "amount": {"amount": amount, "currency": "USDC"},
            }
        )
        code, body = submit_intent(
            engine,
            clock,
            org_id=self.id,
            actor_id="usr_api",
            idempotency_key=key or f"k-{amount}-{clock.now().timestamp()}",
            request=req,
            decision_only=False,
            screening=MockScreening.from_fixture(),
        )
        assert code == 201, body
        return str(body["id"])


def setup_chain_org(
    engine: Engine,
    clock: FrozenClock,
    chain: devchain.LocalChain,
    *,
    usdc_minor: int = 1_000_000 * 10**6,
    prefunded_daily_limit: str | None = "40000.00",
) -> ChainOrg:
    """An organisation with a local-evm rail, and a long-standing verified payee whose payouts EXECUTE."""
    d = setup_decision_org(engine, clock)
    sender, key = new_wallet(chain, usdc_minor=usdc_minor)
    payee, _ = new_wallet(chain, eth_wei=0)
    now = clock.now()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO counterparties (id, org_id, name, kyb_status, allowlisted, payment_count, median_amount_minor, "
                "median_currency, created_at) VALUES ('cpt_local', :o, 'Local Supplier Ltd (fictional)', 'verified', true, "
                "10, 100000000, 'USDC', :t)"
            ),
            {"o": d.id, "t": now},
        )
        conn.execute(
            text(
                "INSERT INTO destinations (id, org_id, counterparty_id, kind, network, address, verified, first_seen_at, "
                "last_changed_at) VALUES ('dst_local', :o, 'cpt_local', 'evm_wallet', 'local-evm', :a, true, :f, :f)"
            ),
            {"o": d.id, "a": payee, "f": now - timedelta(days=100)},
        )
        install_rail(
            conn,
            d.id,
            rail_id="local-evm",
            kind="evm",
            network="local-evm",
            chain_id=31337,
            currency="USDC",
            token_address=chain.usdc_address,
            from_address=sender,
            confirmations=1,
            prefunded_daily_limit=Money.parse(prefunded_daily_limit, "USDC")
            if prefunded_daily_limit
            else None,
        )
    adapter = EvmAdapter(
        rail_id="local-evm",
        rpc_url=chain.rpc_url,
        expected_chain_id=31337,
        token_address=chain.usdc_address,
        signer=LocalKeySigner(key),
        confirmations=1,
    )
    return ChainOrg(d, chain, sender, payee, adapter, {"local-evm": adapter})


def send_usdc(chain: devchain.LocalChain, frm: str, to: str, minor: int) -> None:
    web3 = w3(chain)
    token = usdc(chain)
    web3.eth.wait_for_transaction_receipt(
        token.functions.mint(frm, minor).transact({"from": chain.accounts[0]})
    )
    web3.provider.make_request("anvil_impersonateAccount", [frm])  # type: ignore[arg-type]
    web3.provider.make_request("anvil_setBalance", [frm, hex(10**18)])  # type: ignore[arg-type]
    web3.eth.wait_for_transaction_receipt(token.functions.transfer(to, minor).transact({"from": frm}))
