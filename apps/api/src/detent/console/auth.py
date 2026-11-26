"""Demo login and the acting-user switcher (FND-04), and the console per organisation (DSH-09).

One shared demo password protects the demo console. After login the viewer picks an acting user from
the demo organisation. Every write records that user's ID and role in the audit log. Permission
checks run here, on the server, from ``detent.domain.roles.PERMISSIONS``.

A member signed in to the developer dashboard uses the same screens as themselves, scoped to their own
organisation (DSH-09): no act-as, no demo password, and no demo-only controls (`demo_only`). Their
writes are refused while the organisation is read-only (DSH-03), and must come from this site (an Origin
or Referer of the same host; the console's forms carry no CSRF token, so this stands in for one, on top
of SameSite=Lax).
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from detent.audit.log import Actor
from detent.db.repo import OrgScoped
from detent.db.tables import users
from detent.demo.generations import active_org
from detent.domain.roles import Role, allowed
from detent.runtime import Runtime


class LoginRequired(Exception):
    """Raised to redirect the browser to the login page."""


class ActingUserRequired(Exception):
    """Raised to redirect the browser to the act-as page."""


@dataclass(frozen=True, slots=True)
class ActingUser:
    id: str
    org_id: str
    display_name: str
    role: Role
    via_dashboard: bool = False  # a dashboard member in their own organisation (DSH-09)

    @property
    def actor(self) -> Actor:
        return Actor(self.id, self.role.value)


def runtime(request: Request) -> Runtime:
    rt: Runtime = request.app.state.runtime
    return rt


def check_password(rt: Runtime, password: str) -> bool:
    expected = rt.settings.demo_password.get_secret_value().encode()
    return hmac.compare_digest(password.encode(), expected)


def is_logged_in(request: Request) -> bool:
    return bool(request.session.get("authed"))


def require_login(request: Request) -> None:
    if not is_logged_in(request):
        raise LoginRequired


def load_user(rt: Runtime, user_id: str) -> ActingUser | None:
    with rt.engine.connect() as conn:
        repo = OrgScoped(conn, active_org(conn, rt.settings.demo_org_id))
        row = conn.execute(repo.select(users).where(users.c.id == user_id)).one_or_none()
    if row is None:
        return None
    return ActingUser(row.id, row.org_id, row.display_name, Role(row.role))


def list_users(rt: Runtime) -> list[ActingUser]:
    with rt.engine.connect() as conn:
        repo = OrgScoped(conn, active_org(conn, rt.settings.demo_org_id))
        rows = conn.execute(repo.select(users).order_by(users.c.id)).all()
    return [ActingUser(r.id, r.org_id, r.display_name, Role(r.role)) for r in rows]


_SAFE = frozenset({"GET", "HEAD", "OPTIONS"})


def _same_site(request: Request) -> bool:
    here = f"{request.url.scheme}://{request.url.netloc}"
    origin = request.headers.get("origin")
    if origin:
        return origin == here
    referer = request.headers.get("referer") or ""
    return referer == here or referer.startswith(here + "/")


def dashboard_member(request: Request, rt: Runtime) -> ActingUser | None:
    """The dashboard member signed in on this browser, as a console user of their own organisation."""
    from detent.dashboard.access import load_member
    from detent.dashboard.web import SESSION_ORG, SESSION_USER, org_lock

    uid, org_id = request.session.get(SESSION_USER), request.session.get(SESSION_ORG)
    if not uid or not org_id:
        return None
    with rt.engine.connect() as conn:
        member = load_member(conn, str(org_id), str(uid))
    if member is None or member.is_staff:
        return None
    if request.method not in _SAFE:
        if not _same_site(request):
            raise HTTPException(status_code=403, detail="cross-site request refused")
        lock = org_lock(rt, member.org_id)
        if lock:
            raise HTTPException(status_code=403, detail=lock)
    return ActingUser(member.id, member.org_id, member.display_name, member.role, via_dashboard=True)


def acting_user(request: Request, rt: Runtime = Depends(runtime)) -> ActingUser:  # noqa: B008
    member = dashboard_member(request, rt)
    if member is not None:
        return member
    require_login(request)
    user_id = request.session.get("user_id")
    if not user_id:
        raise ActingUserRequired
    user = load_user(rt, str(user_id))
    if user is None:
        request.session.pop("user_id", None)
        raise ActingUserRequired
    return user


def optional_acting_user(request: Request, rt: Runtime = Depends(runtime)) -> ActingUser | None:  # noqa: B008
    member = dashboard_member(request, rt)
    if member is not None:
        return member
    if not is_logged_in(request) or not request.session.get("user_id"):
        return None
    return load_user(rt, str(request.session["user_id"]))


def require_permission(action: str) -> Callable[..., ActingUser]:
    """FastAPI dependency: the acting user must hold a role allowed to perform ``action``."""

    def dep(user: ActingUser = Depends(acting_user)) -> ActingUser:  # noqa: B008
        if not allowed(action, user.role):
            raise HTTPException(
                status_code=403,
                detail=f"{user.display_name} ({user.role.value}) may not perform {action}",
            )
        return user

    return dep


def demo_only(user: ActingUser) -> None:
    """Demo-only screens and controls (the clock, the scenario runner, the invoice agent, act-as) do not exist
    for a dashboard member (DSH-09)."""
    if user.via_dashboard:
        raise HTTPException(status_code=404)
