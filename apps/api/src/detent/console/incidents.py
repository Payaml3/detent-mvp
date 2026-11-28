"""Console Incidents screens (OPS-01, EXE-10): the list, one incident's timeline, and its actions."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from detent.audit.log import Actor
from detent.console.auth import ActingUser, acting_user, require_permission, runtime
from detent.console.routes import page
from detent.domain.roles import allowed
from detent.incidents import records
from detent.runtime import Runtime

router = APIRouter(prefix="/console")


def _back(incident_id: str | None, exc: Exception | None = None) -> RedirectResponse:
    url = f"/console/incidents/{incident_id}" if incident_id else "/console/incidents"
    return RedirectResponse(url + (f"?error={quote(str(exc)[:300])}" if exc else ""), status_code=303)


@router.get("/incidents", response_class=HTMLResponse)
def incidents_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        rows = records.list_incidents(conn, user.org_id)
    now = rt.clock.now()
    return page(
        request,
        rt,
        "incidents.html",
        user,
        incidents=rows,
        overdue={r.id for r in rows if records.notification_overdue(r, now)},
        severities=records.SEVERITIES,
        can_manage=allowed("incident.manage", user.role),
        error=request.query_params.get("error"),
    )


@router.post("/incidents", response_model=None)
def open_incident_manually(
    request: Request,
    severity: int = Form(1),
    title: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("incident.manage")),  # noqa: B008
) -> RedirectResponse:
    try:
        inc = records.open_manually(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            actor=Actor(user.id, user.role.value),
            severity=severity,
            title=title,
        )
    except records.IncidentError as exc:
        return _back(None, exc)
    return _back(inc)


@router.get("/incidents/{incident_id}", response_class=HTMLResponse)
def incident_page(
    request: Request,
    incident_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        inc = conn.execute(
            text("SELECT * FROM incidents WHERE org_id=:o AND id=:i"), {"o": user.org_id, "i": incident_id}
        ).one_or_none()
        if inc is None:
            raise HTTPException(status_code=404)
        events = records.timeline(conn, user.org_id, incident_id)
    sev = records.SEVERITIES[int(inc.severity)]
    return page(
        request,
        rt,
        "incident.html",
        user,
        inc=inc,
        sev=sev,
        events=events,
        notify_by=inc.opened_at + sev.notify_within,
        overdue=records.notification_overdue(inc, rt.clock.now()),
        replays=[e for e in events if e.kind == "replay_linked"],
        can_manage=allowed("incident.manage", user.role) and inc.status == "open",
        error=request.query_params.get("error"),
    )


def _act(incident_id: str, fn: object) -> RedirectResponse:
    try:
        fn()  # type: ignore[operator]
    except records.IncidentError as exc:
        if exc.status == 404:
            raise HTTPException(status_code=404) from None
        return _back(incident_id, exc)
    return _back(incident_id)


@router.post("/incidents/{incident_id}/notify")
def incident_notify(
    incident_id: str,
    channel: str = Form(""),
    recipient: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("incident.manage")),  # noqa: B008
) -> RedirectResponse:
    actor = Actor(user.id, user.role.value)
    return _act(
        incident_id,
        lambda: records.notify(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            incident_id=incident_id,
            actor=actor,
            channel=channel,
            recipient=recipient,
        ),
    )


@router.post("/incidents/{incident_id}/note")
def incident_note(
    incident_id: str,
    note: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("incident.manage")),  # noqa: B008
) -> RedirectResponse:
    actor = Actor(user.id, user.role.value)
    return _act(
        incident_id,
        lambda: records.add_note(
            rt.engine, rt.clock, org_id=user.org_id, incident_id=incident_id, actor=actor, note=note
        ),
    )


@router.post("/incidents/{incident_id}/root_cause")
def incident_root_cause(
    incident_id: str,
    root_cause: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("incident.manage")),  # noqa: B008
) -> RedirectResponse:
    actor = Actor(user.id, user.role.value)
    return _act(
        incident_id,
        lambda: records.set_root_cause(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            incident_id=incident_id,
            actor=actor,
            root_cause=root_cause,
        ),
    )


@router.post("/incidents/{incident_id}/replay")
def incident_replay(
    incident_id: str,
    payment_id: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("incident.manage")),  # noqa: B008
) -> RedirectResponse:
    actor = Actor(user.id, user.role.value)
    return _act(
        incident_id,
        lambda: records.link_replay(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            incident_id=incident_id,
            actor=actor,
            payment_id=payment_id.strip(),
        ),
    )


@router.post("/incidents/{incident_id}/resolve")
def incident_resolve(
    incident_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("incident.manage")),  # noqa: B008
) -> RedirectResponse:
    actor = Actor(user.id, user.role.value)
    return _act(
        incident_id,
        lambda: records.resolve(
            rt.engine, rt.clock, org_id=user.org_id, incident_id=incident_id, actor=actor
        ),
    )
