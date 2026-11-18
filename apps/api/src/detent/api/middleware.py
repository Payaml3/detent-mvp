"""Request ID, live-key rejection and request logging (FND-02, FND-08).

Pure ASGI-style HTTP middleware so it runs before routing and authentication.
"""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from detent.api.errors import error_response
from detent.logging import request_id_var

log = logging.getLogger("detent.http")

LIVE_KEY_PREFIX = "sk_live_"


def new_request_id() -> str:
    return "req_" + secrets.token_hex(12)


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
            response = await call_next(request)
            response.headers["Request-Id"] = rid
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
