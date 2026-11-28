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
    dashboard_member,
    demo_only,
    list_users,
    load_user,
    require_login,
    require_permission,
    runtime,
)
from detent.db.engine import transaction
from detent.db.repo import OrgScoped
from detent.db.tables import kill_switch
from detent.demo.generations import active_org, agent_key_for
from detent.domain.roles import Role
from detent.intents.registry import update_destination
from detent.runtime import Runtime
from detent.sandbox.generations import visible

log = logging.getLogger("detent.console")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
router = APIRouter(prefix="/console")


def _kill_switch_engaged(rt: Runtime, user: ActingUser | None) -> bool:
    with rt.engine.connect() as conn:
        org_id = user.org_id if user is not None else active_org(conn, rt.settings.demo_org_id)
        repo = OrgScoped(conn, org_id)
        v = conn.execute(repo.select(kill_switch, kill_switch.c.engaged)).scalar_one_or_none()
    return bool(v)


def _sev1(rt: Runtime, user: ActingUser | None) -> list[Any]:
    """EXE-10: a red banner on every page while a Sev 1 incident is open."""
    from detent.incidents.records import open_sev1

    if user is None:
        return []
    with rt.engine.connect() as conn:
        return open_sev1(conn, user.org_id)


def page(request: Request, rt: Runtime, name: str, user: ActingUser | None, **ctx: Any) -> HTMLResponse:
    from detent.dashboard.web import csrf_token

    member_mode = bool(user and user.via_dashboard)
    base = {
        "brand": rt.settings.brand_name,
        "user": user,
        "kill_switch_engaged": _kill_switch_engaged(rt, user),
        "sev1_incidents": _sev1(rt, user),
        # DSH-09: a dashboard member sees their own organisation, without the demo-only controls.
        "dashboard": member_mode,
        "dashboard_csrf": csrf_token(request) if member_mode else "",
        "demo_mode": rt.settings.is_demo and not member_mode,
        "now": rt.clock.now(),
        "demo_steps": list(DEMO_STEPS),
        "hosting_region": rt.settings.hosting_region,
        "database_region": rt.settings.database_region,
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
def act_as_form(request: Request, rt: Runtime = Depends(runtime)) -> Response:  # noqa: B008
    if dashboard_member(request, rt) is not None:  # members act as themselves only (DSH-09)
        return RedirectResponse("/console/", status_code=303)
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
    if dashboard_member(request, rt) is not None:
        raise HTTPException(status_code=404)
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
    from detent.console.overview import overview_stats

    with rt.engine.connect() as conn:
        stats = overview_stats(conn, user.org_id, rt.clock.now())
    return page(request, rt, "overview.html", user, s=stats)


@router.get("/overview/stats", response_class=HTMLResponse)
def overview_stats_partial(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    """CON-02: the numbers alone, polled by htmx every few seconds."""
    from detent.console.overview import overview_stats

    with rt.engine.connect() as conn:
        stats = overview_stats(conn, user.org_id, rt.clock.now())
    return templates.TemplateResponse(request, "overview_stats.html", {"s": stats, "now": rt.clock.now()})


@router.post("/clock/advance")
def advance_clock(
    request: Request,
    step: str = Form(...),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("demo.clock.advance")),  # noqa: B008
) -> RedirectResponse:
    # Outside demo mode the control does not exist at all.
    demo_only(user)
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


# ---------------------------------------------------------------------------------- S3: review loop
SECTIONS_NOT_BUILT = {
    "evaluation": ("Evaluation", "Release-gate suites and the results report (EVL, slice S8)."),
}


def _countdown(deadline: Any, now: Any) -> str:
    secs = int((deadline - now).total_seconds())
    late = secs < 0
    secs = abs(secs)
    h, m = secs // 3600, (secs % 3600) // 60
    return f"overdue by {h}h {m}m" if late else f"{h}h {m}m left"


@router.get("/payments", response_class=HTMLResponse)
def payments(
    request: Request,
    status: str | None = None,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT p.id, p.status, p.amount_minor, p.currency, p.source, p.reference, p.created_at, "
                "p.user_account_ref, c.name AS payee FROM payment_intents p "
                "LEFT JOIN counterparties c ON c.org_id = p.org_id AND c.id = p.counterparty_id "
                "WHERE p.org_id=:o "
                "AND p.generation = (SELECT data_generation FROM organisations WHERE org_id = :o) "
                "AND (CAST(:s AS text) IS NULL OR p.status "
                "= :s) "
                "ORDER BY p.created_at DESC, p.id DESC LIMIT 200"
            ),
            {"o": user.org_id, "s": status},
        ).all()
    from detent.domain.money import Currency, Money

    items = [{**r._mapping, "amount": str(Money(int(r.amount_minor), Currency(r.currency)))} for r in rows]
    return page(request, rt, "payments.html", user, payments=items, status=status)


