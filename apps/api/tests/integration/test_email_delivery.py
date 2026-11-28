"""Dashboard emails through ZeptoMail (founder's choice, 2026-11-28): stored in the outbox, sent by a job."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from conftest import OrgFixture, make_settings
from detent.clock import FrozenClock
from detent.dashboard.email import SEND_JOB, send_email
from detent.runtime import build_runtime
from detent.settings import Settings
from detent.worker.loop import Worker
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

TOKEN = "zepto-test-token-0123456789"  # a fake test value


def _live(org: OrgFixture) -> Settings:
    return make_settings(org.id, email_provider="zeptomail", zeptomail_token=SecretStr(TOKEN))


def _send(engine: Engine, clock: FrozenClock, settings: Settings, org: OrgFixture) -> str:
    with engine.begin() as conn:
        return send_email(conn, clock, org_id=org.id, to="dev@example.test", template="invite.member",
                          body="Open this link: https://example.test/x", settings=settings)  # fmt: skip


def _row(engine: Engine, org: OrgFixture, mid: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT channel, sent_at, provider_message_id, last_error FROM outbox WHERE org_id=:o AND id=:i"
            ),
            {"o": org.id, "i": mid},
        ).one()


def _jobs(engine: Engine, org: OrgFixture) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(
            text("SELECT done_at, dead_at, attempts, last_error FROM jobs WHERE org_id=:o AND kind=:k"),
            {"o": org.id, "k": SEND_JOB},
        ))  # fmt: skip


class FakeZepto:
    def __init__(self, *answers: httpx.Response | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> httpx.Response:
        self.calls.append({"url": url, "json": json, "headers": headers})
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def _worker(settings: Settings, engine: Engine, clock: FrozenClock) -> Worker:
    return Worker(
        build_runtime(settings, engine=engine, clock=clock), worker_id="w-email", org_id=settings.demo_org_id
    )


def test_outbox_provider_only_stores(org: OrgFixture, engine: Engine, clock: FrozenClock) -> None:
    mid = _send(engine, clock, make_settings(org.id), org)
    assert _row(engine, org, mid).channel == "email_mock"
    assert _jobs(engine, org) == []


def test_zeptomail_sends_once_from_the_job(
    org: OrgFixture, engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _live(org)
    fake = FakeZepto(httpx.Response(201, json={"request_id": "zm_123", "message": "OK"}))
    monkeypatch.setattr("detent.dashboard.email_delivery.httpx.post", fake)
    mid = _send(engine, clock, s, org)
    assert _row(engine, org, mid).channel == "email"
    w = _worker(s, engine, clock)
    assert w.run_one()
    row = _row(engine, org, mid)
    assert row.sent_at is not None and row.provider_message_id == "zm_123" and row.last_error is None
    (call,) = fake.calls
    assert call["url"] == "https://api.zeptomail.eu/v1.1/email"
    assert call["headers"]["Authorization"] == f"Zoho-enczapikey {TOKEN}"
    body = call["json"]
    assert body["from"] == {"address": "notifications@dekernai.com", "name": "DekernAI"}
    assert body["to"] == [{"email_address": {"address": "dev@example.test"}}]
    assert body["subject"] == "You're invited to join your team on DekernAI"
    assert "https://example.test/x" in body["textbody"]
    assert not w.run_one(), "nothing left to send"


def test_provider_outage_is_retried_then_sent(
    org: OrgFixture, engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _live(org)
    fake = FakeZepto(
        httpx.Response(503), httpx.ConnectError("down"), httpx.Response(200, json={"request_id": "zm_9"})
    )
    monkeypatch.setattr("detent.dashboard.email_delivery.httpx.post", fake)
    mid = _send(engine, clock, s, org)
    w = _worker(s, engine, clock)
    for _ in range(3):
        assert w.run_one()
        clock.advance(timedelta(minutes=10))
    assert _row(engine, org, mid).provider_message_id == "zm_9"
    (job,) = _jobs(engine, org)
    assert job.done_at is not None and job.attempts == 3
    assert len(fake.calls) == 3


def test_rejected_email_is_recorded_and_not_retried(
    org: OrgFixture, engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = _live(org)
    fake = FakeZepto(httpx.Response(401, json={"error": {"code": "TM_3601", "message": "Invalid token"}}))
    monkeypatch.setattr("detent.dashboard.email_delivery.httpx.post", fake)
    mid = _send(engine, clock, s, org)
    w = _worker(s, engine, clock)
    assert w.run_one()
    clock.advance(timedelta(hours=1))
    assert not w.run_one()
    row = _row(engine, org, mid)
    assert row.sent_at is None and row.last_error.startswith("HTTP 401")
    assert len(fake.calls) == 1


def test_zeptomail_needs_a_token(org: OrgFixture) -> None:
    with pytest.raises(ValueError, match="ZEPTOMAIL_TOKEN"):
        make_settings(org.id, email_provider="zeptomail")
    with pytest.raises(ValueError, match="EMAIL_PROVIDER"):
        make_settings(org.id, email_provider="smtp")


def test_the_token_never_reaches_the_logs(org: OrgFixture) -> None:
    assert TOKEN in _live(org).secret_values()
