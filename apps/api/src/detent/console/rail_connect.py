"""Console rail connection screens (RAL-09, prototype): connect by a mock consent screen or scoped keys."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from detent.audit.log import Actor
from detent.console.auth import ActingUser, acting_user, require_permission, runtime
from detent.console.routes import page
from detent.domain.roles import allowed
from detent.rails import connections as rc
from detent.runtime import Runtime

router = APIRouter(prefix="/console")


def _back(url: str, *, error: Exception | None = None, note: str | None = None) -> RedirectResponse:
    if error is not None:
        url += f"?error={quote(str(error)[:300])}"
    elif note:
        url += f"?note={quote(note)}"
    return RedirectResponse(url, status_code=303)


@router.get("/rails/connect", response_class=HTMLResponse)
def connect_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        live = rc.connections(conn, user.org_id)
        past = rc.history(conn, user.org_id)
    return page(
        request,
        rt,
        "rail_connect.html",
        user,
        catalogue=rc.catalogue(),
        live=live,
        past=past,
        can_connect=allowed("rail.connect", user.role),
        error=request.query_params.get("error"),
        note=request.query_params.get("note"),
    )


@router.get("/rails/connect/{rail_id}", response_class=HTMLResponse, response_model=None)
def consent_page(
    rail_id: str,
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("rail.connect")),  # noqa: B008
) -> HTMLResponse | RedirectResponse:
    try:
        c = rc.find(rail_id)
    except rc.ConnectionError_ as exc:
        return _back("/console/rails/connect", error=exc)
    needed = rc.NEEDED["evm" if c.method == "consent" else "banksim"]
    error = request.query_params.get("error")
    return page(request, rt, "rail_consent.html", user, c=c, needed=needed, error=error)


@router.post("/rails/connect/{rail_id}")
async def connect_rail(
    rail_id: str,
    request: Request,
    decision: str = Form("allow"),
    api_key: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("rail.connect")),  # noqa: B008
) -> RedirectResponse:
    if decision == "deny":
        return _back("/console/rails/connect", note=f"{rail_id} was not connected.")
    scopes = [str(s) for s in (await request.form()).getlist("scopes")]
    try:
        _, hint = rc.connect(
            rt.engine,
            rt.clock,
            rt.settings,
            org_id=user.org_id,
            actor=Actor(user.id, user.role.value),
            rail_id=rail_id,
            scopes=scopes,
            api_key=api_key or None,
        )
    except rc.ConnectionError_ as exc:
        return _back(f"/console/rails/connect/{rail_id}", error=exc)
    return _back(
        "/console/rails/connect",
        note=f"{rail_id} is connected. The credential ({hint}) is stored encrypted and won't be shown again.",
    )


@router.post("/rails/{rail_id}/disconnect")
def disconnect_rail(
    rail_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("rail.connect")),  # noqa: B008
) -> RedirectResponse:
    try:
        rc.disconnect(
            rt.engine, rt.clock, org_id=user.org_id, actor=Actor(user.id, user.role.value), rail_id=rail_id
        )
    except rc.ConnectionError_ as exc:
        return _back("/console/rails/connect", error=exc)
    return _back(
        "/console/rails/connect",
        note=f"{rail_id} is disconnected: its credential is removed and it is out of routing.",
    )