@router.get("/payments/{payment_id}", response_class=HTMLResponse)
def payment_detail(
    request: Request,
    payment_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    from detent.views.payments import payment_view

    with rt.engine.connect() as conn:
        view = payment_view(conn, user.org_id, payment_id, detail=True)
        if view is None:
            raise HTTPException(status_code=404)
        expl = {
            r.id: r.explorer_url
            for r in conn.execute(
                text("SELECT id, explorer_url FROM attempts WHERE org_id=:o AND payment_id=:p"),
                {"o": user.org_id, "p": payment_id},
            )
        }
        from detent.execution.modes import current_mode

        mode = current_mode(conn, user.org_id)
        initiator = conn.execute(
            text("SELECT initiated_by FROM payment_intents WHERE org_id=:o AND id=:p"),
            {"o": user.org_id, "p": payment_id},
        ).scalar_one()
    from detent.domain.roles import allowed

    can_send = (
        view["status"] == "READY"
        and view.get("awaiting_send_click")
        and mode != "shadow"
        and allowed("exception.approve", user.role)
        and initiator != user.id
    )
    return page(
        request,
        rt,
        "payment_detail.html",
        user,
        p=view,
        explorer=expl,
        mode=mode,
        can_send=can_send,
        can_cancel=view["status"] in ("ESCALATED", "HELD", "READY") and allowed("payment.cancel", user.role),
        error=request.query_params.get("error"),
    )


@router.post("/payments/{payment_id}/cancel")
def console_cancel(
    request: Request,
    payment_id: str,
    reason: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("payment.cancel")),  # noqa: B008
) -> Response:
    """INT-05: cancel an escalated, held or ready payment; it is never sent."""
    from urllib.parse import quote

    from detent.intents.cancel import CancelError, cancel_intent

    with rt.engine.connect() as conn:
        if not visible(conn, "payment_intents", user.org_id, payment_id):
            raise HTTPException(status_code=404)
    try:
        cancel_intent(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            payment_id=payment_id,
            actor=Actor(user.id, user.role.value),
            reason=reason,
        )
    except CancelError as exc:
        return RedirectResponse(
            f"/console/payments/{payment_id}?error={quote(str(exc)[:300])}", status_code=303
        )
    return RedirectResponse(f"/console/payments/{payment_id}", status_code=303)


@router.post("/payments/{payment_id}/send")
def console_send(
    request: Request,
    payment_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("exception.approve")),  # noqa: B008
) -> Response:
    """EXE-09 Assist mode: a person clicks Send (G-09: never the initiator)."""
    from detent.execution.modes import ModeError, confirm_send

    with rt.engine.connect() as conn:
        if not visible(conn, "payment_intents", user.org_id, payment_id):  # SBX-04: an earlier generation
            raise HTTPException(status_code=404)
    try:
        confirm_send(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            payment_id=payment_id,
            actor=Actor(user.id, user.role.value),
        )
    except ModeError as exc:
        return RedirectResponse(f"/console/payments/{payment_id}?error={exc.code}", status_code=303)
    return RedirectResponse(f"/console/payments/{payment_id}", status_code=303)


@router.get("/exceptions", response_class=HTMLResponse)
def exceptions_queue(
    request: Request,
    owner: str | None = None,
    tier: int | None = None,
    overdue: int | None = None,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    now = rt.clock.now()
    with rt.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.id, c.payment_id, c.type, c.tier, c.reasons, c.owner_id, c.deadline_at, c.status, "
                "u.display_name AS owner_name, p.amount_minor, p.currency, p.user_account_ref, "
                "cp.name AS payee FROM exception_cases c "
                "LEFT JOIN counterparties cp ON cp.org_id = c.org_id AND cp.id = ("
                "SELECT counterparty_id FROM payment_intents WHERE org_id = c.org_id AND id = c.payment_id) "
                "LEFT JOIN users u ON u.org_id = c.org_id AND u.id = c.owner_id "
                "LEFT JOIN payment_intents p ON p.org_id = c.org_id AND p.id = c.payment_id "
                "WHERE c.org_id=:o AND c.status IN ('OPEN','HELD_OVERDUE') "
                "AND c.generation = (SELECT data_generation FROM organisations WHERE org_id = :o) "
                "AND (CAST(:own AS text) IS NULL OR c.owner_id = :own) "
                "AND (CAST(:tier AS int) IS NULL OR c.tier = :tier) "
                "AND (NOT :ovd OR c.deadline_at < :now OR c.status = 'HELD_OVERDUE') ORDER BY "
                "c.deadline_at, c.id"
            ),
            {"o": user.org_id, "own": owner, "tier": tier, "ovd": bool(overdue), "now": now},
        ).all()
        owners = conn.execute(
            text("SELECT id, display_name FROM users WHERE org_id=:o ORDER BY display_name"),
            {"o": user.org_id},
        ).all()
    from detent.domain.money import Currency, Money

    cases = [
        {
            **r._mapping,
            "countdown": _countdown(r.deadline_at, now),
            "late": r.deadline_at < now or r.status == "HELD_OVERDUE",
            "amount": str(Money(int(r.amount_minor), Currency(r.currency)))
            if r.amount_minor is not None
            else "",
        }
        for r in rows
    ]
    return page(
        request,
        rt,
        "exceptions.html",
        user,
        cases=cases,
        owners=owners,
        filters={"owner": owner, "tier": tier, "overdue": overdue},
    )


def _raw_facts(conn: Any, org_id: str, case: Any) -> dict[str, Any]:
    """EXC-02: what the reviewer reads first (shared with the API, EXC-08)."""
    from detent.views.cases import raw_facts

    return raw_facts(conn, org_id, case.payment_id)


