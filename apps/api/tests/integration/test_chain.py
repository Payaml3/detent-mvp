"""FND-09: anvil plus a 6-decimal MockUSDC, deployed by script."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator

import pytest
from conftest import have_foundry
from detent import devchain
from detent.chainguard import rpc_chain_id
from detent.settings import TestNetworkGuardError

pytestmark = [pytest.mark.chain, pytest.mark.skipif(not have_foundry(), reason="anvil not installed")]


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def chain() -> Iterator[devchain.LocalChain]:
    port = _port()
    proc = devchain.start_anvil(port)
    try:
        yield devchain.deploy(f"http://127.0.0.1:{port}")
    finally:
        proc.terminate()


def test_local_chain_is_31337(chain: devchain.LocalChain) -> None:
    assert chain.chain_id == 31337 == rpc_chain_id(chain.rpc_url)


def test_mock_usdc_has_6_decimals_and_funded_accounts(chain: devchain.LocalChain) -> None:
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(chain.rpc_url))
    usdc = w3.eth.contract(address=chain.usdc_address, abi=devchain.abi())
    assert usdc.functions.decimals().call() == 6
    assert usdc.functions.symbol().call() == "USDC"
    assert usdc.functions.balanceOf(chain.accounts[0]).call() == devchain.MINT_MINOR


def test_transfer_moves_exact_minor_units(chain: devchain.LocalChain) -> None:
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(chain.rpc_url))
    usdc = w3.eth.contract(address=chain.usdc_address, abi=devchain.abi())
    a, b = chain.accounts[1], chain.accounts[5]
    before = usdc.functions.balanceOf(b).call()
    h = usdc.functions.transfer(b, 18_500_000_000).transact({"from": a})  # 18,500.00 USDC
    rcpt = w3.eth.wait_for_transaction_receipt(h)
    assert rcpt["status"] == 1
    assert usdc.functions.balanceOf(b).call() - before == 18_500_000_000


def test_overdraft_reverts_with_status_0(chain: devchain.LocalChain) -> None:
    """A reverted transfer gives receipt status 0, the input for TECHNICAL_FINAL (spec/06)."""
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(chain.rpc_url))
    usdc = w3.eth.contract(address=chain.usdc_address, abi=devchain.abi())
    empty = chain.accounts[9]
    h = usdc.functions.transfer(chain.accounts[0], 1).transact({"from": empty, "gas": 100_000})
    assert w3.eth.wait_for_transaction_receipt(h)["status"] == 0


def test_write_config(chain: devchain.LocalChain, tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "local.json"
    devchain.write_config(chain, p)
    assert json.loads(p.read_text())["usdc_address"] == chain.usdc_address


def test_deploy_refuses_any_other_chain() -> None:
    port = _port()
    proc = devchain.start_anvil(port)
    proc.terminate()
    proc.wait()
    import subprocess

    other = subprocess.Popen([devchain._bin("anvil"), "--port", str(port), "--chain-id", "84532", "--silent"])
    try:
        import time

        for _ in range(100):
            try:
                rpc_chain_id(f"http://127.0.0.1:{port}")
                break
            except Exception:
                time.sleep(0.1)
        with pytest.raises(TestNetworkGuardError, match="local chain only"):
            devchain.deploy(f"http://127.0.0.1:{port}")
    finally:
        other.terminate()
