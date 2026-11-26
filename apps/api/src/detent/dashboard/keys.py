"""The keys page's service (DSH-04; spec/08 "Keys").

Only `sk_test_` keys exist (invariant 14). A key's secret is returned once, by `create_key` or `roll_key`,
and only its hash is stored. Rolling issues a new key with the same owner, scopes and name and keeps the old
one working for an overlap; revoking is immediate. Every change is audited in the organisation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, text

from detent.api.auth import SCOPES, hash_key, issue_key
from detent.audit.log import append
from detent.clock import Clock
from detent.dashboard.access import AccessError, Member, _require
from detent.settings import Settings

# The order the scopes are offered in, with what each lets a key do.
SCOPE_TEXT: dict[str, str] = {
    "read": "Read payments, exceptions, logs and events",
    "intents:create": "Create payment intents and decisions",
    "exceptions:approve": "Approve or reject exceptions (the member's role still applies)",
    "admin": "Manage webhook endpoints and the kill switch",
}
assert set(SCOPE_TEXT) == SCOPES
MAX_OVERLAP_HOURS = 168


@dataclass(frozen=True, slots=True)
class KeyView:
    id: str
    name: str | None
    prefix: str
    scopes: list[str]
    owner: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    rolled_to: str | None
    agent: bool

    def state(self, now: datetime) -> str:
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at is not None and self.expires_at <= now:
            return "expired"
        if self.rolled_to is not None:
            return "rolling"
        return "active"


def _pepper(settings: Settings) -> str:
    if settings.api_key_pepper is None:
        raise AccessError(
            "not_configured", "Keys are not configured on this instance (no key pepper).", status=503
        )
    return settings.api_key_pepper.get_secret_value()


def _scopes(scopes: list[str]) -> list[str]:
    chosen = sorted(set(scopes))
    if not chosen:
        raise AccessError("validation_error", "Choose at least one scope.")
    if set(chosen) - SCOPES:
        raise AccessError("validation_error", "Choose scopes from the list.")
    return chosen


def _name(name: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 80:
        raise AccessError("validation_error", "Give the key a name of 1 to 80 characters.")
    return name


def list_keys(conn: Connection, org_id: str) -> list[KeyView]:
    rows = conn.execute(
        text(
            "SELECT k.id, k.name, k.prefix, k.scopes, k.created_at, k.last_used_at, k.expires_at, "
            "k.revoked_at, k.rolled_to, k.mandate_id, u.display_name FROM api_keys k "
            "JOIN users u ON u.org_id = k.org_id AND u.id = k.user_id "
            "WHERE k.org_id=:o ORDER BY k.created_at DESC, k.id DESC"
        ),
        {"o": org_id},
    ).all()
    return [
        KeyView(
            r.id,
            r.name,
            r.prefix,
            list(r.scopes),
            r.display_name,
            r.created_at,
            r.last_used_at,
            r.expires_at,
            r.revoked_at,
            r.rolled_to,
            r.mandate_id is not None,
        )
        for r in rows
    ]


def _key_id(conn: Connection, org_id: str, secret: str, pepper: str) -> str:
    return str(
        conn.execute(
            text("SELECT id FROM api_keys WHERE org_id=:o AND hash=:h"),
            {"o": org_id, "h": hash_key(secret, pepper)},
        ).scalar_one()
    )


def create_key(
    conn: Connection, clock: Clock, settings: Settings, *, by: Member, name: str, scopes: list[str]
) -> tuple[str, str]:
    """A new key owned by the member. Returns (key id, secret); the secret is never shown again."""
    _require(by, "keys.manage")
    pepper, name, chosen = _pepper(settings), _name(name), _scopes(scopes)
    secret = issue_key(conn, clock, by.org_id, by.id, chosen, pepper)
    kid = _key_id(conn, by.org_id, secret, pepper)
    conn.execute(
        text("UPDATE api_keys SET name=:n, created_by=:b WHERE org_id=:o AND id=:i"),
        {"n": name, "b": by.id, "o": by.org_id, "i": kid},
    )
    append(
        conn,
        clock,
        org_id=by.org_id,
        actor=by.actor,
        kind="api_key.created",
        subject_id=kid,
        payload={"name": name, "scopes": chosen, "prefix": secret[:12]},
    )
    return kid, secret


def _load(conn: Connection, org_id: str, key_id: str) -> Any:
    row = conn.execute(
        text(
            "SELECT id, name, scopes, user_id, mandate_id, revoked_at, expires_at, rolled_to FROM api_keys "
            "WHERE org_id=:o AND id=:i FOR UPDATE"
        ),
        {"o": org_id, "i": key_id},
    ).one_or_none()
    if row is None:
        raise AccessError("not_found", "No such key.", status=404)
    return row


def roll_key(
    conn: Connection, clock: Clock, settings: Settings, *, by: Member, key_id: str, overlap_hours: int
) -> tuple[str, str]:
    """A new key replacing `key_id`, which keeps working for `overlap_hours` (0 ends it now)."""
    _require(by, "keys.manage")
    if not 0 <= overlap_hours <= MAX_OVERLAP_HOURS:
        raise AccessError("validation_error", f"The overlap is 0 to {MAX_OVERLAP_HOURS} hours.")
    pepper = _pepper(settings)
    old = _load(conn, by.org_id, key_id)
    now = clock.now()
    if old.revoked_at is not None or (old.expires_at is not None and old.expires_at <= now):
        raise AccessError("key_inactive", "This key is revoked or expired; create a new one.", status=409)
    if old.rolled_to is not None:
        raise AccessError(
            "key_rolled", "This key was already rolled; roll its replacement instead.", status=409
        )
    secret = issue_key(
        conn, clock, by.org_id, old.user_id, list(old.scopes), pepper, mandate_id=old.mandate_id
    )
    new_id_ = _key_id(conn, by.org_id, secret, pepper)
    ends = now + timedelta(hours=overlap_hours)
    if old.expires_at is not None and old.expires_at < ends:
        ends = old.expires_at
    conn.execute(
        text("UPDATE api_keys SET name=:n, created_by=:b, rolled_from=:f WHERE org_id=:o AND id=:i"),
        {"n": old.name, "b": by.id, "f": key_id, "o": by.org_id, "i": new_id_},
    )
    conn.execute(
        text("UPDATE api_keys SET expires_at=:e, rolled_to=:t WHERE org_id=:o AND id=:i"),
        {"e": ends, "t": new_id_, "o": by.org_id, "i": key_id},
    )
    append(
        conn,
        clock,
        org_id=by.org_id,
        actor=by.actor,
        kind="api_key.rolled",
        subject_id=key_id,
        payload={
            "new_key_id": new_id_,
            "old_key_expires_at": ends.isoformat(),
            "overlap_hours": overlap_hours,
        },
    )
    return new_id_, secret


def revoke_key(conn: Connection, clock: Clock, *, by: Member, key_id: str) -> None:
    """Revoked keys stop at once: every API call reads `revoked_at`."""
    _require(by, "keys.manage")
    old = _load(conn, by.org_id, key_id)
    if old.revoked_at is not None:
        return
    conn.execute(
        text("UPDATE api_keys SET revoked_at=:now WHERE org_id=:o AND id=:i"),
        {"now": clock.now(), "o": by.org_id, "i": key_id},
    )
    append(
        conn, clock, org_id=by.org_id, actor=by.actor, kind="api_key.revoked", subject_id=key_id, payload={}
    )
