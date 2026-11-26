"""Request ID, live-key rejection and request logging (FND-02, FND-08).

Pure ASGI-style HTTP middleware so it runs before routing and authentication.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import Response

from detent.api.errors import error_response
from detent.api.limits import (
    CURRENT_VERSION,
    IP_LIMIT_FACTOR,
    SUPPORTED_VERSIONS,
    VERSION_HEADER,
    LimitResult,
)
from detent.logging import request_id_var

log = logging.getLogger("detent.http")

LIVE_KEY_PREFIX = "sk_live_"


def new_request_id() -> str:
    return "req_" + secrets.token_hex(12)


_PAYMENT_ID = re.compile(r"/(pay_[A-Za-z0-9]+)")
_IDEM_MAX = 255


def record_request(request: Request, response: Response, rid: str, latency_ms: int) -> None:
    """API-06: one row per authenticated API call. Metadata only: no bodies, no query string, no keys.

    A logging failure never changes the API response.
    """
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return
    rt = request.app.state.runtime
    match = _PAYMENT_ID.search(request.url.path)
    idem = request.headers.get("idempotency-key")
    try:
        with rt.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO request_logs (org_id, key_id, method, path, status, latency_ms, "
                    "idempotency_key, payment_id, request_id, at) "
                    "VALUES (:org_id, :key_id, :method, :path, :status, :latency, :idem, :pay, :rid, :at)"
                ),
                {
                    "org_id": principal.org_id,
                    "key_id": principal.key_id,
                    "method": request.method,
                    "path": request.url.path[:500],
                    "status": response.status_code,
                    "latency": latency_ms,
                    "idem": idem[:_IDEM_MAX] if idem else None,
                    "pay": match.group(1) if match else None,
                    "rid": rid,
                    "at": rt.clock.now(),
                },
            )
    except Exception:
        log.exception("request log write failed")


def _uses_live_key(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() == "bearer" and token.strip().startswith(LIVE_KEY_PREFIX):
        return True
    # Basic auth or a stray header must not get a live key through either.
    return LIVE_KEY_PREFIX in auth


async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    rid = new_request_id()
    token = request_id_var.set(rid)
    # Monotonic duration for latency only; domain time always comes from the Clock.
    started = time.perf_counter()
    try:
        if _uses_live_key(request):
            response: Response = error_response(
                403,
                "permission",
                "live_mode_unavailable",
                "Live mode is not available. This sandbox uses test networks only; use an sk_test_ key.",
                request_id=rid,
            )
        else:
            limit: LimitResult | None = None
            version = request.headers.get(VERSION_HEADER)
            is_api = request.url.path.startswith("/v1")
            if is_api:
                limiter = getattr(request.app.state, "limiter", None)
                bearer = request.headers.get("authorization", "")
                if limiter is not None:
                    now = request.app.state.runtime.clock.now()
                    host = request.client.host if request.client else "unknown"
                    ip = limiter.hit(f"ip:{host}", now, limiter.limit * IP_LIMIT_FACTOR)
                    limit = limiter.hit(bearer, now, scope=host) if ip.allowed else ip
            if limit is not None and not limit.allowed:
                response = error_response(
                    429,
                    "rate_limit",
                    "rate_limited",
                    "Too many requests. Retry after the time given.",
                    request_id=rid,
                )
                response.headers["Retry-After"] = str(limit.reset_seconds)
            elif is_api and version is not None and version not in SUPPORTED_VERSIONS:
                supported = ", ".join(sorted(SUPPORTED_VERSIONS))
                response = error_response(
                    400,
                    "invalid_request",
                    "unknown_version",
                    f"Unknown {VERSION_HEADER} {version!r}. Supported: {supported}.",
                    request_id=rid,
                    param=VERSION_HEADER,
                )
            else:
                try:
                    response = await call_next(request)
                except Exception:  # fail closed with the public envelope, never a stack trace
                    log.exception("unhandled error")
                    response = error_response(
                        500,
                        "internal",
                        "internal_error",
                        "Something went wrong on our side.",
                        request_id=rid,
                    )
            if is_api:
                pinned = getattr(request.state, "api_version", None)
                response.headers[VERSION_HEADER] = version or pinned or CURRENT_VERSION
                if limit is not None:
                    response.headers["RateLimit-Limit"] = str(limit.limit)
                    response.headers["RateLimit-Remaining"] = str(limit.remaining)
                    response.headers["RateLimit-Reset"] = str(limit.reset_seconds)
            response.headers["Request-Id"] = rid
            if is_api:
                record_request(request, response, rid, round((time.perf_counter() - started) * 1000))
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response
    finally:
        request_id_var.reset(token)
