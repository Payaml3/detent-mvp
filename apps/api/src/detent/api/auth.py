"""API keys and scopes (spec/03 Authentication; the part of API-01 that slice S1 needs).

Keys look like ``sk_test_<random>``; only an HMAC-SHA256 of the key with the server pepper is stored.
Every key is issued to a named user, who is the actor in the audit log (G-08, D-23). ``sk_live_``
keys never reach this code: the request middleware rejects them first.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import Connection, text

from detent.clock import Clock
from detent.domain.ids import Prefix, new_id

TEST_PREFIX = "sk_test_"
SCOPES = frozenset({"read", "intents:create", "exceptions:approve", "admin"})


class AuthError(Exception):
    def __init__(self, status: int, type_: str, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.type, self.code, self.message = status, type_, code, message


@dataclass(frozen=True, slots=True)
class Principal:
    org_id: str
    key_id: str
    user_id: str
    role: str
    scopes: frozenset[str]
    mandate_id: str | None = None  # an agent's key, bound to one mandate (AGT-03)


def hash_key(key: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), key.encode(), hashlib.sha256).hexdigest()


def issue_key(
    conn: Connection,
    clock: Clock,
    org_id: str,
    user_id: str,
    scopes: list[str],
    pepper: str,
    *,
    mandate_id: str | None = None,
    key: str | None = None,
) -> str:
    unknown = set(scopes) - SCOPES
    if unknown:
        raise ValueError(f"unknown scopes: {sorted(unknown)}")
    if key is not None and not key.startswith(TEST_PREFIX):
        raise ValueError("keys must be sk_test_ keys")
    key = key or TEST_PREFIX + secrets.token_urlsafe(24)
    now = clock.now()
    conn.execute(
        text(
            "INSERT INTO api_keys (id, org_id, prefix, hash, scopes, user_id, mandate_id, created_at) "
            "VALUES (:id, :o, :p, :h, :s, :u, :m, :t)"
        ),
        {
            "id": new_id(Prefix.KEY, now),
            "o": org_id,
            "p": key[:12],
            "h": hash_key(key, pepper),
            "s": sorted(scopes),
            "u": user_id,
            "m": mandate_id,
            "t": now,
        },
    )
    return key


def authenticate(request: Request) -> Principal:
    rt = request.app.state.runtime
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise AuthError(401, "authentication", "missing_api_key", "Send Authorization: Bearer sk_test_...")
    pepper = rt.settings.api_key_pepper
    if pepper is None or not token.startswith(TEST_PREFIX):
        raise AuthError(401, "authentication", "invalid_api_key", "The API key is not valid.")
    digest = hash_key(token, pepper.get_secret_value())
    now = rt.clock.now()
    with rt.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT k.id, k.org_id, k.scopes, k.user_id, u.role, k.revoked_at, k.expires_at, "
                "k.mandate_id, o.expires_at AS org_expires_at "
                "FROM api_keys k JOIN users u ON u.org_id = k.org_id AND u.id = k.user_id "
                "JOIN organisations o ON o.id = k.org_id "
                "WHERE k.hash = :h"
            ).execution_options(cross_org="api key lookup: the key names the organisation"),
            {"h": digest},
        ).one_or_none()
    if row is None or row.revoked_at is not None or (row.expires_at is not None and row.expires_at <= now):
        raise AuthError(401, "authentication", "invalid_api_key", "The API key is not valid.")
    if row.org_expires_at is not None and row.org_expires_at <= now:  # DSH-03 (API side), found by atk-au-02
        raise AuthError(403, "permission", "organisation_expired", "This sandbox organisation has expired.")
    principal = Principal(row.org_id, row.id, row.user_id, row.role, frozenset(row.scopes), row.mandate_id)
    request.state.principal = principal  # read by the request log middleware (API-06)
    return principal


def require(principal: Principal, scope: str) -> None:
    if scope not in principal.scopes:
        raise AuthError(403, "permission", "insufficient_scope", f"This key lacks the {scope!r} scope.")
