"""Verify webhook deliveries (WHK-02).

`DekernAI-Signature: t=<unix seconds>,v1=<hex>` is an HMAC-SHA256, with your endpoint's signing secret,
over `"{t}.{raw body}"`. During a secret rotation a delivery carries one `v1=` per active secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from dekernai._errors import WebhookSignatureError

SIGNATURE_HEADER = "DekernAI-Signature"


def _parse(header: str) -> tuple[int, list[str]]:
    ts: int | None = None
    sigs: list[str] = []
    for part in header.split(","):
        key, sep, value = part.strip().partition("=")
        if not sep:
            raise WebhookSignatureError("malformed signature header")
        if key == "t":
            if ts is not None or not value.isdigit():
                raise WebhookSignatureError("malformed timestamp")
            ts = int(value)
        elif key == "v1":
            sigs.append(value)
    if ts is None or not sigs:
        raise WebhookSignatureError("the header needs t= and at least one v1=")
    return ts, sigs


def verify_webhook(
    secret: str, header: str | None, body: bytes | str, tolerance: int = 300, *, now: int | None = None
) -> dict[str, Any]:
    """Check a delivery and return its event. Raises `WebhookSignatureError`.

    Pass the raw request body, exactly as received: parsing and re-serialising it changes the bytes. A
    timestamp more than `tolerance` seconds away from now, in either direction, is refused against replays.
    """
    raw = body.encode() if isinstance(body, str) else body
    if not header:
        raise WebhookSignatureError("missing signature header")
    ts, sigs = _parse(header)
    current = int(time.time()) if now is None else now
    if abs(current - ts) > tolerance:
        raise WebhookSignatureError("timestamp outside the tolerance window")
    expected = hmac.new(secret.encode(), str(ts).encode() + b"." + raw, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise WebhookSignatureError("no signature matches")
    event: dict[str, Any] = json.loads(raw)
    return event
