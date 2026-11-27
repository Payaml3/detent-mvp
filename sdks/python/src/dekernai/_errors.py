"""The errors the SDK raises."""

from __future__ import annotations

from typing import Any


class DekernAIError(Exception):
    """Base class for every error the SDK raises."""


class APIConnectionError(DekernAIError):
    """The request never reached the API (DNS, refused connection, connect timeout), after every retry."""


class APIError(DekernAIError):
    """The API answered with an error. Its fields come from the error body (see the error codes page)."""

    def __init__(
        self, status: int, body: dict[str, Any] | None, headers: dict[str, str] | None = None
    ) -> None:
        err = (body or {}).get("error") or {}
        self.status = status
        self.type: str | None = err.get("type")
        self.code: str | None = err.get("code")
        self.message: str = err.get("message") or f"HTTP {status}"
        self.param: str | None = err.get("param")
        self.payment_id: str | None = err.get("payment_id")
        self.request_id: str | None = err.get("request_id")
        self.body = body
        self.headers = headers or {}
        super().__init__(f"{status} {self.code or self.type or 'error'}: {self.message}")


class WebhookSignatureError(DekernAIError):
    """A webhook delivery's signature is missing, malformed, wrong or too old."""
