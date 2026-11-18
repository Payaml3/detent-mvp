"""Structured JSON logs with request and payment context (FND-08).

- Every line carries ``request_id`` and ``payment_id`` when they are in context.
- Secrets never reach a log line: a filter replaces every configured secret value, API keys
  (``sk_test_``/``sk_live_``) and ``Authorization`` header values with ``[REDACTED]``. Invoice bodies
  and other untrusted text must not be passed to the logger at all; log their IDs instead.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
payment_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("payment_id", default=None)

REDACTED = "[REDACTED]"
_KEY_RE = re.compile(r"\bsk_(?:test|live)_[A-Za-z0-9]{4,}")
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")

_STD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


class Redactor:
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets: list[str] = sorted({s for s in secrets if s}, key=len, reverse=True)

    def add(self, *secrets: str) -> None:
        self._secrets = sorted({*self._secrets, *(s for s in secrets if s)}, key=len, reverse=True)

    def scrub(self, value: Any) -> Any:
        if isinstance(value, str):
            for s in self._secrets:
                value = value.replace(s, REDACTED)
            value = _KEY_RE.sub(REDACTED, value)
            return _BEARER_RE.sub(r"\1 " + REDACTED, value)
        if isinstance(value, dict):
            return {
                k: (
                    REDACTED
                    if k.lower() in {"authorization", "password", "secret", "private_key"}
                    else self.scrub(v)
                )
                for k, v in value.items()
            }
        if isinstance(value, list | tuple):
            return [self.scrub(v) for v in value]
        return value


redactor = Redactor()

_base_factory = logging.getLogRecordFactory()


def _record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    """Stamp the request and payment IDs on each record when it is created, so they survive
    formatting later or on another thread."""
    record = _base_factory(*args, **kwargs)
    record.request_id = request_id_var.get()
    record.payment_id = payment_id_var.get()
    return record


if getattr(logging.getLogRecordFactory(), "__name__", "") != "_record_factory":
    logging.setLogRecordFactory(_record_factory)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Log timestamps are operational metadata, not domain time, so they use the record's own
        # creation time rather than the Clock.
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in _STD_ATTRS and not k.startswith("_") and v is not None:
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(redactor.scrub(out), default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid, pid = getattr(record, "request_id", None), getattr(record, "payment_id", None)
        ctx = " ".join(f"{k}={v}" for k, v in (("request_id", rid), ("payment_id", pid)) if v)
        line = f"{record.levelname:<5} {record.name}: {record.getMessage()}" + (f" [{ctx}]" if ctx else "")
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return str(redactor.scrub(line))


def configure(level: str = "INFO", json_output: bool = True, secrets: Iterable[str] = ()) -> None:
    redactor.add(*secrets)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Uvicorn's access log would duplicate our request log line, and it prints raw query strings.
    logging.getLogger("uvicorn.access").disabled = True


@contextmanager
def payment_context(payment_id: str | None) -> Iterator[None]:
    token = payment_id_var.set(payment_id)
    try:
        yield
    finally:
        payment_id_var.reset(token)
