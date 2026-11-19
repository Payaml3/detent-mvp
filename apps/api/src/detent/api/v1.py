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
from detent.ledger.deposits import DepositRequest
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
    if principal.mandate_id is not None and (
        body.source != "agent" or body.mandate_id != principal.mandate_id
    ):
        return error_response(
            403,
            "permission",
            "mandate_mismatch",
            "This key belongs to an agent mandate; it can only propose agent intents under it.",
            request_id=_rid(),
            param="mandate_id",
        )
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
        mandate_key=rt.settings.mandate_signing_key_demo,
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
        if action == "approve":
            res = approve(
                rt.engine,
                rt.clock,
                case_id=case_id,
                org_id=principal.org_id,
                actor=actor,
                reason=body.reason,
                mandate_key=rt.settings.mandate_signing_key_demo,
            )
        else:
            res = reject(
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


# --------------------------------------------------------------------------------- kill switch (EXE-08)
def _kill_switch(request: Request, principal: Principal, engage_it: bool) -> JSONResponse:
    from detent.execution.kill_switch import engage, is_engaged, release

    require(principal, "admin")
    rt = request.app.state.runtime
    actor = Actor(principal.user_id, principal.role)
    try:
        if engage_it:
            engage(rt.engine, rt.clock, org_id=principal.org_id, actor=actor)
        else:
            release(
                rt.engine,
                rt.clock,
                org_id=principal.org_id,
                actor=actor,
                mandate_key=rt.settings.mandate_signing_key_demo,
            )
    except PermissionError as exc:
        return error_response(403, "permission", "insufficient_role", str(exc), request_id=_rid())
    return JSONResponse({"engaged": is_engaged(rt.engine, principal.org_id)})


@router.post("/kill_switch")
def engage_kill_switch(
    request: Request, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    return _kill_switch(request, principal, True)


@router.delete("/kill_switch")
def release_kill_switch(
    request: Request, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    return _kill_switch(request, principal, False)


# --------------------------------------------------------------------------------- mandates (MND-01, MND-03)
@router.get("/mandates")
def list_mandates_api(
    request: Request, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    from detent.mandates.store import list_mandates

    require(principal, "read")
    with request.app.state.runtime.engine.connect() as conn:
        return JSONResponse(
            {"data": list_mandates(conn, principal.org_id), "has_more": False, "next_cursor": None}
        )


@router.post("/mandates/{mandate_id}/revoke")
def revoke_mandate_api(
    request: Request, mandate_id: str, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    from detent.domain.roles import Role, allowed
    from detent.mandates.store import revoke_mandate

    require(principal, "admin")
    if not allowed("mandate.revoke", Role(principal.role)):
        return error_response(
            403,
            "permission",
            "insufficient_role",
            "Only the payments lead revokes a mandate.",
            request_id=_rid(),
        )
    rt = request.app.state.runtime
    try:
        with rt.engine.begin() as conn:
            revoke_mandate(
                conn, rt.clock, principal.org_id, mandate_id, actor=Actor(principal.user_id, principal.role)
            )
    except LookupError:
        return error_response(404, "not_found", "not_found", "No such mandate.", request_id=_rid())
    return JSONResponse({"mandate_id": mandate_id, "revoked": True})


# ------------------------------------------------------------------------------- policy versions (POL-07)
@router.get("/policy/versions")
def list_policy_versions(
    request: Request, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    """Every rule version, newest first. Changes happen in the console with two approvers (POL-07)."""
    from detent.policy.changes import list_versions

    require(principal, "read")
    with request.app.state.runtime.engine.connect() as conn:
        return JSONResponse(
            {"data": list_versions(conn, principal.org_id), "has_more": False, "next_cursor": None}
        )


@router.get("/policy/versions/{version}")
def get_policy_version(
    request: Request, version: int, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    from detent.policy.changes import get_version

    require(principal, "read")
    with request.app.state.runtime.engine.connect() as conn:
        v = get_version(conn, principal.org_id, version)
    if v is None:
        return error_response(404, "not_found", "not_found", f"No rule version {version}.", request_id=_rid())
    return JSONResponse(v)


# ------------------------------------------------------------------------------------- Send (EXE-09)
@router.post("/payment_intents/{payment_id}/send")
def send_payment_intent(
    request: Request, payment_id: str, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    """Assist mode: a person confirms sending. The worker then sends it with every pre-send check."""
    from detent.execution.modes import ModeError, confirm_send

    require(principal, "exceptions:approve")
    rt = request.app.state.runtime
    try:
        confirm_send(
            rt.engine,
            rt.clock,
            org_id=principal.org_id,
            payment_id=payment_id,
            actor=Actor(principal.user_id, principal.role),
        )
    except ModeError as exc:
        if exc.status == 403:
            return error_response(403, "permission", exc.code, str(exc), request_id=_rid())
        if exc.status == 404:
            return error_response(404, "not_found", exc.code, str(exc), request_id=_rid())
        return error_response(exc.status, "conflict", exc.code, str(exc), request_id=_rid())
    with rt.engine.connect() as conn:
        from detent.intents.service import payment_view

        return JSONResponse(payment_view(conn, principal.org_id, payment_id))


# ------------------------------------------------------------------------------- deposits (LED-03)
@router.post("/deposit_intents", status_code=201)
def create_deposit_intent_api(
    request: Request,
    body: DepositRequest,
    principal: Annotated[Principal, Depends(authenticate)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=255)] = None,
) -> JSONResponse:
    from detent.ledger.deposits import DepositError, create_deposit_intent

    require(principal, "intents:create")
    if not idempotency_key:
        raise MissingIdempotencyKey()
    rt = request.app.state.runtime
    try:
        code, out = create_deposit_intent(
            rt.engine,
            rt.clock,
            org_id=principal.org_id,
            actor_id=principal.user_id,
            idempotency_key=idempotency_key,
            request=body,
        )
    except DepositError as exc:
        if exc.status == 409:
            return error_response(409, "conflict", exc.code, str(exc), request_id=_rid())
        return error_response(422, "invalid_request", exc.code, str(exc), request_id=_rid(), param=exc.param)
    return JSONResponse(out, status_code=code)


@router.get("/deposit_intents/{deposit_id}")
def get_deposit_intent_api(
    request: Request, deposit_id: str, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    from detent.ledger.deposits import view

    require(principal, "read")
    with request.app.state.runtime.engine.connect() as conn:
        v = view(conn, principal.org_id, deposit_id)
    if v is None:
        return error_response(
            404, "not_found", "not_found", "No such deposit intent.", request_id=_rid(), param="id"
        )
    return JSONResponse(v)


# ------------------------------------------------------------------------------ reconciliation (LED-06)
@router.get("/reconciliation/runs")
def reconciliation_runs(
    request: Request, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    from detent.reconciliation.run import latest_runs

    require(principal, "read")
    with request.app.state.runtime.engine.connect() as conn:
        return JSONResponse(
            {"data": latest_runs(conn, principal.org_id), "has_more": False, "next_cursor": None}
        )


@router.get("/reconciliation/breaks")
def reconciliation_breaks(
    request: Request, principal: Annotated[Principal, Depends(authenticate)], status: str | None = None
) -> JSONResponse:
    from detent.reconciliation.run import list_breaks

    require(principal, "read")
    with request.app.state.runtime.engine.connect() as conn:
        return JSONResponse(
            {"data": list_breaks(conn, principal.org_id, status), "has_more": False, "next_cursor": None}
        )


# ------------------------------------------------------------------------------------- replay (AUD-02)
@router.get("/payment_intents/{payment_id}/replay")
def replay_payment_intent(
    request: Request, payment_id: str, principal: Annotated[Principal, Depends(authenticate)]
) -> JSONResponse:
    """Re-evaluate every recorded decision from its stored inputs and rule version. Never calls a model."""
    from detent.audit.replay import NotReplayable, replay_payment

    require(principal, "read")
    rt = request.app.state.runtime
    try:
        return JSONResponse(
            replay_payment(rt.engine, rt.clock, org_id=principal.org_id, payment_id=payment_id)
        )
    except NotReplayable:
        return error_response(
            404, "not_found", "not_found", "No such payment intent.", request_id=_rid(), param="id"
        )
