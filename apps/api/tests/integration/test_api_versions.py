"""API-03: dated versions. Each organisation has a pinned default; unknown versions are refused."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from conftest import make_settings
from decision_helpers import PEPPER, DecisionOrg, setup_decision_org
from detent.api import middleware
from detent.api.app import create_app
from detent.clock import FrozenClock
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


@pytest.fixture
def dorg(engine: Engine, clock: FrozenClock) -> DecisionOrg:
    return setup_decision_org(engine, clock)


@pytest.fixture
def api(dorg: DecisionOrg, engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    s = make_settings(dorg.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def test_without_a_header_the_organisations_pinned_version_applies(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(middleware, "SUPPORTED_VERSIONS", frozenset({"2026-12-01", "2027-03-01"}))
    other = setup_decision_org(engine, clock)
    with engine.begin() as c:
        c.execute(text("UPDATE organisations SET api_version='2027-03-01' WHERE org_id=:o"), {"o": dorg.id})
    assert api.get("/v1/payment_intents", headers=dorg.auth()).headers["DekernAI-Version"] == "2027-03-01"
    assert api.get("/v1/payment_intents", headers=other.auth()).headers["DekernAI-Version"] == "2026-12-01"
    # An explicit header wins over the pin.
    explicit = api.get("/v1/payment_intents", headers={**dorg.auth(), "DekernAI-Version": "2026-12-01"})
    assert explicit.headers["DekernAI-Version"] == "2026-12-01"


def test_new_organisations_are_pinned_to_the_current_version(dorg: DecisionOrg, engine: Engine) -> None:
    from detent.api.limits import CURRENT_VERSION

    with engine.connect() as c:
        pinned = c.execute(
            text("SELECT api_version FROM organisations WHERE org_id=:o"), {"o": dorg.id}
        ).scalar()
    assert pinned == CURRENT_VERSION


def test_an_unknown_version_is_400_before_any_work(api: TestClient, dorg: DecisionOrg) -> None:
    r = api.get("/v1/payment_intents", headers={**dorg.auth(), "DekernAI-Version": "2019-01-01"})
    err = r.json()["error"]
    assert r.status_code == 400 and err["code"] == "unknown_version" and err["param"] == "DekernAI-Version"
