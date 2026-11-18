"""FND-08: request and payment context on log lines; secrets never logged."""

import json
import logging

import pytest
from conftest import FAKE_LIVE, FAKE_TEST
from detent.logging import JsonFormatter, Redactor, payment_context, redactor, request_id_var


def _format(msg: str, **extra: object) -> dict[str, object]:
    rec = logging.getLogRecordFactory()("t", logging.INFO, __file__, 1, msg, (), None)
    for k, v in extra.items():
        setattr(rec, k, v)
    out: dict[str, object] = json.loads(JsonFormatter().format(rec))
    return out


def test_context_ids_on_every_line() -> None:
    tok = request_id_var.set("req_abc")
    try:
        with payment_context("pay_123"):
            line = _format("hello")
    finally:
        request_id_var.reset(tok)
    assert line["request_id"] == "req_abc" and line["payment_id"] == "pay_123"
    assert "payment_id" not in _format("outside")


@pytest.mark.parametrize(
    "secret_text",
    [
        "key " + FAKE_TEST + "FAKE0KEY0FOR0TESTS0000 used",
        "live " + FAKE_LIVE + "abcdef123456 attempt",
        "Authorization: Bearer abc.def.ghi",
    ],
)
def test_keys_and_bearer_tokens_redacted(secret_text: str) -> None:
    line = json.dumps(_format(secret_text))
    assert (
        FAKE_TEST + "FAKE0KEY" not in line and FAKE_LIVE + "abcdef" not in line and "abc.def.ghi" not in line
    )
    assert "[REDACTED]" in line


def test_configured_secret_values_redacted_in_message_and_extra() -> None:
    redactor.add("super-secret-pepper-value")
    line = json.dumps(_format("pepper super-secret-pepper-value", detail={"x": "super-secret-pepper-value"}))
    assert "super-secret-pepper-value" not in line


def test_sensitive_keys_in_dicts_redacted() -> None:
    r = Redactor()
    assert r.scrub({"Authorization": "x", "password": "y", "ok": "z"}) == {
        "Authorization": "[REDACTED]",
        "password": "[REDACTED]",
        "ok": "z",
    }
