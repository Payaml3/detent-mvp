"""RAL-08: rail health (success rate, p95 latency) and the circuit breaker."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import login, make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.domain.states import Status
from detent.intents.transition import transition
from detent.rails import health
from detent.rails.base import Eligibility, Health
from detent.rails.registry import install_rail
from detent.routing.engine import route
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

RAIL = "banksim-fps"


class Probe:
    """A stand-in adapter: eligible for everything; its health answer is set by the test."""

    def __init__(self, rail_id: str = RAIL, ok: bool = True) -> None:
        self.rail_id, self.ok, self.probes = rail_id, ok, 0

    def eligible(self, intent: Any) -> Eligibility:
        return Eligibility(True)

    def health(self) -> Health:
        self.probes += 1
        return Health(self.ok, None, {"probe": "test"})


@pytest.fixture
def setup(engine: Engine, clock: FrozenClock) -> Iterator[tuple[DecisionOrg, TestClient]]:
    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        install_rail(c, d.id, rail_id=RAIL, kind="banksim", network=RAIL, currency="GBP")
        install_rail(
            c, d.id, rail_id="banksim-chaps", kind="banksim", network="banksim-chaps", currency="GBP"
        )
    s = make_settings(d.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield d, c


def payment(api: TestClient, d: DecisionOrg) -> str:
    dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": d.wallets["WALLET_BLUEFIN_BASE"]}
    body = payout("cpt_bluefin", "18500.00", "USDC", dest, reference="INV-2026-0142")
    r = api.post("/v1/payment_intents", json=body, headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 201, r.text
    pid = str(r.json()["id"])
    rt = api.app.state.runtime  # type: ignore[attr-defined]
    with rt.engine.begin() as c:  # attempts need a payment authorised to send
        transition(c, rt.clock, org_id=d.id, payment_id=pid, to=Status.READY, actor=Actor.system("test"))
    return pid


def attempts(
    engine: Engine, clock: FrozenClock, d: DecisionOrg, pid: str, outcomes: list[tuple[str, str | None, int]]
) -> None:
    """(status, failure_class, seconds to resolve), oldest first, one second apart, on payment ``pid``.

    A payment has at most one CONFIRMED and one in-flight attempt (invariant 2), so a test passes a fresh
    payment for each confirmation or UNKNOWN.
    """
    with engine.begin() as c:
        start = int(c.execute(
            text("SELECT count(*) FROM attempts WHERE org_id=:o AND payment_id=:p"), {"o": d.id, "p": pid}
        ).scalar_one())  # fmt: skip
        seen = int(c.execute(
            text("SELECT count(*) FROM attempts WHERE org_id=:o AND rail_id=:r"), {"o": d.id, "r": RAIL}
        ).scalar_one())  # fmt: skip
        for i, (status, fc, secs) in enumerate(outcomes, start=1):
            at = clock.now() + timedelta(seconds=seen + i)
            c.execute(
                text(
                    "INSERT INTO attempts (id, org_id, payment_id, attempt_no, rail_id, status, failure_class, "
                    "idempotency_key, created_at, resolved_at) VALUES (:id, :o, :p, :n, :r, :s, :fc, :k, :t, :rt)"
                ),
                {
                    "id": f"att_{uuid.uuid4().hex}",
                    "o": d.id,
                    "p": pid,
                    "n": start + i,
                    "r": RAIL,
                    "s": status,
                    "fc": fc,
                    "k": f"{pid}:{start + i}",
                    "t": at,
                    "rt": at + timedelta(seconds=secs),
                },
            )


def rail(engine: Engine, d: DecisionOrg, rail_id: str = RAIL) -> Any:
    with engine.connect() as c:
        return c.execute(
            text("SELECT * FROM rails WHERE org_id=:o AND id=:r"), {"o": d.id, "r": rail_id}
        ).one()


def candidates(engine: Engine, d: DecisionOrg) -> dict[str, str | None]:
    p = SimpleNamespace(
        id="pay_x", amount_minor=1000, currency="GBP", counterparty_id=None, network_constraint=RAIL,
        allow_network_switch=False, address="acct", account_masked=None,
    )  # fmt: skip
    with engine.connect() as c:
        r = route(c, {RAIL: Probe()}, org_id=d.id, payment=p, day="2026-12-03")  # type: ignore[dict-item]
    return {x.rail: (None if x.eligible else x.reason) for x in r.candidates}


def test_success_rate_and_p95_latency(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = payment(api, d)
    # 19 confirmations taking 1..19 seconds and one rejection: 95% success; p95 is the 19th fastest of 19.
    attempts(engine, clock, d, pid, [("FAILED", "REJECTED_BY_RAIL", 1)])
    for s in range(1, 20):
        attempts(engine, clock, d, payment(api, d), [("CONFIRMED", None, s)])
    with engine.connect() as c:
        st = health.stats(c, d.id, RAIL)
    assert st["attempts"] == 20 and st["success_rate"] == "95.0%"
    assert str(st["p95_seconds"]) == "19.0"
    with engine.connect() as c:
        empty = health.stats(c, d.id, "banksim-chaps")
    assert empty["success_rate_bp"] is None and empty["p95_seconds"] is None


def test_circuit_opens_after_the_failure_count_and_leaves_routing(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = payment(api, d)
    # A rejection is a business answer: it doesn't count, and it breaks a run of failures.
    attempts(engine, clock, d, pid, [
        ("FAILED", "TECHNICAL_RETRYABLE", 1), ("FAILED", "TECHNICAL_FINAL", 1), ("FAILED", "REJECTED_BY_RAIL", 1),
    ])  # fmt: skip
    assert candidates(engine, d)[RAIL] is None
    assert health.check_rail(engine, clock, d.id, RAIL, Probe(), probe_seconds=60) == "closed"
    attempts(engine, clock, d, pid, [("FAILED", "TECHNICAL_RETRYABLE", 1)])
    attempts(engine, clock, d, payment(api, d), [("UNKNOWN", "TIMEOUT", 1)])
    assert candidates(engine, d)[RAIL] is None  # two in a row; the threshold is three
    attempts(engine, clock, d, pid, [("FAILED", "TECHNICAL_FINAL", 1)])
    # Routing sees the third failure at once, before the worker records it.
    assert candidates(engine, d)[RAIL] == "CIRCUIT_OPEN"
    probe = Probe(ok=False)
    assert health.check_rail(engine, clock, d.id, RAIL, probe, probe_seconds=60) == "open"
    assert probe.probes == 0  # opening doesn't probe
    r = rail(engine, d)
    assert r.circuit_state == "open" and r.circuit_changed_at == clock.now()
    with engine.connect() as c:
        ev = c.execute(
            text("SELECT payload FROM audit_events WHERE org_id=:o AND kind='rail.circuit_opened'"),
            {"o": d.id},
        ).scalar_one()
    assert ev == {"failures_in_a_row": 3, "threshold": 3}


def test_circuit_closes_after_a_successful_probe(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = payment(api, d)
    with engine.begin() as c:  # the failure count is configured per rail
        c.execute(
            text("UPDATE rails SET circuit_failures=2 WHERE org_id=:o AND id=:r"), {"o": d.id, "r": RAIL}
        )
    attempts(engine, clock, d, pid, [("FAILED", "TECHNICAL_RETRYABLE", 1)] * 2)
    assert health.check_rail(engine, clock, d.id, RAIL, Probe(), probe_seconds=60) == "open"
    down = Probe(ok=False)
    assert health.check_rail(engine, clock, d.id, RAIL, down, probe_seconds=60) == "open"
    assert down.probes == 1 and rail(engine, d).circuit_probe_ok is False
    clock.advance(timedelta(seconds=30))
    assert health.check_rail(engine, clock, d.id, RAIL, down, probe_seconds=60) == "open"
    assert down.probes == 1  # not probed again until the interval passes
    assert (
        health.check_rail(engine, clock, d.id, RAIL, None, probe_seconds=0) == "open"
    )  # no adapter: stays open
    clock.advance(timedelta(seconds=60))
    up = Probe(ok=True)
    assert health.check_rail(engine, clock, d.id, RAIL, up, probe_seconds=60) == "closed"
    assert up.probes == 1
    r = rail(engine, d)
    assert r.circuit_state == "closed" and r.circuit_probe_ok is True
    # The count starts again from the close: the old failures no longer count.
    assert candidates(engine, d)[RAIL] is None
    with engine.connect() as c:
        kinds = list(c.execute(
            text("SELECT kind FROM audit_events WHERE org_id=:o AND kind LIKE 'rail.circuit_%' ORDER BY seq"),
            {"o": d.id},
        ).scalars())  # fmt: skip
    assert kinds == ["rail.circuit_opened", "rail.circuit_closed"]


def test_the_worker_checks_every_organisations_rails(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = payment(api, d)
    attempts(engine, clock, d, pid, [("FAILED", "TECHNICAL_RETRYABLE", 1)] * 3)
    out = health.check_all(engine, clock, make_settings(d.id, api_key_pepper=SecretStr(PEPPER)))
    assert out[d.id][RAIL] == "open" and out[d.id]["banksim-chaps"] == "closed"


def test_rails_screen_shows_health_and_circuit(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = payment(api, d)
    attempts(engine, clock, d, payment(api, d), [("CONFIRMED", None, 4)])
    attempts(engine, clock, d, pid, [("FAILED", "TECHNICAL_RETRYABLE", 1)] * 3)
    health.check_rail(engine, clock, d.id, RAIL, Probe(), probe_seconds=60)
    login(api, d.org.users[Role.PAYMENTS_LEAD])
    html = api.get("/console/rails").text
    assert "Success rate (last 50)" in html and "25.0%" in html
    assert "p95 latency" in html and "4.0 s" in html
    assert "Circuit open" in html and "out of routing" in html
