"""Connecting a rail (RAL-09, prototype): a mock consent screen or scoped API keys.

The organisation keeps its own rail accounts; DekernAI stores the credential it was given, Fernet-encrypted
with ``CREDENTIALS_ENCRYPTION_KEY`` (C-19), and never shows it again (only a short hint). Every rail here is a
test network or the simulated bank: the consent screen is a mock, no provider is called, and a live key is
refused (invariant 14). Disconnecting removes the stored credential and takes the rail out of routing.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.rails.registry import fixture_rails, install_fixture_rail
from detent.settings import Settings

LIVE_PREFIXES = ("sk_live_", "live_", "rk_live_", "pk_live_")


@dataclass(frozen=True)
class Connectable:
    rail_id: str
    label: str
    method: str  # consent | api_key
    provider: str
    scopes: tuple[str, ...]
    currency: str


SCOPES = {
    "evm": ("payouts:send", "balances:read", "transactions:read"),
    "banksim": ("payments:create", "payments:read", "accounts:read"),
}
NEEDED = {"evm": ("payouts:send",), "banksim": ("payments:create",)}


def catalogue() -> list[Connectable]:
    """Rails a client can connect: the testnet USDC rails by consent, the simulated bank rails by API key."""
    out = []
    for r in fixture_rails():
        if r.get("test_only") or r.get("sandbox_only") or r["kind"] not in SCOPES:
            continue
        evm = r["kind"] == "evm"
        out.append(
            Connectable(
                rail_id=r["id"],
                label=f"{r['id']} ({r['currency']})",
                method="consent" if evm else "api_key",
                provider="Mock custody wallet (test network)" if evm else "Simulated bank",
                scopes=SCOPES[r["kind"]],
                currency=r["currency"],
            )
        )
    return out


class ConnectionError_(Exception):
    def __init__(self, message: str, *, status: int = 422, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.status, self.code = status, code


def _fernet(settings: Settings) -> Fernet:
    key = settings.credentials_encryption_key
    if key is None:
        raise ConnectionError_(
            "Rail credentials can't be stored: CREDENTIALS_ENCRYPTION_KEY is not set on this instance.",
            status=503,
            code="credentials_unavailable",
        )
    try:
        return Fernet(key.get_secret_value().encode())
    except ValueError as exc:
        raise ConnectionError_(
            "Rail credentials can't be stored: the encryption key is not valid.",
            status=503,
            code="credentials_unavailable",
        ) from exc


def decrypt(settings: Settings, token: str) -> str:
    """For an adapter that needs the credential; never for display."""
    return _fernet(settings).decrypt(token.encode()).decode()


def find(rail_id: str) -> Connectable:
    for c in catalogue():
        if c.rail_id == rail_id:
            return c
    raise ConnectionError_(f"{rail_id} is not a rail that can be connected", status=404, code="not_found")


def _check_key(key: str) -> str:
    key = key.strip()
    if any(key.lower().startswith(p) for p in LIVE_PREFIXES):
        raise ConnectionError_(
            "Live keys are refused: the prototype connects test rails only (invariant 14)."
        )
    if not 16 <= len(key) <= 200 or not key.isascii() or any(ch.isspace() for ch in key):
        raise ConnectionError_("An API key is 16 to 200 characters with no spaces.")
    return key


def connect(
    engine: Engine,
    clock: Clock,
    settings: Settings,
    *,
    org_id: str,
    actor: Actor,
    rail_id: str,
    scopes: list[str],
    api_key: str | None = None,
) -> tuple[str, str]:
    """Stores the credential encrypted and enables the rail. Returns (connection ID, hint)."""
    c = find(rail_id)
    chosen = sorted(set(scopes))
    if not chosen or any(s not in c.scopes for s in chosen):
        raise ConnectionError_(f"Choose scopes from: {', '.join(c.scopes)}.")
    kind = "evm" if c.method == "consent" else "banksim"
    missing = [s for s in NEEDED[kind] if s not in chosen]
    if missing:
        raise ConnectionError_(f"DekernAI needs {', '.join(missing)} to send on this rail.")
    if c.method == "api_key":
        if not api_key:
            raise ConnectionError_("Enter the API key from the rail's dashboard.")
        credential = _check_key(api_key)
    else:
        credential = "mock_consent_" + secrets.token_urlsafe(24)  # stands in for the provider's token
    token = _fernet(settings).encrypt(credential.encode()).decode()
    hint = "..." + credential[-4:]
    now = clock.now()
    cid = new_id(Prefix.RCN, now)
    with transaction(engine) as conn:
        live = conn.execute(
            text(
                "SELECT id FROM rail_connections WHERE org_id=:o AND rail_id=:r AND disconnected_at IS NULL "
                "FOR UPDATE"
            ),
            {"o": org_id, "r": rail_id},
        ).first()
        if live is not None:
            raise ConnectionError_(
                f"{rail_id} is already connected; disconnect it first", status=409, code="conflict"
            )
        entry = next(r for r in fixture_rails() if r["id"] == rail_id)
        exists = conn.execute(
            text("SELECT 1 FROM rails WHERE org_id=:o AND id=:r FOR UPDATE"), {"o": org_id, "r": rail_id}
        ).first()
        if exists is None:
            install_fixture_rail(conn, org_id, settings, entry)
        conn.execute(
            text("UPDATE rails SET enabled=true WHERE org_id=:o AND id=:r"), {"o": org_id, "r": rail_id}
        )
        conn.execute(
            text(
                "INSERT INTO rail_connections (id, org_id, rail_id, method, scopes, credential, "
                "credential_hint, "
                "connected_by, connected_at) VALUES (:id, :o, :r, :m, :s, :c, :h, :by, :t)"
            ),
            {
                "id": cid,
                "o": org_id,
                "r": rail_id,
                "m": c.method,
                "s": chosen,
                "c": token,
                "h": hint,
                "by": actor.id,
                "t": now,
            },
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="rail.connected",
            subject_id=rail_id,
            payload={"connection_id": cid, "method": c.method, "scopes": chosen, "hint": hint},
        )
    return cid, hint


def disconnect(engine: Engine, clock: Clock, *, org_id: str, actor: Actor, rail_id: str) -> str:
    """Removes the stored credential and disables the rail, so routing no longer offers it."""
    with transaction(engine) as conn:
        live = conn.execute(
            text(
                "SELECT id FROM rail_connections WHERE org_id=:o AND rail_id=:r AND disconnected_at IS NULL "
                "FOR UPDATE"
            ),
            {"o": org_id, "r": rail_id},
        ).first()
        if live is None:
            raise ConnectionError_(f"{rail_id} is not connected", status=404, code="not_found")
        conn.execute(
            text(
                "UPDATE rail_connections SET credential=NULL, disconnected_by=:by, disconnected_at=:t "
                "WHERE org_id=:o AND id=:id"
            ),
            {"by": actor.id, "t": clock.now(), "o": org_id, "id": live.id},
        )
        conn.execute(
            text("UPDATE rails SET enabled=false WHERE org_id=:o AND id=:r"), {"o": org_id, "r": rail_id}
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="rail.disconnected",
            subject_id=rail_id,
            payload={"connection_id": str(live.id)},
        )
    return str(live.id)


def connections(conn: Connection, org_id: str) -> dict[str, Any]:
    """The live connection per rail (no credential), for the screen."""
    rows = conn.execute(
        text(
            "SELECT id, rail_id, method, scopes, credential_hint, connected_by, connected_at FROM "
            "rail_connections "
            "WHERE org_id=:o AND disconnected_at IS NULL"
        ),
        {"o": org_id},
    ).all()
    return {r.rail_id: r for r in rows}


def history(conn: Connection, org_id: str) -> list[Any]:
    return list(
        conn.execute(
            text(
                "SELECT id, rail_id, method, scopes, credential_hint, connected_by, connected_at, "
                "disconnected_by, "
                "disconnected_at FROM rail_connections WHERE org_id=:o ORDER BY connected_at DESC, "
                "id DESC LIMIT 50"
            ),
            {"o": org_id},
        ).all()
    )
