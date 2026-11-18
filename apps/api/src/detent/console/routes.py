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


# ---------------------------------------------------------------------------------- S3: review loop
SECTIONS_NOT_BUILT = {
    "reconciliation": ("Reconciliation", "Matching deposits and payouts across rails (LED-06, slice S6)."),
    "rails": ("Rails", "Rail health, routing weights and circuits (RAL-06, RAL-08)."),
    "policy": ("Policy", "Rule versions, diffs and two-person approval (POL-07, slice S6)."),
    "mandates": ("Mandates", "Signed agent mandates and revocation (MND-01 to MND-03, slice S5)."),
    "audit": ("Audit", "Searchable audit log, replay and evidence export (AUD-02, AUD-03)."),
    "evaluation": ("Evaluation", "Release-gate suites and the results report (EVL, slice S8)."),
    "settings": ("Settings", "Mode, fail-safe and kill switch settings (EXE-08, EXE-09)."),
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
                "c.name AS payee FROM payment_intents p LEFT JOIN counterparties c ON c.org_id = p.org_id "
                "AND c.id = p.counterparty_id WHERE p.org_id=:o AND (CAST(:s AS text) IS NULL OR p.status "
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
    from detent.intents.service import payment_view

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
    return page(request, rt, "payment_detail.html", user, p=view, explorer=expl)


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
                "u.display_name AS owner_name, p.amount_minor, p.currency FROM exception_cases c "
                "LEFT JOIN users u ON u.org_id = c.org_id AND u.id = c.owner_id "
                "LEFT JOIN payment_intents p ON p.org_id = c.org_id AND p.id = c.payment_id "
                "WHERE c.org_id=:o AND c.status IN ('OPEN','HELD_OVERDUE') "
                "AND (CAST(:own AS text) IS NULL OR c.owner_id = :own) "
                "AND (CAST(:tier AS int) IS NULL OR c.tier = :tier) "
                "AND (NOT :ovd OR c.deadline_at < :now) ORDER BY c.deadline_at, c.id"
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
            "late": r.deadline_at < now,
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
    """EXC-02: what the reviewer reads first, straight from the registry and the decision."""
    from web3 import Web3

    from detent.domain.money import Currency, Money

    p = conn.execute(
        text(
            "SELECT p.*, c.name AS payee, c.kyb_status, c.allowlisted, c.payment_count, "
            "c.median_amount_minor, "
            "c.median_currency, d.address, d.account_masked, d.network AS d_network, d.first_seen_at, "
            "d.last_changed_at, d.last_changed_by, d.verified FROM payment_intents p "
            "LEFT JOIN counterparties c ON c.org_id = p.org_id AND c.id = p.counterparty_id "
            "LEFT JOIN destinations d ON d.org_id = p.org_id AND d.id = p.destination_id "
            "WHERE p.org_id=:o AND p.id=:p"
        ),
        {"o": org_id, "p": case.payment_id},
    ).one()
    dec = conn.execute(
        text(
            "SELECT checks FROM decisions WHERE org_id=:o AND payment_id=:p ORDER BY decided_at DESC, id "
            "DESC LIMIT 1"
        ),
        {"o": org_id, "p": case.payment_id},
    ).scalar_one()
    amount = Money(int(p.amount_minor), Currency(p.currency))
    median = (
        Money(int(p.median_amount_minor), Currency(p.median_currency))
        if p.median_amount_minor is not None
        else None
    )
    ratio = None
    if median is not None and median.currency == amount.currency and median.amount_minor:
        from decimal import Decimal

        ratio = str((Decimal(amount.amount_minor) / Decimal(median.amount_minor)).quantize(Decimal("0.01")))
    hits = [c for c in dec if c.get("result") in ("ESCALATE", "BLOCK")]
    return {
        "payee": p.payee,
        "kyb": p.kyb_status,
        "allowlisted": p.allowlisted,
        "address": Web3.to_checksum_address(p.address) if p.address else None,
        "account_masked": p.account_masked,
        "network": p.d_network or p.network_constraint,
        "verified": p.verified,
        "first_seen": p.first_seen_at,
        "last_changed": p.last_changed_at,
        "changed_by": p.last_changed_by,
        "amount": str(amount),
        "median": str(median) if median else None,
        "ratio": ratio,
        "payment_count": p.payment_count,
        "hits": hits,
        "mandate": p.mandate_id,
        "source": p.source,
        "reference": p.reference,
        "initiated_by": p.initiated_by,
    }


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
                "WHERE c.org_id=:o AND c.id=:c"
            ),
            {"o": user.org_id, "c": case_id},
        ).one_or_none()
        if case is None:
            raise HTTPException(status_code=404)
        facts = _raw_facts(conn, user.org_id, case)
    can = (
        allowed("exception.approve", user.role)
        and facts["initiated_by"] != user.id
        and case.status != "RESOLVED"
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
        error=request.query_params.get("error"),
    )


def _console_resolve(
    request: Request, rt: Runtime, user: ActingUser, case_id: str, reason: str, action: str
) -> Response:
    from detent.exceptions.cases import CaseError, approve, reject

    if not reason.strip():
        raise HTTPException(status_code=400, detail="a reason is required")
    fn = approve if action == "approve" else reject
    try:
        fn(
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
