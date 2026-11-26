"""Dashboard screens for a client organisation's members (DSH-02, DSH-03, DSH-11; spec/08).

Sign-in, the invite link (email verification and password), the home page with the onboarding checklist,
and the team page. There is no sign-up route: the only way in is an invite (DSH-01).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import text

from detent.audit.log import append
from detent.dashboard import access
from detent.dashboard.access import AccessError, Member
from detent.dashboard.web import (
    check_csrf,
    client_address,
    client_member,
    end_session,
    login_limiter,
    page,
    redirect,
    runtime,
    safe_next,
    start_session,
    writable_member,
)
from detent.db.engine import transaction
from detent.domain.roles import MEMBER_ROLES, Role, allowed
from detent.runtime import Runtime

log = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", dependencies=[Depends(check_csrf)], include_in_schema=False)

ROLE_TEXT = {
    Role.ACCOUNT_OWNER: "Account owner: team and roles, keys, webhooks, settings, verification",
    Role.ADMIN: "Admin: team and roles, keys, webhooks, settings, verification",
    Role.DEVELOPER: "Developer: keys, request logs, webhooks, sandbox controls",
    Role.PAYMENTS_LEAD: "Payments lead: policy, mandates, mode moves, sign-offs",
    Role.COMPLIANCE_LEAD: "Compliance lead: policy, mandates, mode moves, sign-offs",
    Role.REVIEWER: "Reviewer: the exceptions queue",
    Role.BACKUP_OWNER: "Backup owner: the exceptions queue",
    Role.AUDITOR: "Auditor: read-only audit, replay and export",
}


# ------------------------------------------------------------------------------------------ sign-in
@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str | None = None, rt: Runtime = Depends(runtime)) -> HTMLResponse:  # noqa: B008
    return page(request, rt, "login.html", None, error=None, next=safe_next(next, ""), email="")


@router.post("/login", response_model=None)
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
) -> Response:
    limiter, now = login_limiter(request), rt.clock.now()
    by_email = limiter.hit("login-email:" + email.strip().lower(), now)
    by_address = limiter.hit("login-ip:" + client_address(request), now, limit=limiter.limit * 3)
    if not (by_email.allowed and by_address.allowed):
        log.warning("dashboard sign-in throttled")
        return page(
            request,
            rt,
            "login.html",
            None,
            error="Too many attempts. Wait a minute and try again.",
            next=safe_next(next, ""),
            email=email,
            status_code=429,
        )
    with rt.engine.connect() as conn:
        member = access.authenticate(conn, email, password)
    if member is None:
        log.warning("dashboard sign-in failed")
        return page(
            request,
            rt,
            "login.html",
            None,
            error="Wrong email or password.",
            next=safe_next(next, ""),
            email=email,
            status_code=401,
        )
    with transaction(rt.engine) as conn:
        append(
            conn,
            rt.clock,
            org_id=member.org_id,
            actor=member.actor,
            kind="dashboard.signed_in",
            subject_id=member.id,
            payload={},
        )
    start_session(request, member)
    return redirect(safe_next(next, "/admin/" if member.is_staff else "/dashboard/"))


@router.post("/logout")
def logout(request: Request) -> Response:
    end_session(request)
    return redirect("/dashboard/login")


# ------------------------------------------------------------------------------------------ invites
@router.get("/invite/{token}", response_class=HTMLResponse)
def invite_form(token: str, request: Request, rt: Runtime = Depends(runtime)) -> HTMLResponse:  # noqa: B008
    with rt.engine.connect() as conn:
        inv = access.find_invite(conn, rt.clock, token)
    if inv is None:
        return page(
            request,
            rt,
            "invite.html",
            None,
            invite=None,
            error="This invite link is not valid.",
            status_code=404,
        )
    error = access._INVITE_MESSAGES.get(inv.state)
    return page(
        request,
        rt,
        "invite.html",
        None,
        invite=inv,
        token=token,
        error=error,
        role_text=ROLE_TEXT,
        status_code=410 if error else 200,
    )


@router.post("/invite/{token}", response_model=None)
def accept_invite(
    token: str,
    request: Request,
    display_name: str = Form(""),
    password: str = Form(""),
    password_again: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
) -> Response:
    with rt.engine.connect() as conn:
        inv = access.find_invite(conn, rt.clock, token)
    if password != password_again:
        return page(
            request,
            rt,
            "invite.html",
            None,
            invite=inv,
            token=token,
            role_text=ROLE_TEXT,
            error="The two passwords don't match.",
            status_code=422,
        )
    try:
        with transaction(rt.engine) as conn:
            member = access.accept_invite(
                conn, rt.clock, token=token, display_name=display_name, password=password
            )
    except AccessError as exc:
        return page(
            request,
            rt,
            "invite.html",
            None,
            invite=inv,
            token=token,
            role_text=ROLE_TEXT,
            error=str(exc),
            status_code=exc.status,
        )
    start_session(request, member)
    return redirect("/dashboard/?welcome=1")


# ------------------------------------------------------------------------------------------ home
@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(client_member),  # noqa: B008
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        org = access.load_org(conn, member.org_id)
        steps = onboarding_checklist(conn, member.org_id)
    return page(
        request,
        rt,
        "home.html",
        member,
        org=org,
        steps=steps,
        welcome=request.query_params.get("welcome") == "1",
    )


def onboarding_checklist(conn: Any, org_id: str) -> list[dict[str, Any]]:
    """DSH-02: the first-login checklist, each step ticked from what the organisation has actually done."""

    def has(sql: str) -> bool:
        return conn.execute(text(sql), {"o": org_id}).first() is not None

    members = conn.execute(
        text(
            "SELECT count(*) FROM users WHERE org_id=:o AND removed_at IS NULL AND password_hash IS NOT NULL"
        ),
        {"o": org_id},
    ).scalar_one()
    invited = has("SELECT 1 FROM invites WHERE org_id=:o AND role <> 'account_owner'")
    return [
        {
            "label": "Invite your team",
            "href": "/dashboard/team",
            "done": int(members) > 1 or invited,
            "detail": "Give each person a role; at least one account owner stays.",
        },
        {
            "label": "Create sandbox keys",
            "href": "/dashboard/keys",
            "done": has("SELECT 1 FROM api_keys WHERE org_id=:o"),
            "detail": "sk_test_ keys only (test networks).",
        },
        {
            "label": "Set up policy",
            "href": "/dashboard/policy",
            "done": has("SELECT 1 FROM policy_versions WHERE org_id=:o AND proposed_by NOT LIKE 'system:%'"),
            "detail": "Version 1 of the default rules is installed; propose your own.",
        },
        {
            "label": "Integrate",
            "href": "/dashboard/logs",
            "done": has(
                "SELECT 1 FROM request_logs WHERE org_id=:o AND method='POST' AND path='/v1/payment_intents' "
                "AND status < 300"
            ),
            "detail": "Create your first payment intent with a test key.",
        },
        {
            "label": "Request verification",
            "href": "/dashboard/verification",
            "done": False,
            "detail": "When every test value has run, DekernAI checks the integration.",
        },
    ]


# ------------------------------------------------------------------------------------------ team
@router.get("/team", response_class=HTMLResponse)
def team(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(client_member),  # noqa: B008
) -> HTMLResponse:
    return _team_page(request, rt, member)


def _team_page(
    request: Request, rt: Runtime, member: Member, error: str | None = None, status: int = 200
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        members = access.list_members(conn, member.org_id)
        invites = [i for i in access.list_invites(conn, rt.clock, member.org_id) if i["state"] == "open"]
    can_manage = allowed("team.manage", member.role)
    roles = [
        r for r in MEMBER_ROLES if r != Role.ACCOUNT_OWNER or allowed("team.grant_account_owner", member.role)
    ]
    return page(
        request,
        rt,
        "team.html",
        member,
        members=members,
        invites=invites,
        can_manage=can_manage,
        roles=roles,
        role_text=ROLE_TEXT,
        error=error,
        status_code=status,
    )


def _team_action(request: Request, rt: Runtime, member: Member, fn: Any, notice: str) -> Response:
    try:
        with transaction(rt.engine) as conn:
            fn(conn)
    except AccessError as exc:
        return _team_page(request, rt, member, error=str(exc), status=exc.status)
    return redirect("/dashboard/team?notice=" + notice)


@router.post("/team/invite", response_model=None)
def team_invite(
    request: Request,
    email: str = Form(""),
    role: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    def go(conn: Any) -> None:
        access.invite(
            conn, rt.clock, rt.settings, org_id=member.org_id, email=email, role=_role(role), by=member
        )

    return _team_action(request, rt, member, go, "invited")


@router.post("/team/{user_id}/role", response_model=None)
def team_role(
    user_id: str,
    request: Request,
    role: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    def go(conn: Any) -> None:
        access.change_role(conn, rt.clock, by=member, org_id=member.org_id, user_id=user_id, role=_role(role))

    return _team_action(request, rt, member, go, "role_changed")


@router.post("/team/{user_id}/remove", response_model=None)
def team_remove(
    user_id: str,
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    def go(conn: Any) -> None:
        access.remove_member(conn, rt.clock, by=member, org_id=member.org_id, user_id=user_id)

    return _team_action(request, rt, member, go, "removed")


@router.post("/team/invites/{invite_id}/revoke", response_model=None)
def team_revoke(
    invite_id: str,
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(writable_member),  # noqa: B008
) -> Response:
    def go(conn: Any) -> None:
        access.revoke_invite(conn, rt.clock, by=member, org_id=member.org_id, invite_id=invite_id)

    return _team_action(request, rt, member, go, "invite_revoked")


def _role(value: str) -> Role:
    try:
        return Role(value)
    except ValueError as exc:
        raise AccessError("invalid_role", "Choose one of the listed roles.") from exc


# ------------------------------------------------------------------------------------------ later pages
@router.get("/{section}", response_class=HTMLResponse)
def not_built(
    section: str,
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(client_member),  # noqa: B008
) -> HTMLResponse:
    """Pages from later P2 story groups (policy, verification)."""
    known = {"policy", "verification"}
    if section not in known:
        return page(request, rt, "not_found.html", member, status_code=404)
    return page(request, rt, "coming.html", member, section=section)
