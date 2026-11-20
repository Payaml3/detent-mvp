"""The demo's own test token on Base Sepolia and Ethereum Sepolia (DEM-04, decision D-33).

One demo run moves about $20,000 of test USDC, far more than Circle's faucet gives, so the live demo pays in
``MockUSDC``: a 6-decimal test stand-in for USDC, named "Detent Demo USD (test stand-in, not USDC)",
symbol ``tUSDC``. The contract itself refuses every chain but 31337, 84532 and 11155111, and only its
deployer can mint.

``detent demo token deploy --network base-sepolia`` deploys it from the platform's sending wallet
(``TEST_WALLET_PRIVATE_KEY_*``) and prints the ``USDC_ADDRESS_*`` value to set. ``detent demo token fund``
then mints what the sending wallet and the fictional payer need for a number of full runs (the amounts come
from the fixtures, as in ``detent demo check``). Gas still comes from a faucet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr

from detent.chainguard import DEMO_CHAINS
from detent.settings import Settings, TestNetworkGuardError

UNITS_PER_CENT = 10**4  # 6-decimal token units in one cent
ENV_NAME = {"base-sepolia": "USDC_ADDRESS_BASE_SEPOLIA", "eth-sepolia": "USDC_ADDRESS_ETH_SEPOLIA"}


class TokenError(Exception):
    """The demo token can't be deployed or funded with the current settings."""


@dataclass(frozen=True, slots=True)
class Minted:
    role: str
    address: str
    cents: int


def _rpc(settings: Settings, network: str) -> str:
    if network not in DEMO_CHAINS:
        raise TokenError(f"unknown network {network!r}; use one of {', '.join(DEMO_CHAINS)}")
    url = {"base-sepolia": settings.base_sepolia_rpc_url, "eth-sepolia": settings.eth_sepolia_rpc_url}[
        network
    ]
    if not url:
        raise TokenError(f"{network}: no RPC URL is set")
    return url


def _key(settings: Settings, role: str, network: str) -> SecretStr | None:
    return {
        ("sender", "base-sepolia"): settings.test_wallet_private_key_base,
        ("sender", "eth-sepolia"): settings.test_wallet_private_key_eth,
        ("payer", "base-sepolia"): settings.demo_payer_private_key_base,
        ("payer", "eth-sepolia"): settings.demo_payer_private_key_eth,
    }[(role, network)]


def _web3(url: str, network: str) -> Any:
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))
    chain = int(w3.eth.chain_id)
    if chain != DEMO_CHAINS[network]:
        raise TestNetworkGuardError(
            f"{network}: the RPC reports chain {chain}, expected {DEMO_CHAINS[network]}; refusing to send"
        )
    return w3


def _send(w3: Any, key: SecretStr, tx: dict[str, Any]) -> Any:
    from eth_account import Account

    acct = Account.from_key(key.get_secret_value())
    tx = {**tx, "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending")}
    tx.setdefault("chainId", int(w3.eth.chain_id))
    tx["gas"] = int(w3.eth.estimate_gas(tx) * 12 // 10)
    tx.setdefault("gasPrice", int(w3.eth.gas_price))
    signed = acct.sign_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction), 180)
    if receipt["status"] != 1:
        raise TokenError(f"transaction {receipt['transactionHash'].hex()} reverted")
    return receipt


def _artifact() -> dict[str, Any]:
    from detent import devchain

    devchain.build_contracts()
    data: dict[str, Any] = json.loads(devchain.ARTIFACT.read_text())
    return data


def deploy_token(settings: Settings, network: str) -> str:
    """Deploy the demo token from the sending wallet; returns its address."""
    key = _key(settings, "sender", network)
    if key is None:
        raise TokenError(f"{network}: the sending wallet's key (TEST_WALLET_PRIVATE_KEY_*) is not set")
    w3 = _web3(_rpc(settings, network), network)
    art = _artifact()
    contract = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]["object"])
    tx = contract.constructor().build_transaction({"from": _addr(key), "chainId": DEMO_CHAINS[network]})
    receipt = _send(w3, key, {k: v for k, v in tx.items() if k in ("data", "chainId", "value")})
    return str(receipt["contractAddress"])


def _addr(key: SecretStr) -> str:
    from eth_account import Account

    return str(Account.from_key(key.get_secret_value()).address)


def _token_address(settings: Settings, network: str) -> str:
    return (
        settings.usdc_address_base_sepolia if network == "base-sepolia" else settings.usdc_address_eth_sepolia
    )


def fund(settings: Settings, network: str, *, runs: int = 3, token: str | None = None) -> list[Minted]:
    """Mint enough of the demo token for ``runs`` full demo runs to the sending wallet and the payer.
    Only balances below that target are topped up. Minting is the deployer's (the sending wallet's) right."""
    from web3 import Web3

    from detent.demo.wallets import needed_usdc

    if runs < 1:
        raise TokenError("runs must be at least 1")
    sender_key = _key(settings, "sender", network)
    if sender_key is None:
        raise TokenError(f"{network}: the sending wallet's key (TEST_WALLET_PRIVATE_KEY_*) is not set")
    w3 = _web3(_rpc(settings, network), network)
    address = Web3.to_checksum_address(token or _token_address(settings, network))
    c = w3.eth.contract(address=address, abi=_artifact()["abi"])
    try:
        minter = str(c.functions.minter().call())
    except Exception as exc:
        raise TokenError(
            f"{network}: {address} is not the demo token (no minter); deploy it with detent demo token deploy"
        ) from exc
    if minter.lower() != _addr(sender_key).lower():
        raise TokenError(f"{network}: the demo token at {address} was deployed by another wallet ({minter})")
    need = needed_usdc(network)
    out: list[Minted] = []
    for role in ("sender", "payer"):
        key = _key(settings, role, network)
        if key is None or need[role] == 0:
            continue
        who = Web3.to_checksum_address(_addr(key))
        have_cents = int(c.functions.balanceOf(who).call()) // UNITS_PER_CENT
        short = need[role] * runs - have_cents
        if short <= 0:
            continue
        data = c.encode_abi("mint", args=[who, short * UNITS_PER_CENT])
        _send(w3, sender_key, {"to": address, "data": data, "value": 0})
        out.append(Minted(role, who, short))
    return out