def _deposit_case_page(request: Request, rt: Runtime, user: ActingUser, conn: Any, case: Any) -> HTMLResponse:
    """LED-05/LED-06: a deposit or reconciliation case. It is resolved by approving its fix."""
    inb = conn.execute(
        text("SELECT * FROM inbound_transfers WHERE org_id=:o AND id=:i"),
        {"o": user.org_id, "i": case.deposit_id},
    ).one_or_none()
    brk = conn.execute(
        text(
            "SELECT id, kind, status, proposed_fix FROM recon_breaks WHERE org_id=:o AND case_id=:c "
            "ORDER BY created_at DESC"
        ),
        {"o": user.org_id, "c": case.id},
    ).all()
    return page(
        request,
        rt,
        "deposit_case.html",
        user,
        case=case,
        inb=inb,
        breaks=brk,
        countdown=_countdown(case.deadline_at, rt.clock.now()),
    )


@router.get("/exceptions/{case_id}", response_class=HTMLResponse)
def case_page(
    request: Request,
    case_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    from detent.domain.roles import allowed

    with rt.engine.connect() as conn:
        case = conn.execute(
            text(
                "SELECT c.*, u.display_name AS owner_name, b.display_name AS backup_name FROM "
                "exception_cases c "
                "LEFT JOIN users u ON u.org_id = c.org_id AND u.id = c.owner_id "
                "LEFT JOIN users b ON b.org_id = c.org_id AND b.id = c.backup_owner_id "
                "WHERE c.org_id=:o AND c.id=:c "
                "AND c.generation = (SELECT data_generation FROM organisations WHERE org_id = :o)"
            ),
            {"o": user.org_id, "c": case_id},
        ).one_or_none()
        if case is None:
            raise HTTPException(status_code=404)
        if case.payment_id is None:
            return _deposit_case_page(request, rt, user, conn, case)
        facts = _raw_facts(conn, user.org_id, case)
        from detent.agents.investigation import latest_investigation

        inv = latest_investigation(conn, user.org_id, case.id)
    overdue = case.status == "HELD_OVERDUE" or rt.clock.now() >= case.deadline_at
    can = (
        allowed("exception.approve", user.role)
        and facts["initiated_by"] != user.id
        and case.status != "RESOLVED"
        # G-05: after the deadline only the current owner or the payments lead may approve.
        and (not overdue or user.role is Role.PAYMENTS_LEAD or user.id == case.owner_id)
    )
    return page(
        request,
        rt,
        "case.html",
        user,
        case=case,
        f=facts,
        countdown=_countdown(case.deadline_at, rt.clock.now()),
        can_decide=can,
        overdue=overdue,
        inv=inv,
        error=request.query_params.get("error"),
    )


def _console_resolve(
    request: Request, rt: Runtime, user: ActingUser, case_id: str, reason: str, action: str
) -> Response:
    from detent.exceptions.cases import CaseError, approve, reject

    if not reason.strip():
        raise HTTPException(status_code=400, detail="a reason is required")
    with rt.engine.connect() as conn:
        if not visible(conn, "exception_cases", user.org_id, case_id):  # SBX-04: an earlier generation
            raise HTTPException(status_code=404)
    try:
        if action == "approve":
            approve(
                rt.engine,
                rt.clock,
                case_id=case_id,
                org_id=user.org_id,
                actor=Actor(user.id, user.role.value),
                reason=reason,
                mandate_key=rt.settings.mandate_signing_key_demo,
            )
        else:
            reject(
                rt.engine,
                rt.clock,
                case_id=case_id,
                org_id=user.org_id,
                actor=Actor(user.id, user.role.value),
                reason=reason,
            )
    except CaseError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
    return RedirectResponse(f"/console/exceptions/{case_id}", status_code=303)


@router.post("/exceptions/{case_id}/approve")
def console_approve(
    request: Request,
    case_id: str,
    reason: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("exception.approve")),  # noqa: B008
) -> Response:
    return _console_resolve(request, rt, user, case_id, reason, "approve")


@router.post("/exceptions/{case_id}/reject")
def console_reject(
    request: Request,
    case_id: str,
    reason: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("exception.reject")),  # noqa: B008
) -> Response:
    return _console_resolve(request, rt, user, case_id, reason, "reject")


@router.get("/outbox", response_class=HTMLResponse)
def outbox(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        msgs = conn.execute(
            text(
                "SELECT channel, recipient, template, body, created_at, sent_at FROM outbox WHERE org_id=:o "
                "ORDER BY created_at DESC, id DESC LIMIT 200"
            ),
            {"o": user.org_id},
        ).all()
    return page(request, rt, "outbox.html", user, messages=msgs)


@router.post("/kill_switch/engage")
def console_engage(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("kill_switch.engage")),  # noqa: B008
) -> RedirectResponse:
    from detent.execution.kill_switch import engage

    engage(rt.engine, rt.clock, org_id=user.org_id, actor=Actor(user.id, user.role.value))
    return RedirectResponse(request.headers.get("referer") or "/console/", status_code=303)


