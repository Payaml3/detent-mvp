"""WHK-01: webhook endpoints.

The signing secret (`whsec_...`) is returned once, when the endpoint is created. It is stored encrypted
with CREDENTIALS_ENCRYPTION_KEY (Fernet; C-19, D-12), because every delivery is signed with the
plaintext; `secret_hash` keeps a SHA-256 fingerprint. Without the key, endpoints cannot be created and
nothing is delivered (fail closed).
"""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
import socket
from typing import Any
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Connection, text

from detent.clock import Clock
from detent.domain.ids import Prefix, new_id
from detent.settings import Settings
from detent.webhooks.events import ALL_TYPES, EVENT_TYPES

SECRET_PREFIX = "whsec_"  # noqa: S105 - the prefix of generated secrets, not a secret
MAX_ENDPOINTS = 16
MAX_URL = 2048


class EndpointError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 422, param: str | None = None) -> None:
        super().__init__(message)
        self.code, self.status, self.param = code, status, param


def _fernet(settings: Settings) -> Fernet:
    key = settings.credentials_encryption_key
    if key is None:
        raise EndpointError(
            "webhooks_unavailable", "Webhooks are not configured on this instance.", status=503
        )
    try:
        return Fernet(key.get_secret_value().encode())
    except ValueError as exc:
        raise EndpointError(
            "webhooks_unavailable", "Webhooks are not configured on this instance.", status=503
        ) from exc


def decrypt_secret(settings: Settings, token: str) -> str:
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise EndpointError(
            "webhooks_unavailable", "The endpoint's secret cannot be read.", status=503
        ) from exc


# ------------------------------------------------------------------------------------------ URLs
def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not ip.is_global or ip.is_multicast


def check_url(url: str, settings: Settings, *, resolve: bool = False) -> str:
    """https only, no credentials in the URL, and never a private, loopback or link-local address
    (server-side request forgery). `WEBHOOK_ALLOW_PRIVATE_URLS` (dev and test only) lifts the last
    two rules for a local receiver. With `resolve`, the host's addresses are checked too (delivery)."""
    if len(url) > MAX_URL:
        raise EndpointError("invalid_url", "The URL is too long.", param="url")
    parts = urlsplit(url)
    allow_private = settings.webhook_allow_private_urls
    if parts.scheme != "https" and not (allow_private and parts.scheme == "http"):
        raise EndpointError("invalid_url", "Webhook URLs must use https://.", param="url")
    if not parts.hostname or parts.username or parts.password:
        raise EndpointError("invalid_url", "The URL needs a host and no user name or password.", param="url")
    if allow_private:
        return url
    host = parts.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and _blocked_ip(literal):
        raise EndpointError("invalid_url", "The URL points at a private or reserved address.", param="url")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise EndpointError("invalid_url", "The URL points at a private host name.", param="url")
    if resolve and literal is None:
        try:
            infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
        except OSError as exc:
            raise EndpointError("invalid_url", "The host name does not resolve.", param="url") from exc
        for info in infos:
            if _blocked_ip(ipaddress.ip_address(info[4][0])):
                raise EndpointError("invalid_url", "The host resolves to a private address.", param="url")
    return url


def check_types(types: list[str]) -> tuple[str, ...]:
    if not types:
        raise EndpointError("validation_error", 'Give at least one event type, or "*".', param="event_types")
    unknown = sorted(set(types) - set(EVENT_TYPES) - {ALL_TYPES})
    if unknown:
        raise EndpointError(
            "unknown_event_type", f"Unknown event types: {', '.join(unknown)}.", param="event_types"
        )
    return tuple(sorted(set(types)))


# ------------------------------------------------------------------------------------------ store
def endpoint_json(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "object": "webhook_endpoint",
        "url": row.url,
        "event_types": list(row.event_types),
        "description": row.description,
        "status": "enabled" if row.disabled_at is None else "disabled",
        "secret_fingerprint": (row.secret_hash or "")[:12] or None,
        "created": row.created_at.isoformat(),
    }


_COLS = "id, url, event_types, description, secret_hash, secret_encrypted, created_at, disabled_at"


def create(
    conn: Connection,
    clock: Clock,
    settings: Settings,
    *,
    org_id: str,
    url: str,
    event_types: list[str],
    description: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Create an endpoint. Returns its JSON and the plaintext secret, which is never shown again."""
    fernet = _fernet(settings)
    url = check_url(url.strip(), settings)
    types = check_types(event_types)
    if description is not None and len(description) > 200:
        raise EndpointError(
            "validation_error", "The description is longer than 200 characters.", param="description"
        )
    count = conn.execute(
        text("SELECT count(*) FROM webhook_endpoints WHERE org_id=:o AND disabled_at IS NULL"), {"o": org_id}
    ).scalar_one()
    if int(count) >= MAX_ENDPOINTS:
        raise EndpointError(
            "too_many_endpoints", f"An organisation can have at most {MAX_ENDPOINTS} endpoints.", status=409
        )
    now = clock.now()
    secret = SECRET_PREFIX + secrets.token_urlsafe(32)
    eid = new_id(Prefix.WHE, now)
    row = conn.execute(
        text(
            "INSERT INTO webhook_endpoints (id, org_id, url, event_types, description, secret_hash, "  # noqa: S608
            "secret_encrypted, created_at) VALUES (:id, :o, :u, :t, :d, :h, :e, :now) RETURNING " + _COLS
        ),
        {
            "id": eid,
            "o": org_id,
            "u": url,
            "t": list(types),
            "d": description,
            "h": hashlib.sha256(secret.encode()).hexdigest(),
            "e": fernet.encrypt(secret.encode()).decode(),
            "now": now,
        },
    ).one()
    return endpoint_json(row), secret


def get(conn: Connection, org_id: str, endpoint_id: str) -> Any:
    row = conn.execute(
        text(f"SELECT {_COLS} FROM webhook_endpoints WHERE org_id=:o AND id=:i"),  # noqa: S608
        {"o": org_id, "i": endpoint_id},
    ).one_or_none()
    if row is None:
        raise EndpointError("not_found", "No such webhook endpoint.", status=404, param="id")
    return row


def list_all(conn: Connection, org_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(f"SELECT {_COLS} FROM webhook_endpoints WHERE org_id=:o ORDER BY created_at, id"),  # noqa: S608
        {"o": org_id},
    ).all()
    return [endpoint_json(r) for r in rows]


def disable(conn: Connection, clock: Clock, org_id: str, endpoint_id: str) -> dict[str, Any]:
    get(conn, org_id, endpoint_id)
    row = conn.execute(
        text(
            "UPDATE webhook_endpoints SET disabled_at = coalesce(disabled_at, :now) "  # noqa: S608
            f"WHERE org_id=:o AND id=:i RETURNING {_COLS}"
        ),
        {"now": clock.now(), "o": org_id, "i": endpoint_id},
    ).one()
    return endpoint_json(row)
