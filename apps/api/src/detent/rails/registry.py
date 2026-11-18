"""Rails per organisation (the ``rails`` table) and their adapters built from settings."""

from __future__ import annotations

import json
from typing import Any

import yaml
from sqlalchemy import Connection, Engine, text

from detent.domain.money import Money
from detent.rails.base import RailAdapter
from detent.settings import REPO_ROOT, Settings

EXPLORERS = {
    "base-sepolia": "https://sepolia.basescan.org/tx/{tx}",
    "eth-sepolia": "https://sepolia.etherscan.io/tx/{tx}",
}


def install_rail(
    conn: Connection,
    org_id: str,
    *,
    rail_id: str,
    kind: str,
    network: str,
    currency: str,
    chain_id: int | None = None,
    token_address: str | None = None,
    from_address: str | None = None,
    confirmations: int = 1,
    prefunded_daily_limit: Money | None = None,
    weights: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO rails (id, org_id, kind, network, chain_id, currency, enabled, weights, "
            "prefunded_daily_limit_minor, token_address, from_address, confirmations, explorer_tx_url) "
            "VALUES (:id, :o, :k, :n, :c, :cur, true, CAST(:w AS jsonb), :lim, :tok, :frm, :conf, :exp) "
            "ON CONFLICT (org_id, id) DO UPDATE SET token_address = EXCLUDED.token_address, "
            "from_address = EXCLUDED.from_address, confirmations = EXCLUDED.confirmations, "
            "prefunded_daily_limit_minor = EXCLUDED.prefunded_daily_limit_minor"
        ),
        {
            "id": rail_id,
            "o": org_id,
            "k": kind,
            "n": network,
            "c": chain_id,
            "cur": currency,
            "w": json.dumps(weights) if weights else None,
            "lim": prefunded_daily_limit.amount_minor if prefunded_daily_limit else None,
            "tok": token_address,
            "frm": from_address.lower() if from_address else None,
            "conf": confirmations,
            "exp": EXPLORERS.get(rail_id),
        },
    )


def local_chain_config() -> dict[str, Any] | None:
    path = REPO_ROOT / "chain" / "local.json"
    return dict(json.loads(path.read_text())) if path.exists() else None


def build_adapters(settings: Settings, engine: Engine, org_id: str) -> dict[str, RailAdapter]:
    """Adapters for the organisation's enabled EVM rails that have a signer in settings.

    A rail without a configured signer or RPC URL simply has no adapter: payments routed to it are
    held, never sent another way.
    """
    from detent.rails.evm import EvmAdapter
    from detent.rails.signer import LocalKeySigner

    keys = {
        "base-sepolia": (settings.base_sepolia_rpc_url, settings.test_wallet_private_key_base),
        "eth-sepolia": (settings.eth_sepolia_rpc_url, settings.test_wallet_private_key_eth),
        "local-evm": (settings.local_evm_rpc_url, settings.test_wallet_private_key_local),
    }
    out: dict[str, RailAdapter] = {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, chain_id, token_address, confirmations, explorer_tx_url FROM rails "
                "WHERE org_id=:o AND enabled AND kind='evm'"
            ),
            {"o": org_id},
        ).all()
    for r in rows:
        url, key = keys.get(r.id, (None, None))
        if not url or key is None or not r.token_address:
            continue
        out[r.id] = EvmAdapter(
            rail_id=r.id,
            rpc_url=url,
            expected_chain_id=int(r.chain_id),
            token_address=r.token_address,
            signer=LocalKeySigner(key),
            confirmations=int(r.confirmations),
            explorer_tx_url=r.explorer_tx_url,
        )
    return out


def seed_rails(conn: Connection, org_id: str, settings: Settings) -> list[str]:
    """Install the fixture rails for an organisation. EVM rails get their token address from settings
    (and from chain/local.json for the local chain)."""
    data = yaml.safe_load((REPO_ROOT / "fixtures" / "rails.yaml").read_text())
    local = local_chain_config() or {}
    tokens = {
        "base-sepolia": settings.usdc_address_base_sepolia,
        "eth-sepolia": settings.usdc_address_eth_sepolia,
        "local-evm": local.get("usdc_address"),
    }
    installed = []
    for r in data["rails"]:
        if r.get("sandbox_only"):
            continue
        lim = r.get("prefunded_daily_limit")
        install_rail(
            conn,
            org_id,
            rail_id=r["id"],
            kind=r["kind"],
            network=r["id"],
            currency=r["currency"],
            chain_id=r.get("chain_id"),
            token_address=tokens.get(r["id"]),
            confirmations=int(r.get("confirmations", 1)),
            prefunded_daily_limit=Money.parse(lim, r["currency"]) if lim else None,
            weights=data.get("routing_weights"),
        )
        installed.append(r["id"])
    return installed
