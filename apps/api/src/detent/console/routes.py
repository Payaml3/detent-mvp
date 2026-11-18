"""Back-office console routes for M0: login, act-as, overview shell, demo clock (FND-04, FND-05)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from detent.audit.log import Actor, append
from detent.clock import DEMO_STEPS, DemoClock
from detent.console.auth import (
    ActingUser,
    acting_user,
    check_password,
    list_users,
    load_user,
    require_login,
    require_permission,
    runtime,
)
from detent.db.engine import transaction
from detent.db.repo import OrgScoped
from detent.db.tables import kill_switch
from detent.intents.registry import update_destination
from detent.runtime import Runtime

log = logging.getLogger("detent.console")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
router = APIRouter(prefix="/console")


def _kill_switch_engaged(rt: Runtime) -> bool:
    with rt.engine.connect() as conn:
        repo = OrgScoped(conn, rt.settings.demo_org_id)
        v = conn.execute(repo.select(kill_switch, kill_switch.c.engaged)).scalar_one_or_none()
    return bool(v)


def page(request: Request, rt: Runtime, name: str, user: ActingUser | None, **ctx: Any) -> HTMLResponse:
    base = {
        "brand": rt.settings.brand_name,
        "user": user,
        "kill_switch_engaged": _kill_switch_engaged(rt),
        "demo_mode": rt.settings.is_demo,
        "now": rt.clock.now(),
        "demo_steps": list(DEMO_STEPS),
    }
    return templates.TemplateResponse(request, name, {**base, **ctx})


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, rt: Runtime = Depends(runtime)) -> HTMLResponse:  # noqa: B008
    return page(request, rt, "login.html", None, error=None)


@router.post("/login", response_model=None)
def login(
    request: Request,
    password: str = Form(...),
    rt: Runtime = Depends(runtime),  # noqa: B008
) -> Response:
    if not check_password(rt, password):
        log.warning("console login failed")
        return page(request, rt, "login.html", None, error="Wrong password.")
    request.session.clear()
    request.session["authed"] = True
    return RedirectResponse("/console/act-as", status_code=303)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/console/login", status_code=303)


@router.get("/act-as", response_class=HTMLResponse)
def act_as_form(request: Request, rt: Runtime = Depends(runtime)) -> HTMLResponse:  # noqa: B008
    require_login(request)
    current = request.session.get("user_id")
    return page(
        request,
        rt,
        "act_as.html",
        load_user(rt, current) if current else None,
        users=list_users(rt),
    )


@router.post("/act-as")
def act_as(
    request: Request,
    user_id: str = Form(...),
    rt: Runtime = Depends(runtime),  # noqa: B008
) -> RedirectResponse:
    require_login(request)
    user = load_user(rt, user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="unknown user")
    previous = request.session.get("user_id")
    with transaction(rt.engine) as conn:
        append(
            conn,
            rt.clock,
            org_id=user.org_id,
            actor=user.actor,
            kind="console.acting_user_selected",
            subject_id=user.id,
            payload={"previous_user_id": previous},
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/console/", status_code=303)


@router.get("/", response_class=HTMLResponse)
def overview(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    return page(request, rt, "overview.html", user)


@router.post("/clock/advance")
def advance_clock(
    request: Request,
    step: str = Form(...),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("demo.clock.advance")),  # noqa: B008
) -> RedirectResponse:
    # Outside demo mode the control does not exist at all.
    if not rt.settings.is_demo or not isinstance(rt.clock, DemoClock):
        raise HTTPException(status_code=404)
    delta = DEMO_STEPS.get(step)
    if delta is None:
        raise HTTPException(status_code=400, detail="unknown step")
    seconds = int(delta.total_seconds())
    before = rt.clock.now()
    with transaction(rt.engine) as conn:
        conn.execute(
            text(
                "INSERT INTO demo_clock (org_id, offset_seconds) VALUES (:org_id, :s) "
                "ON CONFLICT (org_id) DO UPDATE SET offset_seconds = demo_clock.offset_seconds + :s "
                "WHERE demo_clock.org_id = :org_id"
            ),
            {"org_id": user.org_id, "s": seconds},
        )
        append(
            conn,
            rt.clock,
            org_id=user.org_id,
            actor=Actor(user.id, user.role.value),
            kind="demo.clock_advanced",
            payload={"step": step, "seconds": seconds, "before": before.isoformat()},
        )
    rt.clock.invalidate()
    return RedirectResponse(request.headers.get("referer") or "/console/", status_code=303)


# ---------------------------------------------------------------------------------- INT-04 registry
@router.get("/counterparties", response_class=HTMLResponse)
def counterparties(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        cps = conn.execute(
            text(
                "SELECT id, name, kyb_status, allowlisted, jurisdiction, payment_count, median_amount_minor, "
                "median_currency FROM counterparties WHERE org_id=:o ORDER BY name"
            ),
            {"o": user.org_id},
        ).all()
        dests = conn.execute(
            text(
                "SELECT id, counterparty_id, kind, network, address, account_masked, verified, "
                "first_seen_at, "
                "last_changed_at, last_changed_by FROM destinations WHERE org_id=:o ORDER BY first_seen_at"
            ),
            {"o": user.org_id},
        ).all()
    by_cp: dict[str, list[Any]] = {}
    for d in dests:
        by_cp.setdefault(d.counterparty_id, []).append(d)
    from detent.domain.money import Currency, Money
    from detent.domain.roles import allowed

    def median(cp: Any) -> str:
        if cp.median_amount_minor is None:
            return "none yet"
        return str(Money(int(cp.median_amount_minor), Currency(cp.median_currency)))

    return page(
        request,
        rt,
        "counterparties.html",
        user,
        counterparties=cps,
        destinations=by_cp,
        median=median,
        can_edit=allowed("counterparty.edit", user.role),
    )


@router.post("/destinations/{destination_id}")
def edit_destination(
    request: Request,
    destination_id: str,
    address: str | None = Form(None),
    account_masked: str | None = Form(None),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("counterparty.edit")),  # noqa: B008
) -> RedirectResponse:
    import re

    if address is not None and not re.fullmatch(r"0x[0-9a-fA-F]{40}", address.strip()):
        raise HTTPException(status_code=400, detail="address must be a 0x-prefixed 40-hex-digit address")
    try:
        with transaction(rt.engine) as conn:
            update_destination(
                conn,
                rt.clock,
                user.org_id,
                destination_id,
                actor=Actor(user.id, user.role.value),
                address=address.strip() if address else None,
                account_masked=account_masked.strip() if account_masked else None,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404) from exc
    return RedirectResponse("/console/counterparties", status_code=303)
