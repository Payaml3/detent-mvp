"""The client: keys, versioning, idempotency keys and safe retries (SDK-01).

Retries happen only where they can't pay twice: on 429 and 503, and on connection errors that happen before
the API sees the request. A retried create sends the same `Idempotency-Key`, so the API returns the first
result instead of creating a second payment. A read timeout is never retried: the request may have arrived.
"""

from __future__ import annotations

import os
import random
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx

from dekernai._errors import APIConnectionError, APIError
from dekernai._generated import API_VERSION, Requester, Resources

__version__ = "0.1.0"
DEFAULT_BASE_URL = "http://localhost:8000"
RETRY_STATUSES = frozenset({429, 503})
MAX_BACKOFF_SECONDS = 30.0


class DekernAI(Resources):
    """A DekernAI API client.

    >>> client = DekernAI(api_key="sk_test_...", base_url="https://sandbox.api.example")
    >>> client.payment_intents.create({...})

    `api_key` and `base_url` default to `DEKERNAI_API_KEY` and `DEKERNAI_BASE_URL`. Live keys are refused:
    the API is a sandbox on test networks only.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        api_version: str = API_VERSION,
        max_retries: int = 2,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = api_key or os.environ.get("DEKERNAI_API_KEY")
        if not key:
            raise ValueError("pass api_key or set DEKERNAI_API_KEY")
        if key.startswith("sk_live_"):
            raise ValueError(
                "live keys are refused: DekernAI runs on test networks only (use an sk_test_ key)"
            )
        if max_retries < 0:
            raise ValueError("max_retries can't be negative")
        self.api_key = key
        self.base_url = (base_url or os.environ.get("DEKERNAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_version = api_version
        self.max_retries = max_retries
        self._sleep = sleep
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)
        requester: Requester = self
        self._init_resources(requester)

    # ------------------------------------------------------------------------------------------ lifecycle
    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> DekernAI:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------------------------------- requests
    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: dict[str, Any] | None = None,
        idempotent: bool = False,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "DekernAI-Version": self.api_version,
            "Accept": "application/json",
            "User-Agent": f"dekernai-python/{__version__}",
        }
        if idempotent:
            headers["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())  # the same key on every retry
        params = {k: _query_value(v) for k, v in (query or {}).items() if v is not None}
        url = self.base_url + path
        attempt = 0
        while True:
            try:
                response = self._http.request(method, url, headers=headers, params=params, json=body)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt >= self.max_retries:
                    raise APIConnectionError(f"could not reach {self.base_url}: {exc}") from exc
                self._sleep(_backoff(attempt, None))
                attempt += 1
                continue
            if response.status_code in RETRY_STATUSES and attempt < self.max_retries:
                self._sleep(_backoff(attempt, response.headers.get("Retry-After")))
                attempt += 1
                continue
            return _result(response)


def _query_value(v: Any) -> Any:
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


def _backoff(attempt: int, retry_after: str | None) -> float:
    if retry_after is not None:
        try:
            return min(max(float(retry_after), 0.0), MAX_BACKOFF_SECONDS)
        except ValueError:
            pass
    return float(min(0.5 * 2**attempt, MAX_BACKOFF_SECONDS) * (0.5 + random.random() / 2))  # noqa: S311


def _result(response: httpx.Response) -> Any:
    try:
        data = response.json() if response.content else None
    except ValueError:
        data = None
    if response.is_success:
        return data
    raise APIError(response.status_code, data if isinstance(data, dict) else None, dict(response.headers))
