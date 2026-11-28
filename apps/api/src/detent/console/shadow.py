"""Console Shadow screens: import an export (SHD-01, SHD-04), the shadow-phase report (SHD-02), mode gates
(SHD-03) and the agent-versus-human agreement sample (EXC-09)."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from detent.audit.log import Actor
from detent.console.auth import ActingUser, acting_user, require_permission, runtime
from detent.console.routes import page, templates
from detent.domain.roles import allowed
from detent.runtime import Runtime
from detent.shadow import gates, imports, pdf, report

router = APIRouter(prefix="/console")
FIELD_KEYS = list(imports.FIELDS)


def _redirect(url: str, exc: Exception | None = None) -> RedirectResponse:
    return RedirectResponse(url + (f"?error={quote(str(exc)[:300])}" if exc else ""), status_code=303)


@router.get("/shadow", response_class=HTMLResponse)
def shadow_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    from sqlalchemy import text

    from detent.execution.modes import current_mode

    with rt.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM shadow_imports WHERE org_id=:o ORDER BY created_at DESC, id DESC LIMIT 50"),
            {"o": user.org_id},
        ).all()
        mode = current_mode(conn, user.org_id)
        live = gates.measure(conn, user.org_id, rt.clock.now())
        gate_rows = gates.list_gates(conn, user.org_id)
    return page(
        request,
        rt,
        "shadow.html",
        user,
        imports=rows,
        fields=imports.FIELDS,
        mode=mode,
        live=live,
        gates=gate_rows,
        next_modes=[m for m in ("assist", "auto") if gates.is_upward(mode, m)],
        can_import=allowed("shadow.import", user.role),
        can_gate=allowed("mode_gate.create", user.role),
        my_role=user.role.value,
        error=request.query_params.get("error"),
    )


@router.post("/shadow/map", response_class=HTMLResponse)
async def shadow_map(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("shadow.import")),  # noqa: B008
) -> Response:
    """Step 1: read only the header row and suggest a mapping. Nothing from the file is kept."""
    data = await file.read()
    try:
        columns = imports.read_header(data)
    except imports.ImportError_ as exc:
        return _redirect("/console/shadow", exc)
    return page(
        request,
        rt,
        "shadow_map.html",
        user,
        columns=columns,
        guess=imports.guess_mapping(columns),
        fields=imports.FIELDS,
        filename=file.filename or "export.csv",
        report=None,
        error=None,
    )


@router.post("/shadow/import", response_model=None)
async def shadow_import(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008
    action: str = Form("validate"),
    label: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("shadow.import")),  # noqa: B008
) -> Response:
    """Step 2: validate (nothing stored) or validate and decide (stored, anonymised, never executed)."""
    form = await request.form()
    mapping = {f: str(form.get(f"map_{f}") or "") for f in FIELD_KEYS}
    data = await file.read()
    try:
        columns = imports.read_header(data)
        if action == "decide":
            imp, _ = await run_in_threadpool(
                imports.run_import,
                rt.engine,
                rt.clock,
                org_id=user.org_id,
                actor=Actor(user.id, user.role.value),
                data=data,
                mapping=mapping,
                label=label or (file.filename or "Shadow import"),
                screening=request.app.state.screening,
            )
            return RedirectResponse(f"/console/shadow/{imp}", status_code=303)
        rep = imports.validate(data, mapping)
    except imports.ImportError_ as exc:
        return page(
            request, rt, "shadow_map.html", user, columns=columns if "columns" in locals() else [],
            guess=mapping, fields=imports.FIELDS, filename=file.filename or "export.csv", report=None,
            error=str(exc),
        )  # fmt: skip
    return page(
        request,
        rt,
        "shadow_map.html",
        user,
        columns=columns,
        guess=mapping,
        fields=imports.FIELDS,
        filename=file.filename or "export.csv",
        report=rep,
        error=None,
    )


def _report(
    rt: Runtime, user: ActingUser, import_id: str, week: str | None
) -> tuple[dict[str, object], list[str]]:
    start = end = None
    if week:
        try:
            start, end = report.week_bounds(week)
        except ValueError:
            raise HTTPException(status_code=404) from None
    with rt.engine.connect() as conn:
        try:
            rep = report.build(conn, user.org_id, import_id, start, end)
        except report.ReportNotFound:
            raise HTTPException(status_code=404) from None
        wk = report.weeks(conn, user.org_id, import_id)
    return rep, wk


@router.get("/shadow/{import_id}", response_class=HTMLResponse)
def shadow_report(
    request: Request,
    import_id: str,
    week: str | None = None,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    rep, wk = _report(rt, user, import_id, week)
    return page(
        request, rt, "shadow_report.html", user, rep=rep, weeks=wk, week=week, words=report.WORDS,
        method=report.METHOD, standalone=False,
    )  # fmt: skip


@router.get("/shadow/{import_id}/report.html", response_class=HTMLResponse)
def shadow_report_download(
    request: Request,
    import_id: str,
    week: str | None = None,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    rep, _wk = _report(rt, user, import_id, week)
    resp = templates.TemplateResponse(
        request,
        "shadow_report_file.html",
        {"rep": rep, "words": report.WORDS, "method": report.METHOD, "brand": rt.settings.brand_name},
    )
    resp.headers["Content-Disposition"] = f'attachment; filename="shadow-report-{import_id}.html"'
    return resp


@router.get("/shadow/{import_id}/report.pdf")
def shadow_report_pdf(
    import_id: str,
    week: str | None = None,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> Response:
    rep, _ = _report(rt, user, import_id, week)
    body = pdf.render(report.as_lines(rep), title=f"Shadow-phase report {import_id}")
    return Response(
        body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="shadow-report-{import_id}.pdf"'},
    )


# ------------------------------------------------------------------------------------------ SHD-03
@router.post("/shadow/gates")
def gate_create(
    to_mode: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("mode_gate.create")),  # noqa: B008
) -> RedirectResponse:
    try:
        gates.create_gate(
            rt.engine, rt.clock, org_id=user.org_id, actor=Actor(user.id, user.role.value), to_mode=to_mode
        )
    except gates.GateError as exc:
        return _redirect("/console/shadow", exc)
    return _redirect("/console/shadow")


@router.post("/shadow/gates/{gate_id}/sign")
def gate_sign(
    gate_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("mode_gate.create")),  # noqa: B008
) -> RedirectResponse:
    try:
        gates.sign_gate(
            rt.engine, rt.clock, org_id=user.org_id, gate_id=gate_id, actor=Actor(user.id, user.role.value)
        )
    except gates.GateError as exc:
        if exc.status == 404:
            raise HTTPException(status_code=404) from None
        return _redirect("/console/shadow", exc)
    return _redirect("/console/shadow")


# ------------------------------------------------------------------------------------------ EXC-09
@router.get("/agreement", response_class=HTMLResponse)
def agreement_page(
    request: Request,
    days: int = 30,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    from detent.exceptions.agreement import sample

    days = max(1, min(days, 366))
    end = rt.clock.now() + timedelta(microseconds=1)  # include a case resolved at this instant
    with rt.engine.connect() as conn:
        s = sample(conn, user.org_id, end - timedelta(days=days), end)
    return page(request, rt, "agreement.html", user, s=s, days=days)
