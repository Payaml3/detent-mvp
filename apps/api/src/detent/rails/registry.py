"""Rails per organisation (the ``rails`` table) and their adapters built from settings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import yaml
from sqlalchemy import Connection, Engine, text

from detent.clock import Clock
from detent.domain.money import Money
from detent.rails.base import RailAdapter
from detent.settings import REPO_ROOT, Settings

EXPLORERS = {
    "base-sepolia": "https://sepolia.basescan.org/tx/{tx}",
    "eth-sepolia": "https://sepolia.etherscan.io/tx/{tx}",
}


@dataclass(frozen=True, slots=True)
class SharedWalletCap:
    """SBX-02: daily outflow caps on a shared faucet wallet, in minor units: for all organisations
    together, and for each one."""

    daily_minor: int
    org_daily_minor: int


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
    base_url: str | None = None,
    per_payment_limit: Money | None = None,
    daily_limit: Money | None = None,
    fee_flat_minor: int = 0,
    fee_bps: int = 0,
    est_fee_minor: int = 0,
    est_seconds: int = 1,
) -> None:
    conn.execute(
        text(
            "INSERT INTO rails (id, org_id, kind, network, chain_id, currency, enabled, weights, "
            "prefunded_daily_limit_minor, token_address, from_address, confirmations, explorer_tx_url, "
            "base_url, "
            "per_payment_limit_minor, daily_limit_minor, fee_flat_minor, fee_bps, est_fee_minor, "
            "est_seconds) "
            "VALUES (:id, :o, :k, :n, :c, :cur, true, CAST(:w AS jsonb), :lim, :tok, :frm, :conf, :exp, "
            ":url, "
            ":ppl, :dl, :ff, :fb, :ef, :es) "
            "ON CONFLICT (org_id, id) DO UPDATE SET token_address = EXCLUDED.token_address, "
            "from_address = EXCLUDED.from_address, confirmations = EXCLUDED.confirmations, "
            "prefunded_daily_limit_minor = EXCLUDED.prefunded_daily_limit_minor, base_url = "
            "EXCLUDED.base_url, "
            "est_fee_minor = EXCLUDED.est_fee_minor, est_seconds = EXCLUDED.est_seconds"
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
            "url": base_url,
            "ppl": per_payment_limit.amount_minor if per_payment_limit else None,
            "dl": daily_limit.amount_minor if daily_limit else None,
            "ff": fee_flat_minor,
            "fb": fee_bps,
            "ef": est_fee_minor,
            "es": est_seconds,
        },
    )


def local_chain_config() -> dict[str, Any] | None:
    path = REPO_ROOT / "chain" / "local.json"
    return dict(json.loads(path.read_text())) if path.exists() else None


def build_adapters(
    settings: Settings, engine: Engine, org_id: str, *, clock: Clock
) -> dict[str, RailAdapter]:
    """Adapters for the organisation's enabled rails.

    RAL-11, SBX-03: an organisation in `simulated` sandbox mode (the default for client and evaluation
    organisations) gets the simulated chain for base-sepolia and eth-sepolia. In `testnet` mode an EVM rail
    needs a signer and an RPC URL in settings; a client or evaluation organisation then sends from the shared
    faucet wallet, under its daily caps (SBX-02). A rail without an adapter simply has none: payments routed
    to it are held, never sent another way.
    """
    from detent.rails.evm import EvmAdapter
    from detent.rails.signer import LocalKeySigner
    from detent.rails.simchain import SIMULATED_NETWORKS, SimChainAdapter

    keys = {
        "base-sepolia": (settings.base_sepolia_rpc_url, settings.test_wallet_private_key_base),
        "eth-sepolia": (settings.eth_sepolia_rpc_url, settings.test_wallet_private_key_eth),
        "local-evm": (settings.local_evm_rpc_url, settings.test_wallet_private_key_local),
    }
    out: dict[str, RailAdapter] = {}
    with engine.connect() as conn:
        org = conn.execute(
            text("SELECT kind, sandbox_rails FROM organisations WHERE org_id=:o"), {"o": org_id}
        ).one_or_none()
    simulated = org is not None and org.sandbox_rails == "simulated"
    shared_wallet = org is not None and org.kind in ("client", "evaluation")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, chain_id, token_address, confirmations, explorer_tx_url FROM rails "
                "WHERE org_id=:o AND enabled AND kind='evm'"
            ),
            {"o": org_id},
        ).all()
    with engine.connect() as conn:
        bank_rows = conn.execute(
            text(
                "SELECT id, currency, network, per_payment_limit_minor, fee_flat_minor, fee_bps, "
                "est_seconds, base_url "
                "FROM rails WHERE org_id=:o AND enabled AND kind='banksim'"
            ),
            {"o": org_id},
        ).all()
    from detent.rails.banksim import BankAdapter

    for b in bank_rows:
        out[b.id] = BankAdapter(
            rail_id=b.id,
            receiving_account=org_id,
            base_url=b.base_url or settings.banksim_url,
            scheme="fps" if b.id == "banksim-fps" else "sepa_inst",
            currency=b.currency,
            per_payment_limit_minor=b.per_payment_limit_minor,
            fee_flat_minor=int(b.fee_flat_minor),
            fee_bps=int(b.fee_bps),
            expected_seconds=int(b.est_seconds),
            timeout_seconds=settings.rail_timeout_seconds,
        )
    for r in rows:
        if simulated and r.id in SIMULATED_NETWORKS:
            out[r.id] = SimChainAdapter(rail_id=r.id, org_id=org_id, engine=engine, clock=clock)
            continue
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
            timeout_seconds=settings.rail_timeout_seconds,
        )
        if shared_wallet:  # SBX-02, SBX-03: the faucet wallet is shared, so its outflow is capped
            out[r.id].shared_wallet = SharedWalletCap(  # type: ignore[attr-defined]
                Money.parse(settings.faucet_daily_cap, "USDC").amount_minor,
                Money.parse(settings.faucet_org_daily_cap, "USDC").amount_minor,
            )
    return out


def _address_of(key: Any) -> str | None:
    if key is None:
        return None
    from eth_account import Account

    return str(Account.from_key(key.get_secret_value()).address)


def seed_rails(conn: Connection, org_id: str, settings: Settings) -> list[str]:
    """Install the fixture rails for an organisation. EVM rails get their token address from settings
    (and from chain/local.json for the local chain)."""
    data = yaml.safe_load((REPO_ROOT / "fixtures" / "rails.yaml").read_text())
    installed = []
    for r in data["rails"]:
        if r.get("sandbox_only") or r["id"] == "local-evm-b":  # local-evm-b exists only for failover tests
            continue
        install_fixture_rail(conn, org_id, settings, r, weights=data.get("routing_weights"))
        installed.append(r["id"])
    return installed


def fixture_rails() -> list[dict[str, Any]]:
    """The rail entries in fixtures/rails.yaml."""
    return list(yaml.safe_load((REPO_ROOT / "fixtures" / "rails.yaml").read_text())["rails"])


def install_fixture_rail(
    conn: Connection,
    org_id: str,
    settings: Settings,
    r: dict[str, Any],
    *,
    weights: dict[str, Any] | None = None,
) -> None:
    """One fixtures/rails.yaml entry, installed (or updated) for an organisation."""
    local = local_chain_config() or {}
    tokens = {
        "base-sepolia": settings.usdc_address_base_sepolia,
        "eth-sepolia": settings.usdc_address_eth_sepolia,
        "local-evm": local.get("usdc_address"),
    }
    senders = {
        "base-sepolia": settings.test_wallet_private_key_base,
        "eth-sepolia": settings.test_wallet_private_key_eth,
        "local-evm": settings.test_wallet_private_key_local,
    }
    lim = r.get("prefunded_daily_limit")
    fee = r.get("fee") or {}
    ppl, dl = r.get("per_payment_limit"), r.get("daily_limit")
    install_rail(
        conn,
        org_id,
        rail_id=r["id"],
        kind=r["kind"],
        network=r["id"],
        currency=r["currency"],
        chain_id=r.get("chain_id"),
        token_address=tokens.get(r["id"]),
        # The sending wallet, so the watcher records the rail's own payouts for reconciliation (S9 found
        # seeded rails had none, so every chain payout showed as missing on the rail).
        from_address=_address_of(senders.get(r["id"])),
        confirmations=int(r.get("confirmations", 1)),
        prefunded_daily_limit=Money.parse(lim, r["currency"]) if lim else None,
        weights=weights,
        per_payment_limit=Money.parse(ppl, r["currency"]) if ppl else None,
        daily_limit=Money.parse(dl, r["currency"]) if dl else None,
        fee_flat_minor=int(fee.get("flat_minor", 0)),
        fee_bps=int(fee.get("bps", 0)),
        est_fee_minor=int(r.get("est_fee_minor", fee.get("flat_minor", 0))),
        est_seconds=int(r.get("est_seconds", 1)),
    )