@router.post("/kill_switch/release")
def console_release(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("kill_switch.release")),  # noqa: B008
) -> RedirectResponse:
    from detent.execution.kill_switch import release

    release(
        rt.engine,
        rt.clock,
        org_id=user.org_id,
        actor=Actor(user.id, user.role.value),
        mandate_key=rt.settings.mandate_signing_key_demo,
    )
    return RedirectResponse(request.headers.get("referer") or "/console/", status_code=303)


@router.get("/rails", response_class=HTMLResponse)
def rails_screen(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    """CON-08: per rail, the network or currency, balance, pre-funded limit usage and the last 20 attempts.

    RAL-08 adds the rolling success rate, p95 latency and the circuit breaker's state."""
    from detent.domain.money import Currency, Money
    from detent.rails.health import is_open as rail_is_open
    from detent.rails.health import stats as rail_stats
    from detent.rails.registry import build_adapters

    day = rt.clock.now().date().isoformat()
    try:
        adapters = build_adapters(rt.settings, rt.engine, user.org_id, clock=rt.clock)
    except Exception:  # an unreachable RPC must not take the screen down
        adapters = {}
    with rt.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM rails WHERE org_id=:o ORDER BY kind, id"), {"o": user.org_id}
        ).all()
        rails = []
        for r in rows:
            used = (
                conn.execute(
                    text("SELECT amount_minor FROM counters WHERE org_id=:o AND scope=:s AND period=:d"),
                    {"o": user.org_id, "s": f"prefund:{r.id}", "d": day},
                ).scalar_one_or_none()
                or 0
            )
            usage = None
            if r.prefunded_daily_limit_minor:
                lim = Money(int(r.prefunded_daily_limit_minor), Currency(r.currency))
                pct = int(used) * 100 // int(r.prefunded_daily_limit_minor)
                spent = Money(int(used), Currency(r.currency)).to_decimal_str()
                usage = f"{spent} of {lim.to_decimal_str()} {r.currency} ({pct}%)"
            attempts = conn.execute(
                text(
                    "SELECT a.id, a.payment_id, a.status, a.failure_class, a.tx_hash, a.explorer_url, "
                    "a.created_at "
                    "FROM attempts a WHERE a.org_id=:o AND a.rail_id=:r ORDER BY a.created_at DESC, a.id "
                    "DESC LIMIT 20"
                ),
                {"o": user.org_id, "r": r.id},
            ).all()
            balance = None
            a = adapters.get(r.id)
            if a is not None:
                try:
                    h = a.health()
                    balance = str(h.balance) if h.balance is not None else ("reachable" if h.ok else None)
                except Exception:
                    balance = None
            ppl = (
                str(Money(int(r.per_payment_limit_minor), Currency(r.currency)))
                if r.per_payment_limit_minor is not None
                else None
            )
            rails.append(
                {
                    "row": r,
                    "usage": usage,
                    "attempts": attempts,
                    "balance": balance,
                    "per_payment": ppl,
                    "health": rail_stats(conn, user.org_id, r.id),
                    "circuit_open": rail_is_open(conn, user.org_id, r),
                }
            )
    return page(request, rt, "rails.html", user, rails=rails)


@router.get("/mandates", response_class=HTMLResponse)
def mandates_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    from detent.domain.roles import allowed
    from detent.mandates.store import list_mandates

    with rt.engine.connect() as conn:
        items = list_mandates(conn, user.org_id)
    return page(
        request, rt, "mandates.html", user, mandates=items, can_revoke=allowed("mandate.revoke", user.role)
    )


@router.post("/mandates/{mandate_id}/revoke")
def console_revoke_mandate(
    request: Request,
    mandate_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("mandate.revoke")),  # noqa: B008
) -> RedirectResponse:
    from detent.mandates.store import revoke_mandate

    try:
        with transaction(rt.engine) as conn:
            revoke_mandate(conn, rt.clock, user.org_id, mandate_id, actor=Actor(user.id, user.role.value))
    except LookupError as exc:
        raise HTTPException(status_code=404) from exc
    return RedirectResponse("/console/mandates", status_code=303)


# ---------------------------------------------------------------------------------- CON-05 invoices
def _mandates_in_force(conn: Any, org_id: str, now: Any) -> list[Any]:
    rows = conn.execute(
        text(
            "SELECT id, agent_id, payload FROM mandates WHERE org_id=:o AND revoked_at IS NULL "
            "AND valid_from <= :t AND expires_at >= :t ORDER BY created_at, id"
        ),
        {"o": org_id, "t": now},
    ).all()
    return list(rows)


def _highlight(doc: str, proposal: dict[str, Any]) -> Any:
    from markupsafe import Markup, escape

    spans = sorted(
        (v["source_span"][0], v["source_span"][1], k)
        for k, v in proposal.items()
        if v.get("source_span") and v["value"] is not None
    )
    out, pos = [], 0
    for s, e, k in spans:
        if s < pos:
            continue  # overlapping spans: keep the first
        out.append(escape(doc[pos:s]))
        out.append(Markup('<mark title="{}">').format(k) + escape(doc[s:e]) + Markup("</mark>"))
        pos = e
    out.append(escape(doc[pos:]))
    return Markup("").join(out)


