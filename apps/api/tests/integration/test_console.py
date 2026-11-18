"""FND-04 (demo login and acting user) and FND-05 (demo clock)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from conftest import DEMO_PASSWORD, OrgFixture, login, make_settings
from detent.api.app import create_app
from detent.audit.log import verify_chain
from detent.clock import FrozenClock
from detent.console.auth import ActingUser, require_permission
from detent.domain.roles import Role
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


def test_console_requires_login(client: TestClient) -> None:
    r = client.get("/console/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/console/login"


def test_wrong_password_rejected(client: TestClient) -> None:
    r = client.post("/console/login", data={"password": "nope"})
    assert "Wrong password" in r.text
    assert client.get("/console/", follow_redirects=False).headers["location"] == "/console/login"


def test_login_then_pick_acting_user(client: TestClient, org: OrgFixture, engine: Engine) -> None:
    login(client)
    r = client.get("/console/", follow_redirects=False)
    assert r.headers["location"] == "/console/act-as"
    page = client.get("/console/act-as").text
    for role in Role:
        assert org.users[role] in page
    login(client, org.users[Role.REVIEWER])
    home = client.get("/console/").text
    assert "Acting as" in home and "reviewer" in home
    assert "Prototype · test networks · simulated bank rail" in home
    assert "Kill switch: off" in home


def test_switching_user_is_audited_with_id_and_role(
    client: TestClient, org: OrgFixture, engine: Engine
) -> None:
    login(client, org.users[Role.PAYMENTS_LEAD])
    client.post("/console/act-as", data={"user_id": org.users[Role.COMPLIANCE_LEAD]})
    with engine.connect() as c:
        rows = c.execute(
            text("SELECT actor, actor_role, kind, payload FROM audit_events WHERE org_id=:o ORDER BY seq"),
            {"o": org.id},
        ).all()
        assert verify_chain(c, org.id).ok
    assert [(r.actor, r.actor_role) for r in rows] == [
        (org.users[Role.PAYMENTS_LEAD], "payments_lead"),
        (org.users[Role.COMPLIANCE_LEAD], "compliance_lead"),
    ]
    assert rows[1].payload == {"previous_user_id": org.users[Role.PAYMENTS_LEAD]}


def test_cannot_act_as_another_orgs_user(client: TestClient, engine: Engine, clock: FrozenClock) -> None:
    from conftest import make_org

    other = make_org(engine, clock)
    login(client)
    r = client.post("/console/act-as", data={"user_id": other.users[Role.PAYMENTS_LEAD]})
    assert r.status_code == 400


def test_role_checks_run_on_the_server(settings, engine: Engine, clock: FrozenClock, org: OrgFixture) -> None:  # type: ignore[no-untyped-def]
    app = create_app(settings, engine=engine, clock=clock, configure_logging=False)

    @app.post("/console/_test/release-kill-switch")
    def release(user: ActingUser = Depends(require_permission("kill_switch.release"))) -> dict[str, str]:  # noqa: B008
        return {"by": user.id}

    with TestClient(app) as c:
        login(c, org.users[Role.ONCALL])
        r = c.post("/console/_test/release-kill-switch")
        assert r.status_code == 403 and "kill_switch.release" in r.text
        c.post("/console/act-as", data={"user_id": org.users[Role.PAYMENTS_LEAD]})
        assert c.post("/console/_test/release-kill-switch").json() == {"by": org.users[Role.PAYMENTS_LEAD]}


def test_clock_control_absent_outside_demo_mode(client: TestClient, org: OrgFixture) -> None:
    login(client, org.users[Role.REVIEWER])
    assert "+15m" not in client.get("/console/").text
    assert client.post("/console/clock/advance", data={"step": "1h"}).status_code == 404


@pytest.fixture
def demo_client(org: OrgFixture, engine: Engine) -> Iterator[TestClient]:
    s = make_settings(
        org.id,
        app_env="demo",
        demo_password=SecretStr(DEMO_PASSWORD),
        session_secret=SecretStr("demo-session-secret-0123456789abcdef"),
    )
    app = create_app(s, engine=engine, configure_logging=False)  # DemoClock over real time
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def test_demo_clock_fast_forward(demo_client: TestClient, org: OrgFixture, engine: Engine) -> None:
    login(demo_client, org.users[Role.REVIEWER])
    clock = demo_client.app.state.runtime.clock  # type: ignore[attr-defined]
    before = clock.now()
    page = demo_client.get("/console/").text
    assert "+15m" in page and "+1h" in page and "+1d" in page
    for step in ("15m", "1h", "1d"):
        r = demo_client.post("/console/clock/advance", data={"step": step}, follow_redirects=False)
        assert r.status_code == 303
    gained = clock.now() - before
    assert timedelta(days=1, hours=1, minutes=15) <= gained < timedelta(days=1, hours=1, minutes=16)
    with engine.connect() as c:
        offset = c.execute(
            text("SELECT offset_seconds FROM demo_clock WHERE org_id=:o"), {"o": org.id}
        ).scalar()
        kinds = c.execute(
            text("SELECT kind, actor FROM audit_events WHERE org_id=:o AND kind='demo.clock_advanced'"),
            {"o": org.id},
        ).all()
    assert offset == 90900
    assert len(kinds) == 3 and all(k.actor == org.users[Role.REVIEWER] for k in kinds)
    assert demo_client.post("/console/clock/advance", data={"step": "1y"}).status_code == 400


def test_demo_cookie_is_secure(demo_client: TestClient) -> None:
    r = demo_client.post("/console/login", data={"password": DEMO_PASSWORD}, follow_redirects=False)
    assert "secure" in r.headers["set-cookie"].lower()


def test_require_permission_on_plain_app() -> None:
    # The dependency can't be satisfied without a logged-in session: fail closed.
    app = FastAPI()

    @app.get("/x")
    def x(user: ActingUser = Depends(require_permission("kill_switch.release"))) -> str:  # noqa: B008
        return user.id

    with pytest.raises(Exception):  # noqa: B017, PT011 - no session middleware: refuses
        TestClient(app).get("/x")
