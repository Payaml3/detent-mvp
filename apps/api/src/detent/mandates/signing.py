"""Mandate signatures (MND-01, spec/05).

HMAC-SHA256 over the canonical JSON of the mandate without its ``signature`` field: keys sorted, no
whitespace, UTF-8. The key is the platform's mandate key (settings in the prototype). Verifying needs no
model call and no network.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from pydantic import SecretStr


def canonical(doc: dict[str, Any]) -> bytes:
    body = {k: v for k, v in doc.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(doc: dict[str, Any], key: SecretStr) -> str:
    mac = hmac.new(key.get_secret_value().encode(), canonical(doc), hashlib.sha256).digest()
    return base64.b64encode(mac).decode()


def verify_signature(doc: dict[str, Any], key: SecretStr) -> bool:
    sig = doc.get("signature") or {}
    if sig.get("alg") != "HS256" or not isinstance(sig.get("value"), str):
        return False
    return hmac.compare_digest(sig["value"], sign(doc, key))