@router.get("/invoices", response_class=HTMLResponse)
def invoices(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    demo_only(user)
    with rt.engine.connect() as conn:
        mandates = _mandates_in_force(conn, user.org_id, rt.clock.now())
        recent = conn.execute(
            text(
                "SELECT id, status, created_at, payment_id, source FROM agent_calls WHERE org_id=:o "
                "AND kind='instruction' ORDER BY created_at DESC, id DESC LIMIT 20"
            ),
            {"o": user.org_id},
        ).all()
    return page(request, rt, "invoices.html", user, mandates=mandates, recent=recent)


@router.post("/invoices")
async def drop_invoice(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> RedirectResponse:
    demo_only(user)
    from starlette.concurrency import run_in_threadpool

    form = await request.form()
    doc = str(form.get("text") or "")
    upload = form.get("file")
    if upload is not None and hasattr(upload, "read"):
        data = await upload.read()
        if data[:4] == b"%PDF":
            doc = await run_in_threadpool(_pdf_text, data)
        elif data:
            doc = data.decode("utf-8", errors="replace")
    if not doc.strip():
        raise HTTPException(status_code=400, detail="paste the invoice text or choose a file")
    return await run_in_threadpool(_propose, rt, user, doc, str(form.get("mandate_id") or ""))


def _pdf_text(data: bytes) -> str:
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _propose(rt: Runtime, user: ActingUser, doc: str, mandate_id: str) -> RedirectResponse:
    from detent.agents.instruction import fixture_placeholders, propose_from_invoice
    from detent.agents.llm import llm_for

    with rt.engine.connect() as conn:
        mandates = _mandates_in_force(conn, user.org_id, rt.clock.now())
        placeholders = fixture_placeholders(conn, user.org_id)
    mid = mandate_id or (mandates[0].id if mandates else None)
    llm, _ = llm_for(rt.settings, placeholders)
    p = propose_from_invoice(
        rt.engine,
        rt.clock,
        org_id=user.org_id,
        document=doc,
        mandate_id=mid,
        llm=llm,
        model=rt.settings.model_agent,
        daily_token_budget=rt.settings.ai_daily_token_budget,
    )
    return RedirectResponse(f"/console/invoices/{p.id}", status_code=303)


@router.get("/invoices/{proposal_id}", response_class=HTMLResponse)
def proposal_page(
    request: Request,
    proposal_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    demo_only(user)
    from detent.agents.instruction import replay_proposal
    from detent.views.payments import payment_view

    with rt.engine.connect() as conn:
        try:
            p = replay_proposal(conn, user.org_id, proposal_id)
        except Exception as exc:
            raise HTTPException(status_code=404) from exc
        row = conn.execute(
            text(
                "SELECT source, resolution, resolved_by, payment_id, model, served_model FROM agent_calls "
                "WHERE org_id=:o AND id=:i"
            ),
            {"o": user.org_id, "i": proposal_id},
        ).one()
        mandate = conn.execute(
            text("SELECT id, payload, revoked_at FROM mandates WHERE org_id=:o AND id=:m"),
            {"o": user.org_id, "m": p.mandate_id},
        ).one_or_none()
        payment = payment_view(conn, user.org_id, row.payment_id) if row.payment_id else None
    label = (
        "Claude API"
        if row.source == "model"
        else "Recorded response (offline stand-in, not a live model call)"
    )
    return page(
        request,
        rt,
        "proposal.html",
        user,
        p=p,
        row=row,
        label=label,
        mandate=mandate,
        payment=payment,
        highlighted=_highlight(p.document, p.proposal),
        error=request.query_params.get("error"),
    )


@router.post("/invoices/{proposal_id}/resolve")
async def resolve_proposal(
    request: Request,
    proposal_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("exception.approve")),  # noqa: B008
) -> RedirectResponse:
    demo_only(user)
    from detent.agents.submit import NotReady, resolve_flags

    form = await request.form()
    values = {k[6:]: str(v).strip() for k, v in form.items() if k.startswith("value_") and str(v).strip()}
    try:
        resolve_flags(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            proposal_id=proposal_id,
            actor=Actor(user.id, user.role.value),
            values=values,
            note=str(form.get("note") or ""),
        )
    except (ValueError, NotReady) as exc:
        from urllib.parse import quote

        return RedirectResponse(f"/console/invoices/{proposal_id}?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(f"/console/invoices/{proposal_id}", status_code=303)


@router.post("/invoices/{proposal_id}/submit")
def submit_as_agent(
    request: Request,
    proposal_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> RedirectResponse:
    """'Submit as agent': the proposal goes through the public API with the agent's own key."""
    demo_only(user)
    from fastapi.testclient import TestClient

    from detent.agents.submit import NotReady, submit_proposal

    key = agent_key_for(rt.settings, user.org_id)
    if key is None:
        raise HTTPException(status_code=409, detail="the agent's API key is not configured (AGENT_API_KEY)")
    try:
        # An in-process HTTP client: the request passes through the whole /v1 stack (key, scope, mandate).
        with TestClient(request.app, raise_server_exceptions=True) as http:
            r = submit_proposal(
                rt.engine,
                rt.clock,
                http,
                agent_key=key.get_secret_value(),
                org_id=user.org_id,
                proposal_id=proposal_id,
            )
    except NotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if r.status_code not in (200, 201):
        from urllib.parse import quote

        return RedirectResponse(
            f"/console/invoices/{proposal_id}?error={quote(r.text[:300])}", status_code=303
        )
    return RedirectResponse(f"/console/invoices/{proposal_id}", status_code=303)


# ------------------------------------------------------------------------------- CON-06 / POL-07 policy
@router.get("/policy", response_class=HTMLResponse)
def policy_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    from detent.domain.roles import allowed
    from detent.policy.changes import draft_diff, get_version, list_versions

    with rt.engine.connect() as conn:
        versions = list_versions(conn, user.org_id)
        active = next((v for v in versions if v["status"] == "active"), None)
        active_full = get_version(conn, user.org_id, active["version"]) if active else None
        draft_row = next((v for v in versions if v["status"] == "draft"), None)
        draft = get_version(conn, user.org_id, draft_row["version"]) if draft_row else None
        changes = draft_diff(conn, user.org_id, draft) if draft else []
        people = conn.execute(
            text("SELECT id, display_name, role FROM users WHERE org_id=:o"), {"o": user.org_id}
        ).all()
    names = {u.id: u.display_name for u in people}
    roles = {u.id: u.role for u in people}
    next_version = (max((v["version"] for v in versions), default=0)) + 1
    template_yaml = ""
    if active_full:
        import re as _re

        template_yaml = _re.sub(
            r"(?m)^version:\s*\d+", f"version: {next_version}", active_full["yaml"], count=1
        )
    can_approve = (
        draft is not None
        and allowed("policy.approve", user.role)
        and draft["proposed_by"] != user.id
        # C-06: the compliance lead is one of the two people on every activation.
        and Role.COMPLIANCE_LEAD.value in {roles.get(draft["proposed_by"]), user.role.value}
    )
    return page(
        request,
        rt,
        "policy.html",
        user,
        versions=versions,
        active=active_full,
        draft=draft,
        changes=changes,
        names=names,
        can_propose=allowed("policy.propose", user.role) and draft is None,
        can_approve=can_approve,
        template_yaml=template_yaml,
        error=request.query_params.get("error"),
    )


def _policy_redirect(exc: Exception | None = None) -> RedirectResponse:
    from urllib.parse import quote

    url = "/console/policy" + (f"?error={quote(str(exc)[:300])}" if exc else "")
    return RedirectResponse(url, status_code=303)


@router.post("/policy/propose")
def console_propose_policy(
    request: Request,
    yaml_text: str = Form(""),
    attest: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("policy.propose")),  # noqa: B008
) -> RedirectResponse:
    from detent.policy.changes import ChangeError, propose_draft

    try:
        propose_draft(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            actor=Actor(user.id, user.role.value),
            yaml_text=yaml_text.replace("\r\n", "\n"),
            attest=attest == "yes",
        )
    except ChangeError as exc:
        return _policy_redirect(exc)
    return _policy_redirect()


@router.post("/policy/{draft_id}/approve")
def console_approve_policy(
    request: Request,
    draft_id: str,
    attest: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("policy.approve")),  # noqa: B008
) -> RedirectResponse:
    from detent.policy.changes import ChangeError, approve_draft

    try:
        approve_draft(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            draft_id=draft_id,
            actor=Actor(user.id, user.role.value),
            attest=attest == "yes",
        )
    except ChangeError as exc:
        return _policy_redirect(exc)
    return _policy_redirect()


@router.post("/policy/{draft_id}/withdraw")
def console_withdraw_policy(
    request: Request,
    draft_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("policy.propose")),  # noqa: B008
) -> RedirectResponse:
    from detent.policy.changes import ChangeError, withdraw_draft

    try:
        withdraw_draft(
            rt.engine, rt.clock, org_id=user.org_id, draft_id=draft_id, actor=Actor(user.id, user.role.value)
        )
    except ChangeError as exc:
        return _policy_redirect(exc)
    return _policy_redirect()


# ------------------------------------------------------------------------------------ EXE-09 settings
@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    from detent.domain.roles import allowed, mode_change_approved
    from detent.execution.modes import current_mode, orchestrate_status, pending_mode_change

    with rt.engine.connect() as conn:
        mode = current_mode(conn, user.org_id)
        pending = pending_mode_change(conn, user.org_id)
        orch = orchestrate_status(conn, user.org_id)
        fail_safe = conn.execute(
            text("SELECT fail_safe FROM organisations WHERE org_id=:o"), {"o": user.org_id}
        ).scalar_one()
        history = conn.execute(
            text("SELECT * FROM mode_changes WHERE org_id=:o ORDER BY created_at DESC, id DESC LIMIT 10"),
            {"o": user.org_id},
        ).all()
        # CON-10: the fail-safe changes like the mode; deadlines and weights are shown read-only.
        fs_pending = pending_mode_change(conn, user.org_id, "fail_safe")
        from detent.policy.store import NoActivePolicy, active_policy
        from detent.routing.engine import DEFAULT_WEIGHTS

        try:
            pol = active_policy(conn, user.org_id)
            deadlines, policy_version = dict(pol.rules.deadlines), pol.version
        except NoActivePolicy:
            deadlines, policy_version = {}, None
        ready_gates = conn.execute(
            text(
                "SELECT id, to_mode FROM mode_gates WHERE org_id=:o AND from_mode=:m AND passed "
                "AND payments_lead_id IS NOT NULL AND compliance_lead_id IS NOT NULL AND "
                "mode_change_id IS NULL "
                "ORDER BY created_at DESC"
            ),
            {"o": user.org_id, "m": mode},
        ).all()
        rail_weights = conn.execute(
            text("SELECT id, weights FROM rails WHERE org_id=:o AND weights IS NOT NULL ORDER BY id"),
            {"o": user.org_id},
        ).all()

    def approvable(p: Any) -> bool:
        return p is not None and mode_change_approved(
            proposer=(p.proposed_by, Role(p.proposed_role)), approver=(user.id, user.role)
        )

    can_approve = approvable(pending)
    lead = allowed("org.change_mode.propose", user.role)
    return page(
        request,
        rt,
        "settings.html",
        user,
        mode=mode,
        pending=pending,
        orch=orch,
        fail_safe=fail_safe,
        history=history,
        can_propose=lead and pending is None,
        can_approve=can_approve,
        can_withdraw=pending is not None and lead,
        fs_pending=fs_pending,
        fs_can_propose=lead and fs_pending is None,
        fs_can_approve=approvable(fs_pending),
        fs_can_withdraw=fs_pending is not None and lead,
        deadlines=deadlines,
        policy_version=policy_version,
        default_weights={k: str(v) for k, v in DEFAULT_WEIGHTS.items()},
        rail_weights=rail_weights,
        ready_gates=ready_gates,
        error=request.query_params.get("error"),
    )


def _settings_redirect(exc: Exception | None = None) -> RedirectResponse:
    from urllib.parse import quote

    return RedirectResponse(
        "/console/settings" + (f"?error={quote(str(exc)[:300])}" if exc else ""), status_code=303
    )


@router.post("/settings/mode/propose")
def console_propose_mode(
    request: Request,
    to_mode: str = Form(""),
    reason: str = Form(""),
    setting: str = Form("mode"),
    gate_id: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("org.change_mode.propose")),  # noqa: B008
) -> RedirectResponse:
    from detent.execution.modes import ModeError, propose_mode_change

    try:
        propose_mode_change(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            actor=Actor(user.id, user.role.value),
            to_mode=to_mode,
            reason=reason,
            setting=setting,
            gate_id=gate_id or None,
        )
    except ModeError as exc:
        return _settings_redirect(exc)
    return _settings_redirect()


