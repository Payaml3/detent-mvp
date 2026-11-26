"""WHK-02: `DekernAI-Signature: t=<unix>,v1=<hex>`, an HMAC-SHA256 over "{t}.{raw body}".

Pure functions, no I/O. The docs snippets (DOC-05) implement the same `verify` in every docs language
and are tested against the vectors in `tests/unit/test_webhook_signing.py`.
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_HEADER = "DekernAI-Signature"
TOLERANCE_SECONDS = 300


class SignatureError(ValueError):
    """The signature header is missing, malformed, wrong or outside the time window."""


def compute(secret: str, timestamp: int, body: bytes) -> str:
    signed = str(timestamp).encode() + b"." + body
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """The header value for one delivery."""
    return f"t={timestamp},v1={compute(secret, timestamp, body)}"


def _parse(header: str) -> tuple[int, list[str]]:
    ts: int | None = None
    sigs: list[str] = []
    for part in header.split(","):
        key, sep, value = part.strip().partition("=")
        if not sep:
            raise SignatureError("malformed signature header")
        if key == "t":
            if ts is not None or not value.isdigit():
                raise SignatureError("malformed timestamp")
            ts = int(value)
        elif key == "v1":
            sigs.append(value)
    if ts is None or not sigs:
        raise SignatureError("the header needs t= and at least one v1=")
    return ts, sigs


def verify(secret: str, header: str, body: bytes, *, now: int, tolerance: int = TOLERANCE_SECONDS) -> int:
    """Check a delivery. Returns its timestamp, or raises SignatureError.

    Accepts any of several `v1=` values (secret rotation sends one per active secret). Rejects a
    timestamp more than `tolerance` seconds from `now`, in either direction, against replays.
    """
    if not header:
        raise SignatureError("missing signature header")
    ts, sigs = _parse(header)
    if abs(now - ts) > tolerance:
        raise SignatureError("timestamp outside the tolerance window")
    expected = compute(secret, ts, body)
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise SignatureError("signature does not match")
    return ts
