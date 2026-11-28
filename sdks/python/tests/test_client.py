"""SDK-01: the client's own behaviour, against a fake transport (no server)."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from dekernai import (
    API_VERSION,
    APIConnectionError,
    APIError,
    DekernAI,
    WebhookSignatureError,
    verify_webhook,
)

Handler = Callable[[httpx.Request], httpx.Response]


def client(handler: Handler, **kw: Any) -> tuple[DekernAI, list[float]]:
    slept: list[float] = []
    c = DekernAI(
        "sk_test_abc",
        base_url="https://sandbox.example.test/",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=slept.append,
        **kw,
    )
    return c, slept


BODY: Any = {
    "kind": "payout",
    "source": "platform",
    "counterparty_id": "cpt_lumen",
    "destination": {"kind": "evm_wallet", "network": "base-sepolia", "destination_id": "dst_lumen_base"},
    "amount": {"amount": "50.00", "currency": "USDC"},
}


def test_live_keys_and_missing_keys_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="live keys are refused"):
        DekernAI("sk_live_abc")
    monkeypatch.delenv("DEKERNAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DEKERNAI_API_KEY"):
        DekernAI()
    monkeypatch.setenv("DEKERNAI_API_KEY", "sk_test_env")
    monkeypatch.setenv("DEKERNAI_BASE_URL", "https://env.example.test")
    c = DekernAI()
    assert (c.api_key, c.base_url) == ("sk_test_env", "https://env.example.test")


def test_requests_carry_the_key_the_version_and_an_idempotency_key_on_creates() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(201, json={"id": "pay_1", "status": "SHADOWED"})

    c, _ = client(handler)
    assert c.payment_intents.create(BODY)["id"] == "pay_1"
    c.payment_intents.create(BODY, idempotency_key="my-key")
    c.payment_intents.retrieve("pay_1/x")
    first, second, get = seen
    assert str(first.url) == "https://sandbox.example.test/v1/payment_intents"
    assert first.headers["Authorization"] == "Bearer sk_test_abc"
    assert first.headers["DekernAI-Version"] == API_VERSION
    assert len(first.headers["Idempotency-Key"]) == 36 and second.headers["Idempotency-Key"] == "my-key"
    assert json.loads(first.content) == BODY
    assert "Idempotency-Key" not in get.headers and get.url.raw_path == b"/v1/payment_intents/pay_1%2Fx"


def test_query_parameters_skip_none_and_keep_their_api_names() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"data": [], "has_more": False, "next_cursor": None})

    c, _ = client(handler)
    c.payment_intents.list(status="UNKNOWN", created_gte="2026-12-01T00:00:00Z", limit=5)
    c.exceptions.list(overdue=True)
    assert dict(seen[0].url.params) == {
        "status": "UNKNOWN",
        "created[gte]": "2026-12-01T00:00:00Z",
        "limit": "5",
    }
    assert dict(seen[1].url.params) == {"overdue": "true"}


@pytest.mark.parametrize("status", [429, 503])
def test_429_and_503_are_retried_with_the_same_idempotency_key(status: int) -> None:
    keys: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        keys.append(req.headers["Idempotency-Key"])
        if len(keys) < 3:
            return httpx.Response(status, headers={"Retry-After": "2"}, json={"error": {"code": "busy"}})
        return httpx.Response(201, json={"id": "pay_1"})

    c, slept = client(handler)
    assert c.payment_intents.create(BODY)["id"] == "pay_1"
    assert len(keys) == 3 and len(set(keys)) == 1
    assert slept == [2.0, 2.0]  # Retry-After is honoured


def test_retries_stop_after_max_retries_and_raise_the_api_error() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = {
            "error": {"type": "rate_limit", "code": "rate_limited", "message": "slow down", "request_id": "r"}
        }
        return httpx.Response(429, json=body)

    c, slept = client(handler, max_retries=1)
    with pytest.raises(APIError) as err:
        c.payment_intents.create(BODY)
    assert calls == 2 and len(slept) == 1
    assert (err.value.status, err.value.code, err.value.request_id) == (429, "rate_limited", "r")


@pytest.mark.parametrize("status", [400, 409, 422, 500, 502])
def test_other_errors_are_never_retried(status: int) -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status, json={"error": {"type": "x", "code": "y", "message": "no", "param": "amount"}}
        )

    c, _ = client(handler)
    with pytest.raises(APIError) as err:
        c.payment_intents.create(BODY)
    assert calls == 1 and err.value.param == "amount"


def test_connection_errors_before_the_request_arrives_are_retried_and_read_timeouts_are_not() -> None:
    calls: list[str] = []

    def refused(req: httpx.Request) -> httpx.Response:
        calls.append(req.headers["Idempotency-Key"])
        if len(calls) == 1:
            raise httpx.ConnectError("refused", request=req)
        return httpx.Response(201, json={"id": "pay_1"})

    c, _ = client(refused)
    assert c.payment_intents.create(BODY)["id"] == "pay_1" and len(set(calls)) == 1 and len(calls) == 2

    def always(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    c, slept = client(always)
    with pytest.raises(APIConnectionError):
        c.kill_switch.engage()
    assert len(slept) == 2

    reads = 0

    def read_timeout(req: httpx.Request) -> httpx.Response:
        nonlocal reads
        reads += 1
        raise httpx.ReadTimeout("no answer", request=req)

    c, _ = client(read_timeout)
    with pytest.raises(httpx.ReadTimeout):
        c.payment_intents.create(BODY)
    assert reads == 1  # the request may have arrived: never resent


def test_every_api_operation_has_a_method() -> None:
    from pathlib import Path

    spec = json.loads((Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.json").read_text())
    ops = sum(
        1 for item in spec["paths"].values() for m in item if m in {"get", "post", "put", "patch", "delete"}
    )
    c, _ = client(lambda r: httpx.Response(200, json={}))
    resources = [v for k, v in vars(c).items() if not k.startswith("_") and hasattr(v, "_client")]
    methods = [n for r in resources for n in dir(r) if not n.startswith("_")]
    assert len(methods) == ops


# --------------------------------------------------------------------------------------------- webhooks
def _sign(secret: str, ts: int, body: bytes) -> str:
    return "v1=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


def test_verify_webhook_returns_the_event_and_refuses_bad_signatures() -> None:
    body = b'{"id":"evt_1","type":"payment_intent.confirmed"}'
    header = f"t=1764756000,{_sign('whsec_a', 1764756000, body)}"
    assert verify_webhook("whsec_a", header, body, now=1764756100)["id"] == "evt_1"
    rotated = f"t=1764756000,{_sign('whsec_old', 1764756000, body)},{_sign('whsec_a', 1764756000, body)}"
    assert (
        verify_webhook("whsec_a", rotated, body.decode(), now=1764756000)["type"]
        == "payment_intent.confirmed"
    )
    for bad, now in [
        (header, 1764756301),  # too old
        (header.replace("t=1764756000", "t=1764756001"), 1764756000),  # timestamp changed
        ("v1=abc", 1764756000),  # no timestamp
        ("", 1764756000),
    ]:
        with pytest.raises(WebhookSignatureError):
            verify_webhook("whsec_a", bad, body, now=now)
    with pytest.raises(WebhookSignatureError):
        verify_webhook("whsec_a", header, body + b" ", now=1764756000)  # the body changed


def test_user_accounts_register_with_put_and_no_idempotency_key() -> None:  # USR-03
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"object": "user_account", "user_account_ref": "u-1"})

    c, _ = client(handler)
    body: Any = {
        "user_verified": True,
        "destination": {"kind": "evm_wallet", "network": "base-sepolia", "address": "0x" + "1a" * 20},
    }
    assert c.user_accounts.register("u-1", body)["user_account_ref"] == "u-1"
    c.user_accounts.retrieve("u-1")
    put, get = seen
    assert put.method == "PUT" and put.url.raw_path == b"/v1/user_accounts/u-1"
    assert json.loads(put.content) == body and get.method == "GET"
