"""``detent demo check`` (DEM-04): test-wallet balances per wallet and chain, and what to top up.

Two kinds of wallet take part in the demo on each test network: the platform's sending wallet
(``TEST_WALLET_PRIVATE_KEY_*``, it pays the payouts) and the fictional payer (``DEMO_PAYER_PRIVATE_KEY_*``,
it sends the batch's deposits). The amounts needed come from the demo fixtures, so they stay in step with
the script. Test networks only: the chain each RPC reports is checked against the rail's test chain ID.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml
from pydantic import SecretStr

from detent.chainguard import DEMO_CHAINS
from detent.settings import REPO_ROOT, Settings

GAS_NEEDED_WEI = {"base-sepolia": 2 * 10**16, "eth-sepolia": 5 * 10**16}  # 0.02 and 0.05 test ETH
CANONICAL_MINOR = 1_850_000  # the $18,500 invoice, paid on Base Sepolia (spec/11 minute 4 to 6)
FAUCETS = {
    "base-sepolia": (
        "Test ETH: a Base Sepolia faucet listed at docs.base.org (tools, network faucets). "
        "Test USDC: the demo's own test token (D-33): detent demo token fund --network base-sepolia."
    ),
    "eth-sepolia": (
        "Test ETH: a Sepolia faucet (for example the ones listed at ethereum.org, developers, networks). "
        "Test USDC: the demo's own test token (D-33): detent demo token fund --network eth-sepolia."
    ),
}


@dataclass(frozen=True, slots=True)
class WalletLine:
    role: str  # "sender" (pays payouts) or "payer" (sends the batch's deposits)
    network: str
    address: str | None
    usdc_minor: int | None  # cents
    usdc_needed_minor: int
    gas_wei: int | None
    gas_needed_wei: int
    status: str  # ok | top_up | not_configured | unreachable | wrong_chain

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def needed_usdc(network: str) -> dict[str, int]:
    """USDC in cents each wallet needs for one full demo run on a network, from the fixtures."""
    data = yaml.safe_load((REPO_ROOT / "fixtures" / "batches" / "demo-batch-20.yaml").read_text())

    def cents(a: str) -> int:
        whole, _, frac = a.partition(".")
        return int(whole) * 100 + int((frac + "00")[:2])

    sender = CANONICAL_MINOR if network == "base-sepolia" else 0
    for p in data["payouts"]:
        if p["currency"] != "USDC" or p.get("counterparty") in ("cpt_flagged", "cpt_nova"):
            continue  # blocked or escalated in the script: nothing moves unless approved
        if p.get("network") == network or (p.get("allow_network_switch") and network == "eth-sepolia"):
            sender += cents(p["amount"])
    payer = 0
    for d in data["deposits"]:
        if d["currency"] != "USDC":
            continue
        on = "base-sepolia" if d.get("sent_to") else d.get("network")
        if on == network:
            payer += cents(d["amount"])
    return {"sender": sender, "payer": payer}


def _balances(url: str, token: str, address: str) -> tuple[int, int, int]:
    """(chain ID, USDC in cents, gas in wei)."""
    from web3 import Web3

    from detent.rails.evm import ERC20_ABI

    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 5}))
    chain = int(w3.eth.chain_id)
    c = w3.eth.contract(address=Web3.to_checksum_address(token), abi=ERC20_ABI)
    units = int(c.functions.balanceOf(Web3.to_checksum_address(address)).call())
    return chain, units // 10**4, int(w3.eth.get_balance(Web3.to_checksum_address(address)))


def _address(key: SecretStr | None) -> str | None:
    if key is None:
        return None
    from eth_account import Account

    return str(Account.from_key(key.get_secret_value()).address)


def check_wallets(settings: Settings, balances: Any = _balances) -> list[WalletLine]:
    urls = {"base-sepolia": settings.base_sepolia_rpc_url, "eth-sepolia": settings.eth_sepolia_rpc_url}
    tokens = {
        "base-sepolia": settings.usdc_address_base_sepolia,
        "eth-sepolia": settings.usdc_address_eth_sepolia,
    }
    keys = {
        ("sender", "base-sepolia"): settings.test_wallet_private_key_base,
        ("sender", "eth-sepolia"): settings.test_wallet_private_key_eth,
        ("payer", "base-sepolia"): settings.demo_payer_private_key_base,
        ("payer", "eth-sepolia"): settings.demo_payer_private_key_eth,
    }
    out: list[WalletLine] = []
    for network, chain_id in DEMO_CHAINS.items():
        need = needed_usdc(network)
        for role in ("sender", "payer"):
            addr = _address(keys[(role, network)])
            gas_need = GAS_NEEDED_WEI[network]
            url = urls[network]
            if addr is None or not url:
                out.append(
                    WalletLine(role, network, addr, None, need[role], None, gas_need, "not_configured")
                )
                continue
            try:
                chain, usdc, gas = balances(url, tokens[network], addr)
            except Exception:  # an unreachable RPC is reported, never raised
                out.append(WalletLine(role, network, addr, None, need[role], None, gas_need, "unreachable"))
                continue
            if chain != chain_id:
                out.append(WalletLine(role, network, addr, None, need[role], None, gas_need, "wrong_chain"))
                continue
            status = "ok" if usdc >= need[role] and gas >= gas_need else "top_up"
            out.append(WalletLine(role, network, addr, usdc, need[role], gas, gas_need, status))
    return out


def _usd(cents: int | None) -> str:
    return "?" if cents is None else f"{cents // 100:,}.{cents % 100:02d}"


def _eth(wei: int | None) -> str:
    return "?" if wei is None else f"{wei / 10**18:.4f}"


def render(lines: list[WalletLine]) -> str:
    rows = ["Demo wallets (test networks only)", ""]
    advice: list[str] = []
    for w in lines:
        who = "sending wallet (payouts)" if w.role == "sender" else "demo payer (deposits)"
        rows.append(
            f"{w.network:<13} {who:<25} {w.address or '-':<43} "
            f"USDC {_usd(w.usdc_minor):>10} / need {_usd(w.usdc_needed_minor):>10}   "
            f"gas {_eth(w.gas_wei):>8} / need {_eth(w.gas_needed_wei)}   {w.status.upper()}"
        )
        env = ("TEST_WALLET_PRIVATE_KEY_" if w.role == "sender" else "DEMO_PAYER_PRIVATE_KEY_") + (
            "BASE" if w.network == "base-sepolia" else "ETH"
        )
        rpc = "BASE_SEPOLIA_RPC_URL" if w.network == "base-sepolia" else "ETH_SEPOLIA_RPC_URL"
        if w.status == "not_configured":
            advice.append(f"- {w.network} {who}: set {env} (a test wallet's key) and {rpc}.")
        elif w.status == "unreachable":
            advice.append(f"- {w.network}: the RPC at {rpc} did not answer.")
        elif w.status == "wrong_chain":
            advice.append(f"- {w.network}: {rpc} is not {w.network}. Fix it before the demo.")
        elif w.status == "top_up":
            short_usdc = max(0, w.usdc_needed_minor - (w.usdc_minor or 0))
            short_gas = max(0, w.gas_needed_wei - (w.gas_wei or 0))
            parts = []
            if short_usdc:
                parts.append(f"{_usd(short_usdc)} test USDC")
            if short_gas:
                parts.append(f"{_eth(short_gas)} test ETH")
            advice.append(
                f"- {w.network} {who} {w.address}: top up {' and '.join(parts)}. {FAUCETS[w.network]}"
            )
    rows.append("")
    if advice:
        rows.append("To do before the demo:")
        rows.extend(advice)
    else:
        rows.append("All demo wallets hold enough test USDC and gas for one full run.")
    return "\n".join(rows)
