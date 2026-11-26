"""/v1 routes for webhooks (WHK-01 to WHK-03), events (API-07) and exceptions (EXC-08)."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from detent.api.auth import Principal, authenticate, require
from detent.api.errors import ErrorType, error_response
from detent.audit.log import Actor, append
from detent.intents.service import IdempotencyConflict
from detent.logging import request_id_var
from detent.views.cases import case_detail, list_cases
from detent.webhooks import delivery, endpoints
from detent.webhooks.endpoints import EndpointError
from detent.webhooks.events import EVENT_TYPES, TEST_EVENT_TYPE

router = APIRouter(prefix="/v1")
Auth = Annotated[Principal, Depends(authenticate)]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=255)]
_KINDS: dict[int, ErrorType] = {
    403: "permission",
    404: "not_found",
    409: "conflict",
    422: "invalid_request",
    503: "internal",
}


def _rid() -> str | None:
    return request_id_var.get()


def _endpoint_error(exc: EndpointError) -> JSONResponse:
    return error_response(
        exc.status,
        _KINDS.get(exc.status, "invalid_request"),
        exc.code,
        str(exc),
        request_id=_rid(),
        param=exc.param,
    )


def _no_key() -> JSONResponse:
    return error_response(
        422,
        "invalid_request",
        "validation_error",
        "The Idempotency-Key header is required.",
        request_id=_rid(),
        param="Idempotency-Key",
    )


def _page(data: list[dict[str, Any]], more: bool) -> JSONResponse:
    return JSONResponse(
        {"data": data, "has_more": more, "next_cursor": data[-1]["id"] if more and data else None}
    )


# ------------------------------------------------------------------------------------- endpoints
class EndpointIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=endpoints.MAX_URL)
    event_types: list[str] = Field(min_length=1, max_length=len(EVENT_TYPES) + 1)
    description: str | None = Field(default=None, max_length=200)


def _claim(conn: Connection, org_id: str, key: str, rhash: str, now: Any) -> dict[str, Any] | None:
    """Idempotency for creates: the first call claims the key; a repeat with the same body replays."""
    inserted = conn.execute(
        text(
            "INSERT INTO idempotency_records (org_id, key, request_hash, response, created_at) "
            "VALUES (:o, :k, :h, '{}'::jsonb, :t) ON CONFLICT (org_id, key) DO NOTHING RETURNING key"
        ),
        {"o": org_id, "k": key, "h": rhash, "t": now},
    ).scalar_one_or_none()
    if inserted is not None:
        return None
    rec = conn.execute(
        text("SELECT request_hash, response FROM idempotency_records WHERE org_id=:o AND key=:k"),
        {"o": org_id, "k": key},
    ).one()
    if rec.request_hash != rhash:
        raise IdempotencyConflict(key)
    return dict(rec.response)


@router.post("/webhook_endpoints", status_code=201)
def create_endpoint(
    request: Request, body: EndpointIn, principal: Auth, idempotency_key: IdemKey = None
) -> Response:
    """WHK-01. The signing secret is in this response only. A replay of the same request returns the
    endpoint with `secret: null`: the secret is never stored where it could be shown again."""
    require(principal, "admin")
    if not idempotency_key:
        return _no_key()
    rt = request.app.state.runtime
    rhash = hashlib.sha256(
        json.dumps({"endpoint": "webhook_endpoints", "body": body.model_dump()}, sort_keys=True).encode()
    ).hexdigest()
    try:
        with rt.engine.begin() as conn:
            stored = _claim(conn, principal.org_id, idempotency_key, rhash, rt.clock.now())
            if stored is not None:
                return JSONResponse(stored, status_code=201)
            out, secret = endpoints.create(
                conn,
                rt.clock,
                rt.settings,
                org_id=principal.org_id,
                url=body.url,
                event_types=body.event_types,
                description=body.description,
            )
            append(
                conn,
                rt.clock,
                org_id=principal.org_id,
                actor=Actor(principal.user_id, principal.role),
                kind="webhook_endpoint.created",
                subject_id=out["id"],
                payload={"url": out["url"], "event_types": out["event_types"], "key_id": principal.key_id},
            )
            conn.execute(
                text("UPDATE idempotency_records SET response=CAST(:r AS jsonb) WHERE org_id=:o AND key=:k"),
                {"r": json.dumps({**out, "secret": None}), "o": principal.org_id, "k": idempotency_key},
            )
    except EndpointError as exc:
        return _endpoint_error(exc)
    return JSONResponse({**out, "secret": secret}, status_code=201)


@router.get("/webhook_endpoints")
def list_endpoints(request: Request, principal: Auth) -> JSONResponse:
    require(principal, "read")
    rt = request.app.state.runtime
    with rt.engine.connect() as conn:
        data = endpoints.list_all(conn, principal.org_id)
    return JSONResponse({"data": data, "has_more": False, "next_cursor": None})


@router.get("/webhook_endpoints/{endpoint_id}")
def get_endpoint(request: Request, endpoint_id: str, principal: Auth) -> JSONResponse:
    require(principal, "read")
    rt = request.app.state.runtime
    try:
        with rt.engine.connect() as conn:
            return JSONResponse(endpoints.endpoint_json(endpoints.get(conn, principal.org_id, endpoint_id)))
    except EndpointError as exc:
        return _endpoint_error(exc)


@router.delete("/webhook_endpoints/{endpoint_id}")
def disable_endpoint(request: Request, endpoint_id: str, principal: Auth) -> JSONResponse:
    """Disable an endpoint: nothing more is delivered to it. The row and its delivery log stay."""
    require(principal, "admin")
    rt = request.app.state.runtime
    try:
        with rt.engine.begin() as conn:
            out = endpoints.disable(conn, rt.clock, principal.org_id, endpoint_id)
            append(
                conn,
                rt.clock,
                org_id=principal.org_id,
                actor=Actor(principal.user_id, principal.role),
                kind="webhook_endpoint.disabled",
                subject_id=endpoint_id,
                payload={"key_id": principal.key_id},
            )
    except EndpointError as exc:
        return _endpoint_error(exc)
    return JSONResponse(out)


@router.post("/webhook_endpoints/{endpoint_id}/test")
def send_test_event(request: Request, endpoint_id: str, principal: Auth) -> JSONResponse:
    """'Send test event': a `webhook.test` event with `"test": true`, to this endpoint only (G-20)."""
    require(principal, "admin")
    rt = request.app.state.runtime
    try:
        with rt.engine.begin() as conn:
            event_id = delivery.send_test(conn, rt.clock, org_id=principal.org_id, endpoint_id=endpoint_id)
            append(
                conn,
                rt.clock,
                org_id=principal.org_id,
                actor=Actor(principal.user_id, principal.role),
                kind="webhook.test_sent",
                subject_id=endpoint_id,
                payload={"event_id": event_id},
            )
    except EndpointError as exc:
        return _endpoint_error(exc)
    return JSONResponse(
        {"event_id": event_id, "type": TEST_EVENT_TYPE, "endpoint_id": endpoint_id}, status_code=202
    )


@router.get("/webhook_endpoints/{endpoint_id}/deliveries")
def list_endpoint_deliveries(
    request: Request,
    endpoint_id: str,
    principal: Auth,
    limit: int = Query(default=50, ge=1, le=100),
    starting_after: str | None = Query(default=None, max_length=64),
) -> JSONResponse:
    """WHK-03: the delivery log, newest first: one row per attempt with status code and time."""
    require(principal, "read")
    rt = request.app.state.runtime
    try:
        with rt.engine.connect() as conn:
            data, more = delivery.list_deliveries(
                conn, principal.org_id, endpoint_id, limit=limit, starting_after=starting_after
            )
    except EndpointError as exc:
        return _endpoint_error(exc)
    return _page(data, more)


class ResendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=4, max_length=64)


@router.post("/webhook_endpoints/{endpoint_id}/resend")
def resend_event(request: Request, endpoint_id: str, body: ResendIn, principal: Auth) -> JSONResponse:
    """Manual resend: a fresh delivery of one event to this endpoint, with its own retries."""
    require(principal, "admin")
    rt = request.app.state.runtime
    try:
        with rt.engine.begin() as conn:
            delivery.resend(
                conn, rt.clock, org_id=principal.org_id, endpoint_id=endpoint_id, event_id=body.event_id
            )
            append(
                conn,
                rt.clock,
                org_id=principal.org_id,
                actor=Actor(principal.user_id, principal.role),
                kind="webhook.resend_requested",
                subject_id=endpoint_id,
                payload={"event_id": body.event_id},
            )
    except EndpointError as exc:
        return _endpoint_error(exc)
    return JSONResponse(
        {"endpoint_id": endpoint_id, "event_id": body.event_id, "queued": True}, status_code=202
    )


# ------------------------------------------------------------------------------------- events (API-07)
_EVENT_SQL = (
    "SELECT payload FROM webhook_events WHERE org_id=:o "
    "AND (CAST(:t AS TEXT) IS NULL OR type = :t) "
    "AND (CAST(:p AS TEXT) IS NULL OR payment_id = :p) "
    "AND (CAST(:test AS BOOLEAN) IS NULL OR test = :test) "
    "AND (CAST(:after AS TEXT) IS NULL OR pos < "
    "(SELECT pos FROM webhook_events WHERE org_id=:o AND id=:after)) "
    "ORDER BY pos DESC LIMIT :n"
)


@router.get("/events")
def list_events(
    request: Request,
    principal: Auth,
    type: str | None = Query(default=None, max_length=64),
    payment_id: str | None = Query(default=None, max_length=64),
    test: bool | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    starting_after: str | None = Query(default=None, max_length=64),
) -> JSONResponse:
    """API-07: the same event objects webhooks deliver, newest first, for clients that poll."""
    require(principal, "read")
    if type is not None and type not in EVENT_TYPES and type != TEST_EVENT_TYPE:
        return error_response(
            422,
            "invalid_request",
            "unknown_event_type",
            f"Unknown event type {type!r}.",
            request_id=_rid(),
            param="type",
        )
    rt = request.app.state.runtime
    with rt.engine.connect() as conn:
        rows = conn.execute(
            text(_EVENT_SQL),
            {
                "o": principal.org_id,
                "t": type,
                "p": payment_id,
                "test": test,
                "after": starting_after,
                "n": limit + 1,
            },
        ).all()
    data = [dict(r.payload) for r in rows[:limit]]
    return _page(data, len(rows) > limit)


@router.get("/events/{event_id}")
def get_event(request: Request, event_id: str, principal: Auth) -> JSONResponse:
    require(principal, "read")
    rt = request.app.state.runtime
    with rt.engine.connect() as conn:
        row = conn.execute(
            text("SELECT payload FROM webhook_events WHERE org_id=:o AND id=:e"),
            {"o": principal.org_id, "e": event_id},
        ).one_or_none()
    if row is None:
        return error_response(404, "not_found", "not_found", "No such event.", request_id=_rid(), param="id")
    return JSONResponse(dict(row.payload))


# ------------------------------------------------------------------------------------- exceptions (EXC-08)
@router.get("/exceptions")
def list_exceptions(
    request: Request,
    principal: Auth,
    status: Literal["open", "resolved"] | None = None,
    owner: str | None = Query(default=None, max_length=64),
    tier: int | None = Query(default=None, ge=1, le=9),
    overdue: bool | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    starting_after: str | None = Query(default=None, max_length=64),
) -> JSONResponse:
    """EXC-08: cases newest first. Approve and reject are POST /exceptions/{id}/approve and /reject."""
    require(principal, "read")
    rt = request.app.state.runtime
    with rt.engine.connect() as conn:
        data, more = list_cases(
            conn,
            principal.org_id,
            now=rt.clock.now(),
            status=status,
            owner=owner,
            tier=tier,
            overdue=overdue,
            limit=limit,
            starting_after=starting_after,
        )
    return _page(data, more)


@router.get("/exceptions/{case_id}")
def get_exception(request: Request, case_id: str, principal: Auth) -> JSONResponse:
    """EXC-08: raw facts first, then rule hits, the investigation's evidence and the history (EXC-02)."""
    require(principal, "read")
    rt = request.app.state.runtime
    with rt.engine.connect() as conn:
        out = case_detail(conn, principal.org_id, case_id)
    if out is None:
        return error_response(
            404, "not_found", "not_found", "No such exception.", request_id=_rid(), param="id"
        )
    return JSONResponse(out)
