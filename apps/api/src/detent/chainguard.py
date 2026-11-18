"""Checks the chain ID that each configured RPC endpoint actually reports (invariant 14).

The settings guard checks configured chain IDs. This checks the live endpoints too, so that an RPC
URL pointing at a mainnet node is caught even when the config says "Sepolia". A mismatch or a
non-test chain stops startup. An unreachable endpoint is reported but does not stop startup: that
rail is simply unhealthy, and the rail adapter (M3) re-checks the chain ID before it sends.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from detent.settings import Settings, TestNetworkGuardError

log = logging.getLogger("detent.chainguard")


@dataclass(frozen=True, slots=True)
class RpcCheck:
    rail_id: str
    url_configured: bool
    reachable: bool
    chain_id: int | None


def rpc_chain_id(url: str, timeout: float = 3.0) -> int:
    resp = httpx.post(
        url, json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}, timeout=timeout
    )
    resp.raise_for_status()
    return int(resp.json()["result"], 16)


def _rpc_urls(settings: Settings) -> dict[str, str | None]:
    return {
        "base-sepolia": settings.base_sepolia_rpc_url,
        "eth-sepolia": settings.eth_sepolia_rpc_url,
        "local-evm": settings.local_evm_rpc_url,
    }


def check_rpc_endpoints(settings: Settings, timeout: float = 3.0) -> list[RpcCheck]:
    expected = settings.configured_chain_ids()
    out: list[RpcCheck] = []
    for rail_id, url in _rpc_urls(settings).items():
        if not url:
            out.append(RpcCheck(rail_id, False, False, None))
            continue
        try:
            actual = rpc_chain_id(url, timeout)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("rpc endpoint unreachable", extra={"rail_id": rail_id, "error": type(exc).__name__})
            out.append(RpcCheck(rail_id, True, False, None))
            continue
        if actual not in settings.allowed_chain_ids:
            raise TestNetworkGuardError(
                f"RPC for {rail_id} reports chain ID {actual}, which is not an allowed test network "
                f"{sorted(settings.allowed_chain_ids)}. Refusing to start (invariant 14)."
            )
        if rail_id in expected and expected[rail_id] != actual:
            raise TestNetworkGuardError(
                f"RPC for {rail_id} reports chain ID {actual} but the rail is configured for "
                f"{expected[rail_id]}. Refusing to start."
            )
        out.append(RpcCheck(rail_id, True, True, actual))
    return out
