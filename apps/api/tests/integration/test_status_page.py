"""WEB-07: /status.json feeds the website's status page (sandbox API, dashboard, docs)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from conftest import OrgFixture, make_settings
from detent.api.app import create_app
from detent.clock import FrozenClock
from fastapi.testclient import TestClient
from sqlalchemy import Engine

pytestmark = pytest.mark.db


def _app(org: OrgFixture, engine: Engine, clock: FrozenClock, **kw: Any) -> TestClient:
    return TestClient(
        create_app(make_settings(org.id, **kw), engine=engine, clock=clock, configure_logging=False)
    )


def _states(r: httpx.Response) -> dict[str, str]:
    return {c["id"]: c["status"] for c in r.json()["components"]}


def test_status_lists_the_three_components_for_any_origin(client: TestClient) -> None:
    r = client.get("/status.json", headers={"Origin": "https://dekernai.com"})
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == "*"
    body = r.json()
    assert [c["name"] for c in body["components"]] == ["Sandbox API", "Dashboard", "Docs"]
    assert _states(r) == {"sandbox_api": "operational", "dashboard": "operational", "docs": "not_monitored"}
    assert body["checked_at"] == "2026-12-03T10:00:00Z"
    assert set(body) == {"checked_at", "components"}, "nothing beyond the public states"


def test_docs_are_checked_over_http(
    org: OrgFixture, engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    answers = iter([httpx.Response(200), httpx.ConnectError("refused")])

    def fake_get(url: str, **_: Any) -> httpx.Response:
        calls.append(url)
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr("detent.api.status.httpx.get", fake_get)
    with _app(org, engine, clock, status_docs_url="https://docs.example.test") as c:
        assert _states(c.get("/status.json"))["docs"] == "operational"
        # Within the cache window the same answer is reused: the public page can't load the database or docs.
        assert _states(c.get("/status.json"))["docs"] == "operational"
        assert calls == ["https://docs.example.test"]
        clock.advance(timedelta(seconds=61))
        r = c.get("/status.json")
        assert _states(r)["docs"] == "down"
        assert r.json()["checked_at"] == "2026-12-03T10:01:01Z"


def test_database_down_marks_api_and_dashboard_down(
    org: OrgFixture, engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _app(org, engine, clock) as c:
        rt = c.app.state.runtime  # type: ignore[attr-defined]

        def broken() -> None:
            raise RuntimeError("database unreachable")

        monkeypatch.setattr(rt.engine, "connect", broken)
        r = c.get("/status.json")
        assert r.status_code == 200
        assert _states(r) == {"sandbox_api": "down", "dashboard": "down", "docs": "not_monitored"}
