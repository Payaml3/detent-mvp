"""D-33 (G-27): the demo's own labelled test token deploys on the two Sepolias and nowhere else.

anvil plays each network by taking its chain ID (84532 for Base Sepolia, 11155111 for Ethereum Sepolia). A chain
outside the allowed three (here 1, Ethereum mainnet's ID) must revert in the contract's constructor, whatever
the Python side does. Keys are generated at runtime; none is written down.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator

import pytest
from chain_helpers import needs_chain
from conftest import make_settings
from detent import devchain
from detent.demo.token import TokenError, deploy_token, fund
from detent.demo.wallets import needed_usdc
from detent.settings import TestNetworkGuardError
from pydantic import SecretStr

pytestmark = needs_chain


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def anvil(request: pytest.FixtureRequest) -> Iterator[str]:
    port = _port()
    proc = devchain.start_anvil(port, chain_id=request.param)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait()


def _wallet(url: str) -> tuple[str, SecretStr]:
    from eth_account import Account
    from web3 import Web3

    acct = Account.create()
    Web3(Web3.HTTPProvider(url)).provider.make_request("anvil_setBalance", [acct.address, hex(10**18)])  # type: ignore[arg-type]
    return str(acct.address), SecretStr(acct.key.hex())


def _settings(network: str, url: str, sender: SecretStr, payer: SecretStr, token: str | None = None):  # type: ignore[no-untyped-def]
    suffix = "base" if network == "base-sepolia" else "eth"
    rpc = "base_sepolia_rpc_url" if network == "base-sepolia" else "eth_sepolia_rpc_url"
    kw: dict[str, object] = {
        rpc: url,
        f"test_wallet_private_key_{suffix}": sender,
        f"demo_payer_private_key_{suffix}": payer,
    }
    if token:
        kw[f"usdc_address_{network.replace('-', '_')}"] = token
    return make_settings("org_demo", **kw)


def _token(url: str, address: str):  # type: ignore[no-untyped-def]
    from web3 import Web3

    return Web3(Web3.HTTPProvider(url)).eth.contract(address=address, abi=devchain.abi())


@pytest.mark.parametrize(
    ("anvil", "network"), [(84532, "base-sepolia"), (11155111, "eth-sepolia")], indirect=["anvil"]
)
def test_deploys_on_the_sepolia_and_funds_both_wallets(anvil: str, network: str) -> None:
    sender, sender_key = _wallet(anvil)
    payer, payer_key = _wallet(anvil)
    address = deploy_token(_settings(network, anvil, sender_key, payer_key), network)
    t = _token(anvil, address)
    assert t.functions.symbol().call() == "tUSDC"
    assert t.functions.name().call() == "Dekernai Demo USD (test stand-in, not USDC)"
    assert t.functions.minter().call() == sender

    s = _settings(network, anvil, sender_key, payer_key, token=address)
    minted = fund(s, network, runs=2)
    need = needed_usdc(network)
    for who, role in ((sender, "sender"), (payer, "payer")):
        assert t.functions.balanceOf(who).call() == need[role] * 2 * 10**4
    assert {m.role for m in minted} == {r for r in ("sender", "payer") if need[r]}
    assert fund(s, network, runs=2) == []  # already enough: nothing more is minted


@pytest.mark.parametrize("anvil", [84532], indirect=True)
def test_only_the_deployer_can_mint(anvil: str) -> None:
    _, sender_key = _wallet(anvil)
    _, payer_key = _wallet(anvil)
    address = deploy_token(_settings("base-sepolia", anvil, sender_key, payer_key), "base-sepolia")
    # The payer is not the minter: funding with the payer as the sending wallet is refused before any send,
    with pytest.raises(TokenError, match="deployed by another wallet"):
        fund(_settings("base-sepolia", anvil, payer_key, sender_key, token=address), "base-sepolia")
    # and the contract itself reverts a mint from anyone but the deployer.
    from eth_account import Account
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(anvil))
    other = Account.from_key(payer_key.get_secret_value())
    data = _token(anvil, address).encode_abi("mint", args=[other.address, 1])
    with pytest.raises(Exception, match="minter only"):
        w3.eth.call({"from": other.address, "to": address, "data": data})


@pytest.mark.parametrize("anvil", [1], indirect=True)
def test_contract_reverts_on_any_other_chain(anvil: str) -> None:
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(anvil))
    art = json.loads(devchain.ARTIFACT.read_text())
    with pytest.raises(Exception, match="test chains only"):
        w3.eth.call({"from": w3.eth.accounts[0], "data": art["bytecode"]["object"]})


@pytest.mark.parametrize("anvil", [1], indirect=True)
def test_deploy_refuses_a_chain_that_is_not_the_network(anvil: str) -> None:
    _, key = _wallet(anvil)
    with pytest.raises(TestNetworkGuardError, match="expected 84532"):
        deploy_token(_settings("base-sepolia", anvil, key, key), "base-sepolia")
