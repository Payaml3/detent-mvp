"""FND-02 and FND-08 over HTTP."""

from __future__ import annotations

import json
import logging

import pytest
from conftest import FAKE_LIVE, FAKE_TEST
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db


def test_healthz_reports_database(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    # FND-07 (S9): the database and both demo chain RPCs are each reported; unconfigured chains don't fail it.
    assert r.json()["checks"] == {
        "database": "ok",
        "base-sepolia": "not_configured",
        "eth-sepolia": "not_configured",
    }


def test_every_response_has_a_request_id(client: TestClient) -> None:
    a, b = client.get("/healthz"), client.get("/console/login")
    assert a.headers["Request-Id"].startswith("req_")
    assert a.headers["Request-Id"] != b.headers["Request-Id"]


@pytest.mark.parametrize("path", ["/healthz", "/console/login", "/v1/payment_intents", "/nowhere"])
def test_live_keys_are_always_rejected(client: TestClient, path: str) -> None:
    r = client.get(path, headers={"Authorization": "Bearer " + FAKE_LIVE + "FAKE0KEY0FOR0TESTS0000"})
    assert r.status_code == 403
    err = r.json()["error"]
    assert err["code"] == "live_mode_unavailable" and err["type"] == "permission"
    assert err["request_id"] == r.headers["Request-Id"]


def test_live_key_rejected_on_post_too(client: TestClient) -> None:
    r = client.post(
        "/console/login",
        data={"password": "x"},
        headers={"Authorization": "bearer " + FAKE_LIVE + "abc123"},
    )
    assert r.status_code == 403


def test_test_keys_pass_the_live_mode_guard(client: TestClient) -> None:
    r = client.get("/healthz", headers={"Authorization": "Bearer " + FAKE_TEST + "abc123"})
    assert r.status_code == 200


def test_request_logs_carry_request_id_and_never_keys(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    from detent.logging import JsonFormatter

    caplog.set_level(logging.INFO)
    client.get(
        "/healthz?token=" + FAKE_TEST + "SECRETVALUE123",
        headers={"Authorization": "Bearer " + FAKE_TEST + "SECRETVALUE123"},
    )
    fmt = JsonFormatter()
    lines = [fmt.format(r) for r in caplog.records]
    http = [json.loads(fmt.format(r)) for r in caplog.records if r.name == "detent.http"]
    assert http
    rec = http[-1]
    assert rec["request_id"].startswith("req_") and rec["status"] == 200 and rec["path"] == "/healthz"
    # Every line, including third-party loggers that print the raw URL, is scrubbed.
    assert all("SECRETVALUE123" not in line for line in lines)


def test_unknown_version_is_400_and_known_is_echoed(client: TestClient) -> None:
    bad = client.get("/v1/payment_intents", headers={"DekernAI-Version": "2020-01-01"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "unknown_version"
    ok = client.get("/v1/payment_intents", headers={"DekernAI-Version": "2026-12-01"})
    assert ok.headers["DekernAI-Version"] == "2026-12-01"


def test_v1_responses_carry_rate_limit_headers_and_429(client: TestClient) -> None:
    from detent.api.limits import RateLimiter

    r = client.get("/v1/payment_intents")
    assert {"ratelimit-limit", "ratelimit-remaining", "ratelimit-reset"} <= set(r.headers)
    client.app.state.limiter = RateLimiter(limit=1)  # type: ignore[attr-defined]
    client.get("/v1/payment_intents")
    r = client.get("/v1/payment_intents")
    assert r.status_code == 429 and r.json()["error"]["type"] == "rate_limit"
    assert int(r.headers["Retry-After"]) > 0


def test_errors_use_the_envelope_for_404_and_405(client: TestClient) -> None:
    for r, code in (
        (client.get("/v1/nowhere"), "not_found"),
        (client.delete("/healthz"), "method_not_allowed"),
    ):
        err = r.json()["error"]
        assert err["code"] == code and err["request_id"] == r.headers["Request-Id"]


def test_rotating_junk_tokens_still_hit_the_client_address_limit(client: TestClient) -> None:
    from detent.api.limits import IP_LIMIT_FACTOR, RateLimiter

    client.app.state.limiter = RateLimiter(limit=1)  # type: ignore[attr-defined]
    codes = [
        client.get("/v1/payment_intents", headers={"Authorization": f"Bearer junk{i}"}).status_code
        for i in range(IP_LIMIT_FACTOR + 2)
    ]
    assert codes[-1] == 429


def test_the_rate_limit_comes_from_settings(client: TestClient) -> None:
    assert client.app.state.limiter.limit == 120  # type: ignore[attr-defined]
