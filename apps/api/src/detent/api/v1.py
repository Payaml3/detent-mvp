"""The /v1 decision endpoints (spec/03): create, decide-only, read and list payment intents."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from detent.api.auth import Principal, authenticate, require
from detent.api.errors import ErrorType, error_response
from detent.audit.log import Actor
from detent.exceptions.cases import CaseError, approve, reject
from detent.intents.service import IntentRequest, payment_view, submit_intent
from detent.logging import request_id_var

router = APIRouter(prefix="/v1")


class MissingIdempotencyKey(Exception):
    pass


def _rid() -> str | None:
    return request_id_var.get()


def _create(
    request: Request, body: IntentRequest, principal: Principal, key: str | None, decision_only: bool
) -> JSONResponse:
    require(principal, "intents:create")
    if not key:
        raise MissingIdempotencyKey()
    rt = request.app.state.runtime
    code, out = submit_intent(
        rt.engine,
        rt.clock,
        org_id=principal.org_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        idempotency_key=key,
        request=body,
        decision_only=decision_only,
        screening=request.app.state.screening,
    )
    return JSONResponse(out, status_code=code)


@router.post("/payment_intents", status_code=201)
def create_payment_intent(
    request: Request,
    body: IntentRequest,
    principal: Annotated[Principal, Depends(authenticate)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=255)] = None,
) -> JSONResponse:
    return _create(request, body, principal, idempotency_key, decision_only=False)


@router.post("/decisions")
def create_decision(
    request: Request,
    body: IntentRequest,
    principal: Annotated[Principal, Depends(authenticate)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=255)] = None,
) -> JSONResponse:
    return _create(request, body, principal, idempotency_key, decision_only=True)


@router.get("/payment_intents/{payment_id}")
def get_payment_intent(
    request: Request, payment_id: str, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    require(principal, "read")
    with request.app.state.runtime.engine.connect() as conn:
        view = payment_view(conn, principal.org_id, payment_id, detail=True)
    if view is None:  # another organisation's ID is indistinguishable from a missing one
        return error_response(
            404,
            "not_found",
            "not_found",
            "No such payment intent.",
            request_id=_rid(),
            payment_id=None,
            param="id",
        )
    return JSONResponse(view)


@router.get("/payment_intents")
def list_payment_intents(
    request: Request,
    principal: Annotated[Principal, Depends(authenticate)],
    status: str | None = None,
    rail: str | None = None,
    created_gte: Annotated[datetime | None, Query(alias="created[gte]")] = None,
    created_lte: Annotated[datetime | None, Query(alias="created[lte]")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    starting_after: str | None = None,
) -> JSONResponse:
    require(principal, "read")
    where = ["p.org_id = :o"]
    params: dict[str, Any] = {"o": principal.org_id, "lim": limit + 1}
    if status:
        where.append("p.status = :status")
        params["status"] = status
    if rail:
        where.append(
            "EXISTS (SELECT 1 FROM attempts a WHERE a.org_id = p.org_id AND a.payment_id = p.id AND "
            "a.rail_id = :rail)"
        )
        params["rail"] = rail
    if created_gte:
        where.append("p.created_at >= :gte")
        params["gte"] = created_gte
    if created_lte:
        where.append("p.created_at <= :lte")
        params["lte"] = created_lte
    with request.app.state.runtime.engine.connect() as conn:
        if starting_after:
            cur = conn.execute(
                text("SELECT created_at, id FROM payment_intents WHERE org_id=:o AND id=:i"),
                {"o": principal.org_id, "i": starting_after},
            ).one_or_none()
            if cur is None:
                return error_response(
                    422,
                    "invalid_request",
                    "validation_error",
                    "Unknown cursor.",
                    request_id=_rid(),
                    param="starting_after",
                )
            where.append("(p.created_at, p.id) < (:cc, :ci)")
            params.update(cc=cur.created_at, ci=cur.id)
        ids = (
            conn.execute(
                text(
                    # `where` holds only fixed fragments from this function; values are bound parameters.
                    f"SELECT p.id FROM payment_intents p WHERE {' AND '.join(where)} "  # noqa: S608
                    "ORDER BY p.created_at DESC, p.id DESC LIMIT :lim"
                ),
                params,
            )
            .scalars()
            .all()
        )
        has_more = len(ids) > limit
        ids = ids[:limit]
        data = [payment_view(conn, principal.org_id, i) for i in ids]
    return JSONResponse(
        {"data": data, "has_more": has_more, "next_cursor": ids[-1] if has_more and ids else None}
    )


# --------------------------------------------------------------------------------- exceptions (EXC-04)
class ResolutionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=2000)


def _resolve_case(
    request: Request, case_id: str, body: ResolutionIn, principal: Principal, action: str
) -> JSONResponse:
    require(principal, "exceptions:approve")
    if not body.reason.strip():
        return error_response(
            422,
            "invalid_request",
            "validation_error",
            "A reason is required.",
            request_id=_rid(),
            param="reason",
        )
    rt = request.app.state.runtime
    actor = Actor(principal.user_id, principal.role)
    try:
        fn = approve if action == "approve" else reject
        res = fn(
            rt.engine, rt.clock, case_id=case_id, org_id=principal.org_id, actor=actor, reason=body.reason
        )
    except CaseError as exc:
        kinds: dict[int, ErrorType] = {404: "not_found", 403: "permission", 409: "conflict"}
        return error_response(
            exc.status,
            kinds.get(exc.status, "conflict"),
            exc.code,
            str(exc) or exc.code,
            request_id=_rid(),
        )
    return JSONResponse(
        {
            "case_id": res.case_id,
            "payment_id": res.payment_id,
            "payment_status": res.payment_status,
            "new_case_id": res.new_case_id,
        }
    )


@router.post("/exceptions/{case_id}/approve")
def approve_exception(
    request: Request, case_id: str, body: ResolutionIn, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    return _resolve_case(request, case_id, body, principal, "approve")


@router.post("/exceptions/{case_id}/reject")
def reject_exception(
    request: Request, case_id: str, body: ResolutionIn, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    return _resolve_case(request, case_id, body, principal, "reject")
