"""Local test chain: anvil plus MockUSDC (FND-09). Local development and CI only.

``make chain`` runs ``python -m detent.devchain``: it starts anvil (chain ID 31337), deploys
MockUSDC, mints test balances to the first anvil accounts and writes ``chain/local.json``. It then
keeps anvil running until interrupted.

Deployment uses anvil's unlocked dev accounts, so no private key is read or written here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from detent.settings import REPO_ROOT, TestNetworkGuardError

LOCAL_CHAIN_ID = 31337
CHAIN_DIR = REPO_ROOT / "chain"
ARTIFACT = CHAIN_DIR / "out" / "MockUSDC.sol" / "MockUSDC.json"
LOCAL_CONFIG = CHAIN_DIR / "local.json"
MINT_MINOR = 1_000_000 * 10**6  # 1,000,000 test USDC per funded account


@dataclass(frozen=True)
class LocalChain:
    rpc_url: str
    chain_id: int
    usdc_address: str
    accounts: list[str]


def _bin(name: str) -> str:
    path = shutil.which(name) or str(Path.home() / ".foundry" / "bin" / name)
    if not Path(path).exists():
        raise FileNotFoundError(f"{name} not found; install Foundry (see README)")
    return path


def build_contracts() -> None:
    if ARTIFACT.exists():
        return
    subprocess.run([_bin("forge"), "build", "--root", str(CHAIN_DIR)], check=True)  # noqa: S603


def start_anvil(port: int = 8545) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(  # noqa: S603
        [_bin("anvil"), "--port", str(port), "--chain-id", str(LOCAL_CHAIN_ID), "--silent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if proc.poll() is not None:
            err = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(f"anvil exited early: {err.strip()}")
        try:
            _rpc(url, "eth_chainId")
            return proc
        except httpx.HTTPError:
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("anvil did not start within 10 s")


def _rpc(url: str, method: str, params: list[Any] | None = None) -> Any:
    r = httpx.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}, timeout=5)
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise RuntimeError(f"{method}: {body['error']}")
    return body["result"]


def deploy(rpc_url: str) -> LocalChain:
    from web3 import Web3

    build_contracts()
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    chain_id = int(w3.eth.chain_id)
    if chain_id != LOCAL_CHAIN_ID:
        raise TestNetworkGuardError(f"refusing to deploy MockUSDC to chain {chain_id}; local chain only")
    art = json.loads(ARTIFACT.read_text())
    accounts = [str(a) for a in w3.eth.accounts]
    contract = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]["object"])
    tx = contract.constructor().transact({"from": accounts[0]})
    receipt = w3.eth.wait_for_transaction_receipt(tx, timeout=30)
    if receipt["status"] != 1:
        raise RuntimeError("MockUSDC deployment reverted")
    address = str(receipt["contractAddress"])
    usdc = w3.eth.contract(address=address, abi=art["abi"])
    for acct in accounts[:3]:
        h = usdc.functions.mint(acct, MINT_MINOR).transact({"from": accounts[0]})
        w3.eth.wait_for_transaction_receipt(h, timeout=30)
    return LocalChain(rpc_url=rpc_url, chain_id=chain_id, usdc_address=address, accounts=accounts[:10])


def write_config(chain: LocalChain, path: Path = LOCAL_CONFIG) -> None:
    path.write_text(json.dumps(asdict(chain), indent=2) + "\n")


def abi() -> list[dict[str, Any]]:
    build_contracts()
    data: list[dict[str, Any]] = json.loads(ARTIFACT.read_text())["abi"]
    return data


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8545
    proc = start_anvil(port)
    try:
        chain = deploy(f"http://127.0.0.1:{port}")
        write_config(chain)
        print(f"anvil on {chain.rpc_url} (chain {chain.chain_id}); MockUSDC at {chain.usdc_address}")
        print(f"wrote {LOCAL_CONFIG.relative_to(REPO_ROOT)}. Ctrl-C to stop.")
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
