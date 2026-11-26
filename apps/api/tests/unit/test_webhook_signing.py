"""WHK-02: `DekernAI-Signature: t=<unix>,v1=<hex>` over "{t}.{raw body}", with a 5-minute window."""

from __future__ import annotations

import hashlib
import hmac

import pytest
from detent.webhooks.signing import SignatureError, compute, sign, verify

SECRET = "whsec_" + "test-vector-secret"
BODY = b'{"id":"evt_1","type":"payment_intent.unknown"}'
T = 1764756000

# The fixed vector the docs snippets in every language are tested against (DOC-05).
VECTOR = hmac.new(SECRET.encode(), f"{T}.".encode() + BODY, hashlib.sha256).hexdigest()


def test_the_signature_is_hmac_sha256_of_timestamp_dot_body() -> None:
    assert compute(SECRET, T, BODY) == VECTOR
    assert sign(SECRET, T, BODY) == f"t={T},v1={VECTOR}"


def test_a_good_signature_verifies_inside_the_window() -> None:
    header = sign(SECRET, T, BODY)
    assert verify(SECRET, header, BODY, now=T) == T
    assert verify(SECRET, header, BODY, now=T + 300) == T
    assert verify(SECRET, header, BODY, now=T - 300) == T


@pytest.mark.parametrize("now", [T + 301, T - 301, T + 86_400])
def test_stale_or_future_timestamps_are_rejected(now: int) -> None:
    with pytest.raises(SignatureError, match="tolerance"):
        verify(SECRET, sign(SECRET, T, BODY), BODY, now=now)


def test_a_changed_body_or_wrong_secret_is_rejected() -> None:
    header = sign(SECRET, T, BODY)
    with pytest.raises(SignatureError, match="does not match"):
        verify(SECRET, header, BODY + b" ", now=T)
    with pytest.raises(SignatureError, match="does not match"):
        verify(SECRET + "x", header, BODY, now=T)


def test_a_changed_timestamp_is_rejected() -> None:
    forged = f"t={T + 1},v1={VECTOR}"
    with pytest.raises(SignatureError, match="does not match"):
        verify(SECRET, forged, BODY, now=T)


@pytest.mark.parametrize("header", ["", "v1=abc", f"t={T}", "t=abc,v1=00", "garbage", f"t={T},t={T},v1=00"])
def test_malformed_headers_are_rejected(header: str) -> None:
    with pytest.raises(SignatureError):
        verify(SECRET, header, BODY, now=T)


def test_any_of_several_signatures_may_match() -> None:
    header = f"t={T},v1={'0' * 64},v1={VECTOR}"
    assert verify(SECRET, header, BODY, now=T) == T
