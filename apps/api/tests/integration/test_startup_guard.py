"""FND-02: the app and the worker exit with a clear error on a non-test chain ID."""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env, have_foundry
from detent.settings import REPO_ROOT

pytestmark = pytest.mark.db


def _run(args: list[str], **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "detent", *args],
        env=child_env(**env),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _mainnet_rails(tmp_path: Path) -> str:
    p = tmp_path / "rails.yaml"
    p.write_text("rails:\n  - {id: base, kind: evm, chain_id: 8453, currency: USDC}\n")
    return str(p)


@pytest.mark.parametrize("command", ["api", "worker", "check-config"])
def test_mainnet_chain_id_stops_startup(tmp_path: Path, command: str) -> None:
    r = _run([command], RAILS_CONFIG=_mainnet_rails(tmp_path))
    assert r.returncode == 2
    assert "refusing to start" in r.stderr and "8453" in r.stderr


def test_widening_allowed_chain_ids_stops_startup() -> None:
    r = _run(["check-config"], ALLOWED_CHAIN_IDS="84532,11155111,31337,1")
    assert r.returncode == 2 and "non-test-network" in r.stderr


def test_default_config_starts() -> None:
    r = _run(["check-config"])
    assert r.returncode == 0, r.stderr
    assert "settings OK" in r.stdout


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.chain
@pytest.mark.skipif(not have_foundry(), reason="anvil not installed")
@pytest.mark.parametrize(
    ("chain_id", "message"), [(1, "not an allowed test network"), (84532, "configured for")]
)
def test_rpc_reporting_a_different_chain_stops_startup(chain_id: int, message: str) -> None:
    from detent.devchain import _bin

    port = _free_port()
    anvil = subprocess.Popen([_bin("anvil"), "--port", str(port), "--chain-id", str(chain_id), "--silent"])
    try:
        import time

        import httpx

        for _ in range(100):
            try:
                httpx.post(
                    f"http://127.0.0.1:{port}", json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId"}
                )
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        # The config says local-evm is chain 31337, but the endpoint answers as another chain.
        r = _run(["worker"], LOCAL_EVM_RPC_URL=f"http://127.0.0.1:{port}")
    finally:
        anvil.terminate()
    assert r.returncode == 2
    assert message in r.stderr
