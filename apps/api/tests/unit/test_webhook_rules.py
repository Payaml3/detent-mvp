"""WHK-01 and WHK-03 rules that need no database: event types, URL safety and the retry schedule."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import make_settings
from detent.settings import Settings
from detent.webhooks import delivery
from detent.webhooks.endpoints import EndpointError, check_types, check_url
from detent.webhooks.events import EVENT_TYPES, types_for


def _settings(**kw: object) -> Settings:
    return make_settings("org_x", **kw)


def test_event_types_match_spec_03() -> None:
    from detent.settings import REPO_ROOT

    spec = (REPO_ROOT / "spec" / "03-api.md").read_text()
    for t in EVENT_TYPES:
        assert f"`{t}`" in spec
    assert {
        "payment_intent.confirmed",
        "exception.created",
        "deposit.credited",
        "reconciliation.break",
    } <= set(EVENT_TYPES)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"from": "RECEIVED", "to": "ESCALATED"}, ["payment_intent.decided", "payment_intent.escalated"]),
        ({"from": "RECEIVED", "to": "HELD"}, ["payment_intent.decided"]),
        ({"from": "RECEIVED", "to": "SHADOWED"}, ["payment_intent.decided"]),
        ({"from": "SUBMITTED", "to": "UNKNOWN"}, ["payment_intent.unknown"]),
        ({"from": "UNKNOWN", "to": "CONFIRMED"}, ["payment_intent.confirmed"]),
        ({"from": "READY", "to": "HELD"}, []),
    ],
)
def test_payment_status_changes_map_to_event_types(payload: dict[str, str], expected: list[str]) -> None:
    assert types_for("payment.status_changed", payload) == expected


def test_audit_kinds_without_a_public_event_produce_none() -> None:
    assert types_for("policy.proposed", {}) == []
    assert types_for("webhook_endpoint.created", {}) == []
    assert types_for("case.opened", {}) == ["exception.created"]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/hook",
        "https://user:pw@example.com/hook",
        "https://127.0.0.1/hook",
        "https://10.0.0.5/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/hook",
        "https://localhost/hook",
        "https://printer.local/hook",
        "ftp://example.com/hook",
    ],
)
def test_unsafe_urls_are_refused(url: str) -> None:
    with pytest.raises(EndpointError) as e:
        check_url(url, _settings())
    assert e.value.code == "invalid_url"


def test_public_https_urls_pass_and_local_receivers_need_the_dev_flag() -> None:
    assert check_url("https://hooks.example.com/dekernai", _settings())
    assert check_url("http://127.0.0.1:9000/hook", _settings(webhook_allow_private_urls=True))


def test_the_dev_flag_is_refused_outside_dev_and_test() -> None:
    with pytest.raises(ValueError, match="WEBHOOK_ALLOW_PRIVATE_URLS"):
        make_settings("org_x", app_env="sandbox", webhook_allow_private_urls=True)


def test_event_type_lists_are_checked() -> None:
    assert check_types(["*"]) == ("*",)
    assert check_types(["payment_intent.confirmed", "payment_intent.confirmed"]) == (
        "payment_intent.confirmed",
    )
    with pytest.raises(EndpointError) as e:
        check_types(["payment_intent.teleported"])
    assert e.value.code == "unknown_event_type"
    with pytest.raises(EndpointError):
        check_types([])


def test_retry_schedule_is_g20() -> None:
    assert (
        timedelta(minutes=1),
        timedelta(minutes=5),
        timedelta(minutes=30),
        timedelta(hours=2),
        timedelta(hours=6),
        timedelta(hours=24),
    ) == delivery.RETRY_DELAYS
    assert delivery.MAX_ATTEMPTS == 7
