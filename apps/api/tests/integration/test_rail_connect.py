"""RAL-09: connecting a rail by a mock consent screen or scoped API keys; credentials encrypted, never shown again."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from conftest import FAKE_LIVE, login, make_settings
from cryptography.fernet import Fernet
from decision_helpers import PEPPER, DecisionOrg, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.rails import connections as rc
from detent.settings import Settings
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

# Key-shaped values are assembled at runtime so secret scanners never see a key-shaped literal.
KEY = "_".join(["test", "banksim", "k3y", "0123456789abcd"])


@pytest.fixture
def setup(engine: Engine, clock: FrozenClock) -> Iterator[tuple[DecisionOrg, TestClient, Settings]]:
    d = setup_decision_org(engine, clock)
    s = make_settings(
        d.id,
        api_key_pepper=SecretStr(PEPPER),
        credentials_encryption_key=SecretStr(Fernet.generate_key().decode()),
    )
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield d, c, s


def lead(d: DecisionOrg) -> Actor:
    return Actor(d.org.users[Role.PAYMENTS_LEAD], Role.PAYMENTS_LEAD.value)


def rail(engine: Engine, d: DecisionOrg, rail_id: str) -> object:
    with engine.connect() as c:
        return c.execute(
            text("SELECT * FROM rails WHERE org_id=:o AND id=:r"), {"o": d.id, "r": rail_id}
        ).one_or_none()


def test_catalogue_has_test_rails_only() -> None:
    cat = {c.rail_id: c for c in rc.catalogue()}
    assert set(cat) == {"base-sepolia", "eth-sepolia", "banksim-fps", "banksim-sepa-inst"}
    assert cat["base-sepolia"].method == "consent" and cat["banksim-fps"].method == "api_key"
    assert "payouts:send" in cat["base-sepolia"].scopes and "payments:create" in cat["banksim-fps"].scopes


def test_api_key_is_encrypted_never_shown_and_audited(
    setup: tuple[DecisionOrg, TestClient, Settings], engine: Engine, clock: FrozenClock
) -> None:
    d, api, s = setup
    cid, hint = rc.connect(
        engine, clock, s, org_id=d.id, actor=lead(d), rail_id="banksim-fps",
        scopes=["payments:create", "payments:read"], api_key=KEY,
    )  # fmt: skip
    assert hint == "...abcd"
    with engine.connect() as c:
        row = c.execute(
            text("SELECT * FROM rail_connections WHERE org_id=:o AND id=:i"), {"o": d.id, "i": cid}
        ).one()
        audit = str(c.execute(text("SELECT payload FROM audit_events WHERE org_id=:o"), {"o": d.id}).all())
    assert KEY not in row.credential and rc.decrypt(s, row.credential) == KEY  # encrypted at rest
    assert row.scopes == ["payments:create", "payments:read"] and row.method == "api_key"
    assert KEY not in audit and "...abcd" in audit  # the audit names the hint, never the key
    r = rail(engine, d, "banksim-fps")
    assert r is not None and r.enabled  # type: ignore[attr-defined]
    login(api, d.org.users[Role.PAYMENTS_LEAD])
    page = api.get("/console/rails/connect").text
    assert "...abcd" in page and KEY not in page and "payments:create, payments:read" in page
    assert 'action="/console/rails/banksim-fps/disconnect"' in page and "Only the payments lead" not in page
    with pytest.raises(rc.ConnectionError_, match="already connected"):
        rc.connect(engine, clock, s, org_id=d.id, actor=lead(d), rail_id="banksim-fps", scopes=["payments:create"],
                   api_key=KEY)  # fmt: skip


@pytest.mark.parametrize(
    ("key", "scopes", "match"),
    [
        (FAKE_LIVE + "0" * 16, ["payments:create"], "Live keys are refused"),
        ("short", ["payments:create"], "16 to 200"),
        ("has a space in it 0123", ["payments:create"], "no spaces"),
        (KEY, ["payments:read"], "needs payments:create"),
        (KEY, ["payouts:send"], "Choose scopes"),
        (None, ["payments:create"], "Enter the API key"),
    ],
)
def test_bad_keys_and_scopes_are_refused(
    setup: tuple[DecisionOrg, TestClient, Settings],
    engine: Engine,
    clock: FrozenClock,
    key: str | None,
    scopes: list[str],
    match: str,
) -> None:
    d, _, s = setup
    with pytest.raises(rc.ConnectionError_, match=match):
        rc.connect(
            engine, clock, s, org_id=d.id, actor=lead(d), rail_id="banksim-fps", scopes=scopes, api_key=key
        )
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM rail_connections WHERE org_id=:o"), {"o": d.id}).scalar_one()
            == 0
        )


def test_no_encryption_key_means_no_connection(engine: Engine, clock: FrozenClock) -> None:
    d = setup_decision_org(engine, clock)
    s = make_settings(d.id, api_key_pepper=SecretStr(PEPPER))
    with pytest.raises(rc.ConnectionError_, match="CREDENTIALS_ENCRYPTION_KEY"):
        rc.connect(engine, clock, s, org_id=d.id, actor=lead(d), rail_id="banksim-fps", scopes=["payments:create"],
                   api_key=KEY)  # fmt: skip


def test_consent_screen_connects_and_disconnect_takes_the_rail_out_of_routing(
    setup: tuple[DecisionOrg, TestClient, Settings], engine: Engine
) -> None:
    d, api, s = setup
    login(api, d.org.users[Role.PAYMENTS_LEAD])
    screen = api.get("/console/rails/connect/base-sepolia").text
    assert "Mock consent screen" in screen and "payouts:send" in screen and 'value="deny"' in screen
    denied = api.post(
        "/console/rails/connect/base-sepolia", data={"decision": "deny"}, follow_redirects=False
    )
    assert denied.status_code == 303 and "not%20connected" in denied.headers["location"]
    r = api.post(
        "/console/rails/connect/base-sepolia",
        data={"decision": "allow", "scopes": ["payouts:send", "balances:read"]},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "won" in r.headers["location"]
    with engine.connect() as c:
        row = c.execute(
            text("SELECT * FROM rail_connections WHERE org_id=:o AND rail_id='base-sepolia'"), {"o": d.id}
        ).one()
    assert row.method == "consent" and rc.decrypt(s, row.credential).startswith("mock_consent_")
    assert rail(engine, d, "base-sepolia").enabled  # type: ignore[union-attr]
    out = api.post("/console/rails/base-sepolia/disconnect", follow_redirects=False)
    assert out.status_code == 303
    with engine.connect() as c:
        row = c.execute(
            text("SELECT * FROM rail_connections WHERE org_id=:o AND rail_id='base-sepolia'"), {"o": d.id}
        ).one()
        kinds = list(c.execute(
            text("SELECT kind FROM audit_events WHERE org_id=:o AND kind LIKE 'rail.%' ORDER BY seq"), {"o": d.id}
        ).scalars())  # fmt: skip
    assert row.credential is None and row.disconnected_at is not None  # the credential is removed
    assert not rail(engine, d, "base-sepolia").enabled  # type: ignore[union-attr]  # out of routing
    assert kinds == ["rail.connected", "rail.disconnected"]
    page = api.get("/console/rails/connect").text
    assert "Not connected" in page and "No connections yet" not in page  # history keeps the record


def test_only_the_payments_lead_connects(setup: tuple[DecisionOrg, TestClient, Settings]) -> None:
    d, api, _ = setup
    login(api, d.org.users[Role.REVIEWER])
    assert "Only the payments lead" in api.get("/console/rails/connect").text
    r = api.post("/console/rails/connect/banksim-fps", data={"api_key": KEY, "scopes": ["payments:create"]})
    assert r.status_code == 403