@router.post("/settings/mode/{change_id}/approve")
def console_approve_mode(
    request: Request,
    change_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("org.change_mode.propose")),  # noqa: B008
) -> RedirectResponse:
    from detent.execution.modes import ModeError, approve_mode_change

    try:
        approve_mode_change(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            change_id=change_id,
            actor=Actor(user.id, user.role.value),
        )
    except ModeError as exc:
        return _settings_redirect(exc)
    return _settings_redirect()


@router.post("/settings/mode/{change_id}/withdraw")
def console_withdraw_mode(
    request: Request,
    change_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("org.change_mode.propose")),  # noqa: B008
) -> RedirectResponse:
    from detent.execution.modes import ModeError, withdraw_mode_change

    try:
        withdraw_mode_change(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            change_id=change_id,
            actor=Actor(user.id, user.role.value),
        )
    except ModeError as exc:
        return _settings_redirect(exc)
    return _settings_redirect()


# ------------------------------------------------------------------------------ CON-07 reconciliation
@router.get("/reconciliation", response_class=HTMLResponse)
def reconciliation_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    from detent.domain.roles import allowed
    from detent.reconciliation.run import latest_runs, list_breaks

    with rt.engine.connect() as conn:
        runs = latest_runs(conn, user.org_id)
        breaks = list_breaks(conn, user.org_id)
    return page(
        request,
        rt,
        "reconciliation.html",
        user,
        runs=runs,
        latest=runs[0] if runs else None,
        open_breaks=[b for b in breaks if b["status"] == "OPEN"],
        decided=[b for b in breaks if b["status"] != "OPEN"][:20],
        can_fix=allowed("recon.approve_fix", user.role),
        error=request.query_params.get("error"),
    )


