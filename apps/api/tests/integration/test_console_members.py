"""P2 group 4b: the console for a dashboard member, scoped to their own organisation (DSH-09).

A member signed in to the developer dashboard opens the same console screens as themselves: no demo
password, no act-as, no demo-only controls. They see only their organisation's data, and only its current
data generation (SBX-04). Their writes need their role, a same-site request and an organisation that is not
read-only (DSH-03).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.dashboard import access, sandbox
from detent.dashboard.access import Member
from detent.domain.roles import Role
from detent.execution import kill_switch
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from test_dashboard_access import PASSWORD, _email, owner_of, sign_in
from test_sandbox_rails import SETTINGS, drain, key_for, pay
from test_sandbox_reset import WEBHOOKS, _escalate

pytestmark = pytest.mark.db

SAME = {"Origin": "http://testserver"}


def _org(engine: Engine, clock: FrozenClock, staff: Member) -> Member:
    _org_id, owner = owner_of(engine, clock, staff)
    with engine.begin() as conn:
        conn.execute(text("UPDATE organisations SET mode='auto' WHERE org_id=:o"), {"o": owner.org_id})
    return owner


def _member(engine: Engine, clock: FrozenClock, owner: Member, role: Role) -> Member:
    with engine.begin() as conn:
        token = access.invite(
            conn, clock, SETTINGS, org_id=owner.org_id, email=_email(role.value), role=role, by=owner
        )
        return access.accept_invite(conn, clock, token=token, display_name="Lee Lead", password=PASSWORD)


@pytest.fixture
def staff(engine: Engine, clock: FrozenClock) -> Member:
    with engine.begin() as conn:
        return access.create_staff(
            conn, clock, email=_email("staff"), display_name="Staff", password=PASSWORD
        )


@pytest.fixture
def owner(engine: Engine, clock: FrozenClock, staff: Member) -> Member:
    return _org(engine, clock, staff)


@pytest.fixture
def lead(engine: Engine, clock: FrozenClock, owner: Member) -> Member:
    return _member(engine, clock, owner, Role.PAYMENTS_LEAD)


@pytest.fixture
def api(engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    with TestClient(create_app(WEBHOOKS, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def _web(engine: Engine, clock: FrozenClock, m: Member) -> TestClient:
    c = TestClient(create_app(SETTINGS, engine=engine, clock=clock, configure_logging=False))
    assert sign_in(c, m.email).status_code == 303
    return c


def test_a_member_uses_the_console_as_themselves_without_demo_controls(
    engine: Engine, clock: FrozenClock, owner: Member
) -> None:
    c = _web(engine, clock, owner)
    home = c.get("/console/")
    assert home.status_code == 200
    assert "Ada Owner" in home.text and "Acting as" not in home.text
    assert 'action="/console/act-as"' not in home.text and 'href="/console/act-as"' not in home.text
    assert "/console/clock/advance" not in home.text
    assert 'href="/console/invoices"' not in home.text and 'href="/console/demo"' not in home.text
    assert 'action="/dashboard/logout"' in home.text and "Fictional demo data" not in home.text
    assert c.get("/console/act-as", follow_redirects=False).headers["location"] == "/console/"
    assert c.post("/console/act-as", data={"user_id": "usr_x"}, headers=SAME).status_code == 404
    for path in ("/console/invoices", "/console/demo"):
        assert c.get(path).status_code == 404, path
    assert c.post("/console/clock/advance", data={"step": "1h"}, headers=SAME).status_code == 404
    for path in ("/console/policy", "/console/counterparties", "/console/mandates", "/console/payments"):
        assert c.get(path).status_code == 200, path
    # The dashboard links to the console, and its old policy placeholder goes there.
    assert 'href="/console/"' in c.get("/dashboard/").text
    moved = c.get("/dashboard/policy", follow_redirects=False)
    assert (moved.status_code, moved.headers["location"]) == (303, "/console/policy")


def test_a_member_sees_only_their_organisation_and_current_generation(
    api: TestClient, engine: Engine, clock: FrozenClock, staff: Member, owner: Member, lead: Member
) -> None:
    other = _org(engine, clock, staff)
    theirs = _escalate(api, key_for(engine, clock, other)).json()
    mine = _escalate(api, key_for(engine, clock, owner)).json()
    c = _web(engine, clock, lead)
    payments, cases = c.get("/console/payments").text, c.get("/console/exceptions").text
    assert mine["id"] in payments and theirs["id"] not in payments
    assert mine["exception"]["id"] in cases and theirs["exception"]["id"] not in cases
    assert c.get(f"/console/exceptions/{theirs['exception']['id']}").status_code == 404

    with engine.begin() as conn:
        sandbox.reset_sandbox(conn, clock, by=owner, confirm="reset")
    assert mine["id"] not in c.get("/console/payments").text
    assert mine["exception"]["id"] not in c.get("/console/exceptions").text
    case = f"/console/exceptions/{mine['exception']['id']}"
    assert c.get(case).status_code == 404
    assert c.post(f"{case}/approve", data={"reason": "looks fine"}, headers=SAME).status_code == 404
    assert c.get("/console/").status_code == 200


def test_member_writes_need_their_role_and_a_same_site_request(
    engine: Engine, clock: FrozenClock, owner: Member, lead: Member
) -> None:
    as_owner = _web(engine, clock, owner)
    assert as_owner.post("/console/kill_switch/engage", headers=SAME).status_code == 403  # not their role
    c = _web(engine, clock, lead)
    assert c.post("/console/kill_switch/engage").status_code == 403  # no Origin or Referer
    evil = {"Origin": "https://evil.example.test"}
    assert c.post("/console/kill_switch/engage", headers=evil).status_code == 403
    assert (
        c.post("/console/kill_switch/engage", headers={"Referer": "https://evil.example.test/"}).status_code
        == 403
    )
    assert not kill_switch.is_engaged(engine, lead.org_id)
    ok = c.post("/console/kill_switch/engage", headers=SAME, follow_redirects=False)
    assert ok.status_code == 303
    assert kill_switch.is_engaged(engine, lead.org_id)
    with engine.connect() as conn:
        actor = conn.execute(
            text(
                "SELECT actor, actor_role FROM audit_events WHERE org_id=:o AND kind LIKE 'kill_switch.%' "
                "ORDER BY seq DESC LIMIT 1"
            ),
            {"o": lead.org_id},
        ).one()
    assert tuple(actor) == (lead.id, "payments_lead")


def test_a_read_only_organisation_cannot_write_from_the_console(
    engine: Engine, clock: FrozenClock, owner: Member, lead: Member
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE organisations SET suspended_at=:t, suspended_reason='test' WHERE org_id=:o"),
            {"t": clock.now(), "o": lead.org_id},
        )
    c = _web(engine, clock, lead)
    assert c.get("/console/policy").status_code == 200  # reading still works
    assert c.post("/console/kill_switch/engage", headers=SAME).status_code == 403
    assert not kill_switch.is_engaged(engine, lead.org_id)


def test_a_reset_waits_for_payments_the_kill_switch_holds(
    api: TestClient, engine: Engine, clock: FrozenClock, owner: Member, lead: Member
) -> None:
    kill_switch.engage(engine, clock, org_id=lead.org_id, actor=lead.actor)
    held = pay(api, key_for(engine, clock, owner), "90.00")
    drain(engine, clock, owner.org_id)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, held_reason FROM payment_intents WHERE org_id=:o AND id=:p"),
            {"o": owner.org_id, "p": held["id"]},
        ).one()
    assert tuple(row) == ("HELD", "KILL_SWITCH_ENGAGED")
    with engine.begin() as conn, pytest.raises(access.AccessError, match="can still be sent"):
        sandbox.reset_sandbox(conn, clock, by=owner, confirm="reset")
