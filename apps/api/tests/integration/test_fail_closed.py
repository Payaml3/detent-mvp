"""POL-09: a failing dependency never gives EXECUTE; the fail-safe setting routes the payment."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from decision_helpers import DecisionOrg, payout, setup_decision_org
from detent.clock import FrozenClock
from detent.intents import service
from detent.intents.service import IntentRequest, submit_intent
from detent.policy.screening import MockScreening
from sqlalchemy import Engine

pytestmark = pytest.mark.db

HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}


class DownScreening:
    def check(self, *, address: str | None, name: str | None) -> object:
        raise TimeoutError("screening vendor timed out")


def run(engine: Engine, clock: FrozenClock, d: DecisionOrg, screening: object = None) -> dict[str, object]:
    req = IntentRequest.model_validate(payout("cpt_harbor", "2000.00", "EUR", HARBOR))
    code, body = submit_intent(
        engine,
        clock,
        org_id=d.id,
        actor_id=d.org.users[next(iter(d.org.users))],
        idempotency_key="k",
        request=req,
        decision_only=False,
        screening=screening or MockScreening.from_fixture(),
    )
    assert code == 201
    return body


@pytest.mark.parametrize(("fail_safe", "status"), [("manual_queue", "ESCALATED"), ("hold", "HELD")])
def test_screening_down(engine: Engine, clock: FrozenClock, fail_safe: str, status: str) -> None:
    d = setup_decision_org(engine, clock, fail_safe=fail_safe)
    body = run(engine, clock, d, DownScreening())
    assert body["status"] == status
    scr = next(c for c in body["decision"]["checks"] if c["check"] == "screening")  # type: ignore[index, union-attr]
    assert scr["reason"] == "SYSTEM_UNAVAILABLE" and scr["evidence"]["dependency"] == "screening"


DEPENDENCIES = [
    "load_counterparty",
    "load_destination",
    "read_counters",
    "find_recent_block",
    "load_travel_rule",
]


@pytest.mark.parametrize("dep", DEPENDENCIES)
@pytest.mark.parametrize(("fail_safe", "status"), [("manual_queue", "ESCALATED"), ("hold", "HELD")])
def test_each_data_read_failing_fails_closed(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch, dep: str, fail_safe: str, status: str
) -> None:
    d = setup_decision_org(engine, clock, fail_safe=fail_safe)

    def broken(*a: object, **k: object) -> object:
        raise ConnectionError(f"{dep} failed")

    monkeypatch.setattr(service, dep, broken)
    body = run(engine, clock, d)
    assert body["status"] == status
    assert body["decision"]["outcome"] == "ESCALATE"  # type: ignore[index]
    assert any(c.get("reason") == "SYSTEM_UNAVAILABLE" for c in body["decision"]["checks"])  # type: ignore[index, union-attr]


def test_policy_crash_fails_closed(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = setup_decision_org(engine, clock)
    boom: Callable[..., object] = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("engine bug"))  # noqa: E731
    monkeypatch.setattr(service, "evaluate", boom)
    body = run(engine, clock, d)
    assert body["status"] == "ESCALATED" and body["decision"]["outcome"] == "ESCALATE"  # type: ignore[index]
    assert body["decision"]["checks"] == [  # type: ignore[index]
        {
            "check": "system",
            "result": "ESCALATE",
            "reason": "SYSTEM_UNAVAILABLE",
            "evidence": {"dependency": "decision", "error": "RuntimeError"},
        }
    ]