def _recon_redirect(exc: Exception | None = None) -> RedirectResponse:
    from urllib.parse import quote

    return RedirectResponse(
        "/console/reconciliation" + (f"?error={quote(str(exc)[:300])}" if exc else ""), status_code=303
    )


@router.post("/reconciliation/run")
def console_run_reconciliation(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> RedirectResponse:
    from detent.reconciliation.run import run_for

    run_for(rt.engine, rt.clock, rt.settings, user.org_id)
    return _recon_redirect()


@router.post("/reconciliation/breaks/{break_id}/approve")
def console_approve_fix(
    request: Request,
    break_id: str,
    reason: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("recon.approve_fix")),  # noqa: B008
) -> RedirectResponse:
    from detent.reconciliation.fixes import FixError, approve_fix

    try:
        approve_fix(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            break_id=break_id,
            actor=Actor(user.id, user.role.value),
            reason=reason,
        )
    except FixError as exc:
        return _recon_redirect(exc)
    return _recon_redirect()


@router.post("/reconciliation/breaks/{break_id}/reject")
def console_reject_fix(
    request: Request,
    break_id: str,
    reason: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(require_permission("recon.approve_fix")),  # noqa: B008
) -> RedirectResponse:
    from detent.reconciliation.fixes import FixError, reject_fix

    try:
        reject_fix(
            rt.engine,
            rt.clock,
            org_id=user.org_id,
            break_id=break_id,
            actor=Actor(user.id, user.role.value),
            reason=reason,
        )
    except FixError as exc:
        return _recon_redirect(exc)
    return _recon_redirect()


