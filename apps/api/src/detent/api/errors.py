"""The public error envelope (spec/03)."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi.responses import JSONResponse

ErrorType = Literal[
    "invalid_request",
    "authentication",
    "permission",
    "not_found",
    "conflict",
    "rate_limit",
    "quota",
    "internal",
]

log = logging.getLogger("detent.api.errors")
# Codes returned that are missing from the catalogue (API-02). The test session fails if any appear.
UNCATALOGUED: set[str] = set()


def error_response(
    status: int,
    type_: ErrorType,
    code: str,
    message: str,
    *,
    request_id: str | None,
    payment_id: str | None = None,
    param: str | None = None,
) -> JSONResponse:
    from detent.api.error_codes import BY_CODE  # deferred: error_codes imports ErrorType from here

    if code not in BY_CODE:
        UNCATALOGUED.add(code)
        log.error("uncatalogued error code %s", code)
    body = {
        "error": {
            "type": type_,
            "code": code,
            "message": message,
            "payment_id": payment_id,
            "request_id": request_id,
            "param": param,
        }
    }
    headers = {"Request-Id": request_id} if request_id else None
    return JSONResponse(body, status_code=status, headers=headers)
