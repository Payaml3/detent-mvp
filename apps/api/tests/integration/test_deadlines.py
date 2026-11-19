"""EXC-06, G-04, G-05: the deadline sweeper. A timeout never becomes an approval (invariant 7)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from conftest import make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.exceptions.cases import NotPermitted, approve
from detent.exceptions.deadlines import approved_by_timeout, sweep, sweep_all
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


def escalate(api: TestClient, d: DecisionOrg) -> str:
    dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": d.wallets["WALLET_BLUEFIN_BASE"]}
    body = payout("cpt_bluefin", "18500.00", "USDC", dest, reference="INV-2026-0142")
    r = api.post("/v1/payment_intents", json=body, headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 201 and r.json()["status"] == "ESCALATED", r.text
    return str(r.json()["id"])


def case_of(engine: Engine, org: str, pid: str) -> object:
    with engine.connect() as c:
        return c.execute(
            text("SELECT * FROM exception_cases WHERE org_id=:o AND payment_id=:p"), {"o": org, "p": pid}
        ).one()


def outbox(engine: Engine, org: str) -> list[tuple[str, str, str]]:
    with engine.connect() as c:
        rows = c.execute(
            text("SELECT recipient, template, body FROM outbox WHERE org_id=:o ORDER BY created_at, id"),
            {"o": org},
        ).all()
    return [(r.recipient, r.template, r.body) for r in rows]


def payment_status(engine: Engine, org: str, pid: str) -> str:
    with engine.connect() as c:
        return str(
            c.execute(
                text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org, "p": pid}
            ).scalar_one()
        )


def send_jobs(engine: Engine, org: str, pid: str) -> int:
    with engine.connect() as c:
        return int(
            c.execute(
                text("SELECT count(*) FROM jobs WHERE org_id=:o AND payment_id=:p AND kind='payment.send'"),
                {"o": org, "p": pid},
            ).scalar_one()
        )


def test_before_the_deadline_nothing_happens(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pid = escalate(api, dorg)
    clock.advance(timedelta(hours=1, minutes=59))
    assert sweep(engine, clock, dorg.id) == []
    assert case_of(engine, dorg.id, pid).status == "OPEN"  # type: ignore[attr-defined]


def test_overdue_case_is_held_counterparty_told_and_backup_owner_takes_over(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pid = escalate(api, dorg)
    before = case_of(engine, dorg.id, pid)
    clock.advance(timedelta(hours=2, minutes=1))
    [case_id] = sweep(engine, clock, dorg.id)
    c = case_of(engine, dorg.id, pid)
    assert c.id == case_id == before.id  # type: ignore[attr-defined]
    assert c.status == "HELD_OVERDUE" and c.resolution is None  # type: ignore[attr-defined]
    assert c.owner_id == dorg.org.users[Role.BACKUP_OWNER]  # type: ignore[attr-defined]
    assert c.overdue_count == 1  # type: ignore[attr-defined]
    # G-04: the same length as the original deadline (2 h, tier 1), from takeover.
    assert c.deadline_at == clock.now() + timedelta(hours=2)  # type: ignore[attr-defined]
    # The payment stays held: still ESCALATED, nothing queued to send.
    assert payment_status(engine, dorg.id, pid) == "ESCALATED"
    assert send_jobs(engine, dorg.id, pid) == 0
    box = outbox(engine, dorg.id)
    told = [b for b in box if b[1] == "case.counterparty_update"]
    assert len(told) == 1 and told[0][0] == "payables@bluefin.example.invalid"
    assert "INV-2026-0142" in told[0][2] and "still being reviewed" in told[0][2]
    assigned = [b for b in box if b[1] == "case.overdue_assigned"]
    assert [a[0] for a in assigned] == [f"{dorg.org.users[Role.BACKUP_OWNER]}@test.invalid"]
    with engine.connect() as conn:
        kinds = (
            conn.execute(
                text("SELECT kind FROM audit_events WHERE org_id=:o AND subject_id=:s ORDER BY seq"),
                {"o": dorg.id, "s": case_id},
            )
            .scalars()
            .all()
        )
    assert kinds[-1] == "case.overdue"
    assert approved_by_timeout(engine, dorg.id) == 0


def test_sweeping_twice_is_a_no_op(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    escalate(api, dorg)
    clock.advance(timedelta(hours=3))
    assert len(sweep(engine, clock, dorg.id)) == 1
    n = len(outbox(engine, dorg.id))
    assert sweep(engine, clock, dorg.id) == []
    assert len(outbox(engine, dorg.id)) == n


def test_second_miss_goes_to_the_payments_lead_and_the_payment_stays_held(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pid = escalate(api, dorg)
    for _ in range(4):  # far past every deadline, swept repeatedly
        clock.advance(timedelta(hours=2, minutes=1))
        sweep(engine, clock, dorg.id)
    c = case_of(engine, dorg.id, pid)
    assert c.status == "HELD_OVERDUE" and c.overdue_count == 4  # type: ignore[attr-defined]
    assert c.owner_id == dorg.org.users[Role.PAYMENTS_LEAD]  # type: ignore[attr-defined]
    assert payment_status(engine, dorg.id, pid) == "ESCALATED"
    assert send_jobs(engine, dorg.id, pid) == 0
    assert approved_by_timeout(engine, dorg.id) == 0


def test_after_the_deadline_only_the_current_owner_or_payments_lead_may_approve(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:  # G-05
    pid = escalate(api, dorg)
    clock.advance(timedelta(hours=2, minutes=1))
    sweep(engine, clock, dorg.id)
    case_id = case_of(engine, dorg.id, pid).id  # type: ignore[attr-defined]
    rv = Actor(dorg.org.users[Role.REVIEWER], Role.REVIEWER.value)
    with pytest.raises(NotPermitted):
        approve(engine, clock, case_id=case_id, org_id=dorg.id, actor=rv, reason="late look")
    bo = Actor(dorg.org.users[Role.BACKUP_OWNER], Role.BACKUP_OWNER.value)
    res = approve(engine, clock, case_id=case_id, org_id=dorg.id, actor=bo, reason="checked with supplier")
    assert res.payment_status == "READY"
    assert approved_by_timeout(engine, dorg.id) == 0  # a person approved it, not the clock


def test_overdue_without_a_human_decision_is_never_approved_across_orgs(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    other = setup_decision_org(engine, clock)
    pid = escalate(api, dorg)
    clock.advance(timedelta(days=2))
    swept = sweep_all(engine, clock)
    assert swept.get(dorg.id) and other.id not in swept
    assert payment_status(engine, dorg.id, pid) == "ESCALATED"
    assert approved_by_timeout(engine, dorg.id) == 0


def test_the_worker_runs_the_sweeper(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    from detent.runtime import Runtime
    from detent.worker.loop import Worker

    pid = escalate(api, dorg)
    clock.advance(timedelta(hours=3))
    w = Worker(Runtime(make_settings(dorg.id), engine, clock), worker_id="test-sweeper")
    assert dorg.id in w.tick(force=True)
    assert w.tick() == {}  # within the cadence: not run again yet
    assert case_of(engine, dorg.id, pid).status == "HELD_OVERDUE"  # type: ignore[attr-defined]