# ------------------------------------------------------------------------------------ CON-09 demo runner
def _demo_enabled(rt: Runtime) -> None:
    """The scenario runner exists in the demo and on developer machines, never in the public sandbox."""
    if rt.settings.app_env == "sandbox":
        raise HTTPException(status_code=404)


@router.get("/demo", response_class=HTMLResponse)
def demo_page(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    demo_only(user)
    from detent.demo.generations import current_generation
    from detent.demo.packs import current_pack, packs
    from detent.demo.scenarios import SCENARIOS, recorded

    _demo_enabled(rt)
    with rt.engine.connect() as conn:
        gen = current_generation(conn, rt.settings.demo_org_id)
        pack = current_pack(conn, user.org_id)
    results = {sid: recorded(rt, user.org_id, sid) for sid in SCENARIOS if sid != "reset"}
    return page(
        request,
        rt,
        "demo.html",
        user,
        scenarios=list(SCENARIOS.values()),
        results=results,
        generation=gen,
        packs=packs(),
        pack=pack,
        flash=request.query_params.get("result"),
        error=request.query_params.get("error"),
    )


@router.get("/demo/invoice.txt")
def demo_invoice(
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> Response:
    """The $18,500 invoice as the fictional supplier sent it, for dropping on the Invoices screen."""
    demo_only(user)
    from detent.demo.scenarios import CANONICAL_INVOICE, demo_document

    _demo_enabled(rt)
    body = demo_document(rt, user.org_id, CANONICAL_INVOICE)
    return Response(
        body,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="bluefin-invoice-18500-usdc.txt"'},
    )


@router.post("/demo/run/{scenario_id}")
def demo_run(
    request: Request,
    scenario_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> RedirectResponse:
    demo_only(user)
    from urllib.parse import quote

    from detent.demo.scenarios import SCENARIOS, ScenarioError, run_scenario

    _demo_enabled(rt)
    if scenario_id not in SCENARIOS:
        raise HTTPException(status_code=404)
    try:
        result = run_scenario(rt, user.org_id, scenario_id, Actor(user.id, user.role.value))
    except ScenarioError as exc:
        return RedirectResponse(f"/console/demo?error={quote(str(exc)[:400])}", status_code=303)
    if scenario_id == "reset":
        request.session.pop("user_id", None)  # the new generation has its own users
        return RedirectResponse("/console/act-as", status_code=303)
    note = " ".join(result.lines)[:600]
    return RedirectResponse(f"/console/demo?result={quote(note)}#{scenario_id}", status_code=303)


@router.post("/demo/reset")
def demo_reset_pack(
    request: Request,
    pack: str = Form("default"),
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> RedirectResponse:
    """DEM-06: reset into a chosen scenario pack (payments lead only, like every reset)."""
    demo_only(user)
    from urllib.parse import quote

    from detent.demo.generations import ResetRefused, reset_demo

    _demo_enabled(rt)
    try:
        reset_demo(rt, actor=Actor(user.id, user.role.value), pack=pack)
    except ResetRefused as exc:
        return RedirectResponse(f"/console/demo?error={quote(str(exc)[:400])}", status_code=303)
    request.session.pop("user_id", None)  # the new generation has its own users
    return RedirectResponse("/console/act-as", status_code=303)


@router.post("/demo/pack-batch")
def demo_pack_batch(
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> RedirectResponse:
    """DEM-06: run the current pack's short batch through the rules."""
    demo_only(user)
    from urllib.parse import quote

    from detent.demo.packs import current_pack, run_pack_batch

    _demo_enabled(rt)
    with rt.engine.connect() as conn:
        pack = current_pack(conn, user.org_id)
    rows = run_pack_batch(rt, user.org_id, Actor(user.id, user.role.value), pack)
    note = "; ".join(f"{r['ref']} {r['outcome']} (expected {r['expected']})" for r in rows)
    return RedirectResponse(f"/console/demo?result={quote(note[:600])}", status_code=303)


# ------------------------------------------------------------------------------------- AUD-02 replay
@router.get("/payments/{payment_id}/replay", response_class=HTMLResponse)
def payment_replay(
    request: Request,
    payment_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    from detent.audit.replay import NotReplayable, replay_payment

    try:
        r = replay_payment(rt.engine, rt.clock, org_id=user.org_id, payment_id=payment_id)
    except NotReplayable as exc:
        raise HTTPException(status_code=404) from exc
    return page(request, rt, "replay.html", user, r=r)


@router.get("/{section}", response_class=HTMLResponse)
def not_built(
    request: Request,
    section: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    if section not in SECTIONS_NOT_BUILT:
        raise HTTPException(status_code=404)
    title, what = SECTIONS_NOT_BUILT[section]
    return page(request, rt, "not_built.html", user, title=title, what=what)
