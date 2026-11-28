"""DekernAI admins (founder, 2026-11-28): the first admin by a one-time email invite to FOUNDER_ADMIN_EMAIL,
then admins invite each other on the Admins screen. Every new admin sets their own password."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator

import pytest
from conftest import make_settings
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.dashboard import access
from detent.dashboard.access import OPERATOR_ORG, Member
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from test_dashboard_access import PASSWORD, _email, accept, owner_of, post, sign_in

pytestmark = pytest.mark.db

SETTINGS = make_settings("org_detent", dashboard_url="https://dash.example.test")


@pytest.fixture
def staff(engine: Engine, clock: FrozenClock) -> Member:
    with engine.begin() as conn:
        return access.create_staff(
            conn, clock, email=_email("staff"), display_name="Staff", password=PASSWORD
        )


@pytest.fixture
def web(engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    with TestClient(create_app(SETTINGS, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def _link(engine: Engine, email: str) -> str:
    with engine.connect() as conn:
        body = conn.execute(
            text(
                "SELECT body FROM outbox WHERE org_id=:o AND recipient=:e ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"o": OPERATOR_ORG, "e": email},
        ).scalar_one()
    assert "as a DekernAI admin" in body
    m = re.search(r"/dashboard/invite/([A-Za-z0-9_-]+)", body)
    assert m
    return m.group(1)


def test_the_first_admin_is_invited_once_while_no_admin_exists(engine: Engine, clock: FrozenClock) -> None:
    founder = f"founder-{uuid.uuid4().hex[:8]}@dekern.example.test"
    settings = make_settings(
        "org_detent", dashboard_url="https://dash.example.test", founder_admin_email=founder
    )
    with engine.connect() as conn, conn.begin() as tx:  # other tests' admins exist: hide them, then roll back
        conn.execute(
            text("UPDATE users SET removed_at=:now WHERE org_id=:o AND removed_at IS NULL"),
            {"o": OPERATOR_ORG, "now": clock.now()},
        )
        conn.execute(
            text(
                "UPDATE invites SET revoked_at=:now WHERE org_id=:o AND used_at IS NULL AND revoked_at IS NULL"
            ),
            {"o": OPERATOR_ORG, "now": clock.now()},
        )
        token = access.bootstrap_founder_admin(conn, clock, settings)
        assert token is not None
        assert access.bootstrap_founder_admin(conn, clock, settings) is None  # one open invite at a time
        member = access.accept_invite(conn, clock, token=token, display_name="Founder", password=PASSWORD)
        assert member.is_staff
        assert access.bootstrap_founder_admin(conn, clock, settings) is None  # an admin exists now
        tx.rollback()
    with engine.begin() as conn:
        assert access.bootstrap_founder_admin(conn, clock, SETTINGS) is None  # no FOUNDER_ADMIN_EMAIL


def test_the_app_starts_with_founder_admin_email_set_when_admins_exist(
    engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    founder = f"founder-{uuid.uuid4().hex[:8]}@dekern.example.test"
    settings = make_settings("org_detent", founder_admin_email=founder)
    with TestClient(create_app(settings, engine=engine, clock=clock, configure_logging=False)) as c:
        assert c.get("/dashboard/login").status_code == 200
    with engine.connect() as conn:
        sent = conn.execute(
            text("SELECT count(*) FROM outbox WHERE org_id=:o AND recipient=:e"),
            {"o": OPERATOR_ORG, "e": founder},
        ).scalar_one()
    assert sent == 0


def test_an_admin_invites_another_admin_who_sets_their_own_password(
    web: TestClient, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    assert sign_in(web, staff.email).status_code == 303
    assert "/admin/staff" in web.get("/admin/").text
    new = _email("newadmin")
    r = post(web, "/admin/staff/invite", {"email": new}, page="/admin/staff")
    assert r.status_code == 303
    shown = web.get("/admin/staff").text
    assert "/dashboard/invite/" in shown and new in shown
    assert "/dashboard/invite/" not in web.get("/admin/staff").text  # the link is shown once
    with engine.connect() as conn:
        kinds = list(
            conn.execute(
                text("SELECT kind FROM audit_events WHERE org_id=:o AND actor=:a ORDER BY seq"),
                {"o": OPERATOR_ORG, "a": staff.id},
            ).scalars()
        )
    assert "invite.sent" in kinds

    newcomer = TestClient(web.app)
    assert accept(newcomer, _link(engine, new), name="New Admin").status_code == 303
    assert sign_in(newcomer, new).headers["location"] == "/admin/"
    assert new in newcomer.get("/admin/staff").text
    again = post(web, "/admin/staff/invite", {"email": new}, page="/admin/staff")
    assert again.status_code == 409


def test_client_members_cannot_invite_admins(
    engine: Engine, clock: FrozenClock, staff: Member, web: TestClient
) -> None:
    _org, owner = owner_of(engine, clock, staff)
    assert sign_in(web, owner.email).status_code == 303
    assert web.get("/admin/staff").status_code == 404
    assert post(web, "/admin/staff/invite", {"email": _email("x")}, page="/dashboard/").status_code == 404
    with engine.begin() as conn, pytest.raises(access.AccessError):
        access.invite_staff(conn, clock, SETTINGS, email=_email("y"), by=owner)
