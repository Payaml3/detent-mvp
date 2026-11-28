"""Shared plumbing for the dashboard and admin screens: sessions, CSRF, sign-in limits and page rendering.

Sessions live in the signed session cookie (SameSite=Lax, HTTPS-only when deployed). The dashboard keeps its
own keys, separate from the demo console's. Every request reloads the member, so a removed member or a
changed role takes effect at once. Every POST carries a per-session CSRF token.
"""

from __future__ import annotations

import hmac
import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from detent.api.limits import RateLimiter
from detent.dashboard.access import LOCKED_MESSAGES, Member, load_member, load_org, org_status
from detent.runtime import Runtime
from detent.views.display import install as install_display_filters

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
install_display_filters(templates.env)

SESSION_USER = "dash_user"
SESSION_ORG = "dash_org"
SESSION_CSRF = "dash_csrf"


class SignInRequired(Exception):
    """Redirects to the dashboard sign-in page."""

    def __init__(self, next_path: str = "/dashboard/") -> None:
        self.next_path = next_path


class Forbidden(Exception):
    def __init__(self, message: str, status: int = 403) -> None:
        super().__init__(message)
        self.message, self.status = message, status


def runtime(request: Request) -> Runtime:
    rt: Runtime = request.app.state.runtime
    return rt


def login_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter | None = getattr(request.app.state, "login_limiter", None)
    if limiter is None:
        rt = runtime(request)
        limiter = RateLimiter(limit=max(1, rt.settings.login_attempts_per_minute))
        request.app.state.login_limiter = limiter
    return limiter


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ------------------------------------------------------------------------------------------ sessions
def start_session(request: Request, member: Member) -> None:
    request.session.clear()  # a fresh session on every sign-in (no fixation)
    request.session[SESSION_USER] = member.id
    request.session[SESSION_ORG] = member.org_id
    request.session[SESSION_CSRF] = secrets.token_urlsafe(32)


def end_session(request: Request) -> None:
    request.session.clear()


def csrf_token(request: Request) -> str:
    tok = request.session.get(SESSION_CSRF)
    if not tok:
        tok = secrets.token_urlsafe(32)
        request.session[SESSION_CSRF] = tok
    return str(tok)


async def check_csrf(request: Request) -> None:
    """Every dashboard and admin POST sends the session's token as the `csrf` form field."""
    if request.method != "POST":
        return
    form = await request.form()
    sent = str(form.get("csrf") or "")
    expected = str(request.session.get(SESSION_CSRF) or "")
    if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
        raise Forbidden("The form expired. Go back, reload the page and try again.", status=400)


def current_member(request: Request, rt: Runtime = Depends(runtime)) -> Member:  # noqa: B008
    uid, org_id = request.session.get(SESSION_USER), request.session.get(SESSION_ORG)
    if not uid or not org_id:
        raise SignInRequired(request.url.path)
    with rt.engine.connect() as conn:
        member = load_member(conn, str(org_id), str(uid))
    if member is None:  # removed since signing in
        end_session(request)
        raise SignInRequired(request.url.path)
    return member


def client_member(member: Member = Depends(current_member)) -> Member:  # noqa: B008
    if member.is_staff:
        raise Forbidden("DekernAI admins use the admin screens.", status=403)
    return member


def staff_member(member: Member = Depends(current_member)) -> Member:  # noqa: B008
    if not member.is_staff:
        raise Forbidden("Only DekernAI admins can open the admin screens.", status=404)
    return member


def org_lock(rt: Runtime, org_id: str) -> str | None:
    """The read-only notice for an expired or suspended organisation, or None when it is active (DSH-03)."""
    with rt.engine.connect() as conn:
        org = load_org(conn, org_id)
    status = org_status(org, rt.clock.now())
    return None if status == "active" else LOCKED_MESSAGES[status]


def writable_member(
    rt: Runtime = Depends(runtime),  # noqa: B008
    member: Member = Depends(client_member),  # noqa: B008
) -> Member:
    """A client member doing a write: refused while the organisation is locked (read-only dashboard)."""
    lock = org_lock(rt, member.org_id)
    if lock:
        raise Forbidden(lock)
    return member


def page(request: Request, rt: Runtime, name: str, member: Member | None, **ctx: Any) -> HTMLResponse:
    base = {
        "brand": rt.settings.brand_name,
        "website_url": rt.settings.website_url.rstrip("/"),
        "member": member,
        "csrf": csrf_token(request),
        "now": rt.clock.now(),
        "hosting_region": rt.settings.hosting_region,
        "database_region": rt.settings.database_region,
        "lock": org_lock(rt, member.org_id) if member is not None and not member.is_staff else None,
    }
    status = int(ctx.pop("status_code", 200))
    return templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status)


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def safe_next(path: str | None, default: str) -> str:
    """Only same-site paths are followed after sign-in (no open redirect)."""
    if path and path.startswith(("/dashboard", "/admin")) and "//" not in path and "\\" not in path:
        return path
    return default
