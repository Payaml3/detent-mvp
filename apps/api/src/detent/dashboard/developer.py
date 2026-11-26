"""The developer pages of the dashboard (DSH-04, DSH-05, DSH-06, DSH-08; spec/08).

Keys, request logs, webhooks and usage, for the account owner, admins and developers (usage is open to every
member). A key or webhook secret is shown once, in the response to the form that made it, which is never
cached; only a hash (or, for webhooks, the encrypted signing secret) is kept.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import text

from detent.audit.log import append
from detent.dashboard import keys as key_service
from detent.dashboard import sandbox, verification
from detent.dashboard.access import AccessError, Member
from detent.dashboard.web import check_csrf, client_member, page, redirect, runtime, writable_member
from detent.db.engine import transaction
from detent.domain.roles import allowed
from detent.runtime import Runtime
from detent.sandbox import usage
from detent.sandbox.generations import CURRENT
from detent.webhooks import delivery, endpoints
from detent.webhooks.endpoints import EndpointError
from detent.webhooks.events import ALL_TYPES, EVENT_TYPES

router = APIRouter(prefix="/dashboard", dependencies=[Depends(check_csrf)], include_in_schema=False)

LOG_DAYS = 30  # spec/08: request logs are kept for 30 days
LOG_PAGE = 50
NO_STORE = {"Cache-Control": "no-store"}


def _need(member: Member, action: str) -> None:
    if not allowed(action, member.role):
        raise AccessError("forbidden", "Your role can't open this page.", status=403)


def _shown_once(resp: HTMLResponse) -> HTMLResponse:
    resp.headers.update(NO_STORE)
    return resp


# ------------------------------------------------------------------------------------------ keys (DSH-04)
@router.get("/keys", response_class=HTMLResponse)
def keys_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(client_member),  # noqa: B008
) -> HTMLResponse:
    return _keys(request, rt, member)


def _keys(
    request: Request,
    rt: Runtime,
    member: Member,
    *,
    error: str | None = None,
    status: int = 200,
    secret: str | None = None,
    notice: str | None = None,
) -> HTMLResponse:
    if not allowed("keys.manage", member.role):
        return page(
            request, rt, "forbidden.html", member, message="Your role can't manage keys.", status_code=403
        )
    with rt.engine.connect() as conn:
        rows = key_service.list_keys(conn, member.org_id)
    resp = page(
        request,
        rt,
        "keys.html",
        member,
        keys=rows,
        scope_text=key_service.SCOPE_TEXT,
        overlap=rt.settings.key_roll_overlap_hours,
        configured=rt.settings.api_key_pepper is not None,
        error=error,
        secret=secret,
        notice=notice,
        status_code=status,
    )
    return _shown_once(resp) if secret else resp


@router.post("/keys", response_model=None)
async def create_key(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    form = await request.form()
    name = str(form.get("name") or "")
    scopes = [str(s) for s in form.getlist("scopes")]
    try:
        with transaction(rt.engine) as conn:
            _kid, secret = key_service.create_key(
                conn, rt.clock, rt.settings, by=member, name=name, scopes=scopes
            )
    except AccessError as exc:
        return _keys(request, rt, member, error=str(exc), status=exc.status)
    return _keys(request, rt, member, secret=secret, notice="Key created.", status=201)


@router.post("/keys/{key_id}/roll", response_model=None)
def roll_key(
    key_id: str,
    request: Request,
    overlap_hours: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    try:
        hours = int(overlap_hours) if overlap_hours.strip() else rt.settings.key_roll_overlap_hours
        with transaction(rt.engine) as conn:
            _kid, secret = key_service.roll_key(
                conn, rt.clock, rt.settings, by=member, key_id=key_id, overlap_hours=hours
            )
    except ValueError as exc:  # AccessError is a ValueError; so is a non-number overlap
        status = exc.status if isinstance(exc, AccessError) else 422
        msg = str(exc) if isinstance(exc, AccessError) else "The overlap is a whole number of hours."
        return _keys(request, rt, member, error=msg, status=status)
    return _keys(request, rt, member, secret=secret, notice="Key rolled.", status=201)


@router.post("/keys/{key_id}/revoke", response_model=None)
def revoke_key(
    key_id: str,
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    try:
        with transaction(rt.engine) as conn:
            key_service.revoke_key(conn, rt.clock, by=member, key_id=key_id)
    except AccessError as exc:
        return _keys(request, rt, member, error=str(exc), status=exc.status)
    return redirect("/dashboard/keys?notice=revoked")


# ------------------------------------------------------------------------------------------ logs (DSH-05)
_LOG_COLS = "id, key_id, method, path, status, latency_ms, idempotency_key, payment_id, request_id, at"


@router.get("/logs", response_class=HTMLResponse)
def logs_page(
    request: Request,
    status: str = "",
    path: str = "",
    idempotency_key: str = "",
    payment_id: str = "",
    before: str = "",
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(client_member),  # noqa: B008
) -> HTMLResponse:
    try:
        _need(member, "request_logs.read")
    except AccessError as exc:
        return page(request, rt, "forbidden.html", member, message=str(exc), status_code=exc.status)
    where, params = (
        ["org_id=:o", "at >= :since", CURRENT],
        {
            "o": member.org_id,
            "since": rt.clock.now() - timedelta(days=LOG_DAYS),
        },
    )
    error = None
    status = status.strip().lower()
    if status:
        if len(status) == 3 and status[0] in "12345" and status.endswith("xx"):
            where.append("status >= :lo AND status < :hi")
            params["lo"], params["hi"] = int(status[0]) * 100, int(status[0]) * 100 + 100
        elif status.isdigit() and len(status) == 3:
            where.append("status = :st")
            params["st"] = int(status)
        else:
            error = "Filter the status by a code such as 422, or a class such as 4xx."
    if path.strip():
        where.append("strpos(path, :path) > 0")
        params["path"] = path.strip()[:200]
    if idempotency_key.strip():
        where.append("idempotency_key = :idem")
        params["idem"] = idempotency_key.strip()[:255]
    if payment_id.strip():
        where.append("payment_id = :pay")
        params["pay"] = payment_id.strip()[:64]
    if before.strip().isdigit():
        where.append("id < :before")
        params["before"] = int(before)
    rows: list[Any] = []
    if error is None:
        with rt.engine.connect() as conn:
            rows = list(
                conn.execute(
                    text(
                        f"SELECT {_LOG_COLS} FROM request_logs WHERE "  # noqa: S608 - fixed fragments only
                        + " AND ".join(where)
                        + " ORDER BY id DESC LIMIT :n"
                    ),
                    {**params, "n": LOG_PAGE + 1},
                ).all()
            )
    more = len(rows) > LOG_PAGE
    rows = rows[:LOG_PAGE]
    filters = {"status": status, "path": path, "idempotency_key": idempotency_key, "payment_id": payment_id}
    return page(
        request,
        rt,
        "logs.html",
        member,
        rows=rows,
        more=more,
        next_before=rows[-1].id if rows and more else None,
        filters=filters,
        error=error,
        days=LOG_DAYS,
        status_code=422 if error else 200,
    )


@router.get("/logs/{log_id}", response_class=HTMLResponse)
def log_detail(
    log_id: str,
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(client_member),  # noqa: B008
) -> HTMLResponse:
    try:
        _need(member, "request_logs.read")
    except AccessError as exc:
        return page(request, rt, "forbidden.html", member, message=str(exc), status_code=exc.status)
    row = None
    if log_id.isdigit():
        with rt.engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT {_LOG_COLS} FROM request_logs WHERE org_id=:o AND id=:i AND {CURRENT}"),  # noqa: S608
                {"o": member.org_id, "i": int(log_id)},
            ).one_or_none()
    if row is None:
        return page(request, rt, "not_found.html", member, status_code=404)
    return page(request, rt, "log.html", member, row=row)


# ------------------------------------------------------------------------------------------ webhooks (DSH-06)
def _webhooks(
    request: Request,
    rt: Runtime,
    member: Member,
    *,
    error: str | None = None,
    status: int = 200,
    secret: str | None = None,
    form: dict[str, Any] | None = None,
) -> HTMLResponse:
    if not allowed("webhooks.manage", member.role):
        return page(
            request, rt, "forbidden.html", member, message="Your role can't manage webhooks.", status_code=403
        )
    with rt.engine.connect() as conn:
        rows = endpoints.list_all(conn, member.org_id)
    resp = page(
        request,
        rt,
        "webhooks.html",
        member,
        endpoints=rows,
        event_types=EVENT_TYPES,
        all_types=ALL_TYPES,
        configured=rt.settings.credentials_encryption_key is not None,
        error=error,
        secret=secret,
        form=form or {},
        status_code=status,
    )
    return _shown_once(resp) if secret else resp


@router.get("/webhooks", response_class=HTMLResponse)
def webhooks_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(client_member),  # noqa: B008
) -> HTMLResponse:
    return _webhooks(request, rt, member)


def _audit(conn: Any, rt: Runtime, member: Member, kind: str, subject: str, payload: dict[str, Any]) -> None:
    append(
        conn,
        rt.clock,
        org_id=member.org_id,
        actor=member.actor,
        kind=kind,
        subject_id=subject,
        payload={**payload, "via": "dashboard"},
    )


@router.post("/webhooks", response_model=None)
async def create_webhook(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    form = await request.form()
    url = str(form.get("url") or "")
    description = str(form.get("description") or "").strip() or None
    types = [str(t) for t in form.getlist("event_types")]
    kept = {"url": url, "description": description or "", "event_types": types}
    try:
        _need(member, "webhooks.manage")
        with transaction(rt.engine) as conn:
            out, secret = endpoints.create(
                conn,
                rt.clock,
                rt.settings,
                org_id=member.org_id,
                url=url,
                event_types=types or [ALL_TYPES],
                description=description,
            )
            _audit(
                conn,
                rt,
                member,
                "webhook_endpoint.created",
                out["id"],
                {"url": out["url"], "event_types": out["event_types"]},
            )
    except (AccessError, EndpointError) as exc:
        code = exc.status
        return _webhooks(request, rt, member, error=str(exc), status=code, form=kept)
    return _webhooks(request, rt, member, secret=secret, status=201)


def _endpoint_page(
    request: Request,
    rt: Runtime,
    member: Member,
    endpoint_id: str,
    *,
    error: str | None = None,
    status: int = 200,
) -> HTMLResponse:
    if not allowed("webhooks.manage", member.role):
        return page(
            request, rt, "forbidden.html", member, message="Your role can't manage webhooks.", status_code=403
        )
    try:
        with rt.engine.connect() as conn:
            ep = endpoints.endpoint_json(endpoints.get(conn, member.org_id, endpoint_id))
            deliveries, more = delivery.list_deliveries(
                conn, member.org_id, endpoint_id, limit=50, starting_after=None
            )
    except EndpointError:
        return page(request, rt, "not_found.html", member, status_code=404)
    return page(
        request,
        rt,
        "webhook.html",
        member,
        ep=ep,
        deliveries=deliveries,
        more=more,
        error=error,
        status_code=status,
    )


@router.get("/webhooks/{endpoint_id}", response_class=HTMLResponse)
def webhook_detail(
    endpoint_id: str,
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(client_member),  # noqa: B008
) -> HTMLResponse:
    return _endpoint_page(request, rt, member, endpoint_id)


def _endpoint_action(
    request: Request, rt: Runtime, member: Member, endpoint_id: str, fn: Any, notice: str
) -> Response:
    try:
        _need(member, "webhooks.manage")
        with transaction(rt.engine) as conn:
            fn(conn)
    except (AccessError, EndpointError) as exc:
        return _endpoint_page(request, rt, member, endpoint_id, error=str(exc), status=exc.status)
    return redirect(f"/dashboard/webhooks/{endpoint_id}?notice={notice}")


@router.post("/webhooks/{endpoint_id}/test", response_model=None)
def webhook_test(
    endpoint_id: str,
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    def go(conn: Any) -> None:
        event_id = delivery.send_test(conn, rt.clock, org_id=member.org_id, endpoint_id=endpoint_id)
        _audit(conn, rt, member, "webhook.test_sent", endpoint_id, {"event_id": event_id})

    return _endpoint_action(request, rt, member, endpoint_id, go, "test_sent")


@router.post("/webhooks/{endpoint_id}/resend", response_model=None)
def webhook_resend(
    endpoint_id: str,
    request: Request,
    event_id: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    def go(conn: Any) -> None:
        delivery.resend(conn, rt.clock, org_id=member.org_id, endpoint_id=endpoint_id, event_id=event_id[:64])
        _audit(conn, rt, member, "webhook.resend_requested", endpoint_id, {"event_id": event_id[:64]})

    return _endpoint_action(request, rt, member, endpoint_id, go, "resent")


@router.post("/webhooks/{endpoint_id}/disable", response_model=None)
def webhook_disable(
    endpoint_id: str,
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    def go(conn: Any) -> None:
        endpoints.disable(conn, rt.clock, member.org_id, endpoint_id)
        _audit(conn, rt, member, "webhook_endpoint.disabled", endpoint_id, {})

    return _endpoint_action(request, rt, member, endpoint_id, go, "disabled")


# ------------------------------------------------------------------------------------------ usage (DSH-08)
@router.get("/usage", response_class=HTMLResponse)
def usage_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(client_member),  # noqa: B008
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        lines = usage.summary(conn, rt.clock, member.org_id)
    now = rt.clock.now()
    return page(
        request,
        rt,
        "usage.html",
        member,
        lines=lines,
        resets_in=usage.seconds_to_next_day(now),
        month=now.strftime("%B %Y"),
        per_minute=rt.settings.api_rate_limit_per_minute,
    )


# ------------------------------------------------------------------------------------------ sandbox (DSH-07)
def _sandbox(
    request: Request, rt: Runtime, member: Member, *, error: str | None = None, status: int = 200
) -> HTMLResponse:
    if not allowed("sandbox.control", member.role):
        return page(
            request,
            rt,
            "forbidden.html",
            member,
            message="Your role can't use the sandbox controls.",
            status_code=403,
        )
    with rt.engine.connect() as conn:
        org = conn.execute(
            text("SELECT mode, kind, sandbox_rails, data_generation FROM organisations WHERE org_id=:o"),
            {"o": member.org_id},
        ).one()
        payouts = sandbox.recent_payouts(conn, member.org_id)
    return page(
        request,
        rt,
        "sandbox.html",
        member,
        scenarios=sandbox.SCENARIOS,
        mode=org.mode,
        rails=org.sandbox_rails,
        kind=org.kind,
        generation=org.data_generation,
        testnets=sandbox.testnet_available(rt.settings),
        payouts=payouts,
        faucet=(rt.settings.faucet_daily_cap, rt.settings.faucet_org_daily_cap),
        error=error,
        status_code=status,
    )


@router.get("/sandbox", response_class=HTMLResponse)
def sandbox_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(client_member),  # noqa: B008
) -> HTMLResponse:
    return _sandbox(request, rt, member)


@router.post("/sandbox/scenarios", response_model=None)
def sandbox_scenario(
    request: Request,
    scenario: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    try:
        out = sandbox.run_scenario(
            rt.engine, rt.clock, rt.settings, request.app.state.screening, by=member, scenario=scenario
        )
    except AccessError as exc:
        return _sandbox(request, rt, member, error=str(exc), status=exc.status)
    return redirect(f"/dashboard/sandbox?notice=scenario&payment={out['id']}")


@router.post("/sandbox/rails", response_model=None)
def sandbox_rails(
    request: Request,
    mode: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    try:
        with transaction(rt.engine) as conn:
            sandbox.set_rails_mode(conn, rt.clock, rt.settings, by=member, mode=mode)
    except AccessError as exc:
        return _sandbox(request, rt, member, error=str(exc), status=exc.status)
    return redirect("/dashboard/sandbox?notice=rails")


@router.post("/sandbox/reset", response_model=None)
def sandbox_reset(
    request: Request,
    confirm: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    try:
        with transaction(rt.engine) as conn:
            sandbox.reset_sandbox(conn, rt.clock, by=member, confirm=confirm)
    except AccessError as exc:
        return _sandbox(request, rt, member, error=str(exc), status=exc.status)
    return redirect("/dashboard/sandbox?notice=reset")


# ------------------------------------------------------------------------------------- verification (DSH-12)
def _verification(
    request: Request, rt: Runtime, member: Member, *, error: str | None = None, status: int = 200
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        items = verification.checklist(conn, member.org_id)
        last = verification.latest(conn, member.org_id)
    return page(
        request,
        rt,
        "verification.html",
        member,
        items=items,
        last=last,
        can_request=allowed("verification.request", member.role),
        error=error,
        status_code=status,
    )


@router.get("/verification", response_class=HTMLResponse)
def verification_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(client_member),  # noqa: B008
) -> HTMLResponse:
    return _verification(request, rt, member)


@router.post("/verification/request", response_model=None)
def verification_request(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    try:
        with transaction(rt.engine) as conn:
            verification.request_verification(conn, rt.clock, by=member)
    except AccessError as exc:
        return _verification(request, rt, member, error=str(exc), status=exc.status)
    return redirect("/dashboard/verification?notice=requested")
