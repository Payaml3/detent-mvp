"""The public error envelope (spec/03)."""

from __future__ import annotations

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
