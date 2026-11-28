"""INT-05: cancel an escalated, held or ready intent; SUBMITTED or UNKNOWN answers 409; CANCELLED is terminal."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from conftest import login, make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.domain.states import Status
from detent.execution.kill_switch import engage
from detent.execution.send import send_payment
from detent.intents.cancel import NotCancellable, cancel_intent
from detent.intents.transition import transition
from detent.policy.screening import MockScreening
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}


@pytest.fixture
def setup(engine: Engine, clock: FrozenClock) -> Iterator[tuple[DecisionOrg, TestClient]]:
    d = setup_decision_org(engine, clock)
    s = make_settings(d.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield d, c


def create(api: TestClient, d: DecisionOrg, body: dict[str, object]) -> dict[str, object]:
    r = api.post("/v1/payment_intents", json=body, headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 201, r.text
    return dict(r.json())


def routine(api: TestClient, d: DecisionOrg) -> str:
    return str(create(api, d, payout("cpt_harbor", "2000.00", "EUR", HARBOR, reference="INV-H-1"))["id"])


def escalated(api: TestClient, d: DecisionOrg) -> dict[str, object]:
    dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": d.wallets["WALLET_BLUEFIN_BASE"]}
    return create(api, d, payout("cpt_bluefin", "18500.00", "USDC", dest, reference="INV-2026-0142"))


def status(engine: Engine, org: str, pid: str) -> str:
    with engine.connect() as c:
        return str(
            c.execute(
                text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org, "p": pid}
            ).scalar_one()
        )


def force(engine: Engine, clock: FrozenClock, org: str, pid: str, *path: Status) -> None:
    with engine.begin() as conn:
        for st in path:
            transition(conn, clock, org_id=org, payment_id=pid, to=st, actor=Actor.system("test"))


def lead(d: DecisionOrg) -> Actor:
    return Actor(d.org.users[Role.PAYMENTS_LEAD], Role.PAYMENTS_LEAD.value)


def cancel(api: TestClient, d: DecisionOrg, pid: str, reason: str = "no longer owed") -> object:
    return api.post(f"/v1/payment_intents/{pid}/cancel", json={"reason": reason}, headers=d.auth())


def test_cancel_a_ready_payment_and_the_send_job_then_sends_nothing(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = routine(api, d)
    assert status(engine, d.id, pid) == "READY"
    r = cancel(api, d, pid)
    assert r.status_code == 200, r.text  # type: ignore[attr-defined]
    assert r.json()["status"] == "CANCELLED"  # type: ignore[attr-defined]
    # The queued send job runs afterwards: it sees CANCELLED under the lock and sends nothing.
    st = send_payment(engine, clock, {}, org_id=d.id, payment_id=pid, screening=MockScreening.from_fixture())
    assert st == Status.CANCELLED
    with engine.connect() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM attempts WHERE org_id=:o AND payment_id=:p"), {"o": d.id, "p": pid}
            ).scalar_one()
            == 0
        )
        ev = c.execute(
            text(
                "SELECT actor, payload FROM audit_events WHERE org_id=:o AND subject_id=:p "
                "AND kind='payment.cancelled'"
            ),
            {"o": d.id, "p": pid},
        ).one()
    assert ev.actor == d.org.users[Role.PAYMENTS_LEAD]
    assert ev.payload["reason"] == "no longer owed" and ev.payload["from"] == "READY"


def test_cancel_an_escalated_payment_resolves_its_case(
    setup: tuple[DecisionOrg, TestClient], engine: Engine
) -> None:
    d, api = setup
    p = escalated(api, d)
    case_id = p["exception"]["id"]  # type: ignore[index]
    r = cancel(api, d, str(p["id"]))
    assert r.status_code == 200  # type: ignore[attr-defined]
    with engine.connect() as c:
        case = c.execute(
            text(
                "SELECT status, resolution, resolution_reason FROM exception_cases WHERE org_id=:o AND id=:c"
            ),
            {"o": d.id, "c": case_id},
        ).one()
    assert (case.status, case.resolution, case.resolution_reason) == (
        "RESOLVED",
        "cancelled",
        "no longer owed",
    )


def test_cancel_a_held_payment(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = routine(api, d)
    engage(engine, clock, org_id=d.id, actor=lead(d))
    assert status(engine, d.id, pid) == "HELD"
    cancel_intent(engine, clock, org_id=d.id, payment_id=pid, actor=lead(d), reason="duplicate invoice")
    assert status(engine, d.id, pid) == "CANCELLED"


@pytest.mark.parametrize(
    "path", [(Status.SUBMITTED,), (Status.SUBMITTED, Status.UNKNOWN)], ids=["SUBMITTED", "UNKNOWN"]
)
def test_submitted_or_unknown_answers_409(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock, path: tuple[Status, ...]
) -> None:
    d, api = setup
    pid = routine(api, d)
    force(engine, clock, d.id, pid, *path)
    r = cancel(api, d, pid)
    assert r.status_code == 409  # type: ignore[attr-defined]
    assert r.json()["error"]["code"] == "not_cancellable"  # type: ignore[attr-defined]
    assert status(engine, d.id, pid) == path[-1].value


def test_cancelled_is_terminal(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = routine(api, d)
    cancel_intent(engine, clock, org_id=d.id, payment_id=pid, actor=lead(d), reason="x")
    with pytest.raises(NotCancellable):
        cancel_intent(engine, clock, org_id=d.id, payment_id=pid, actor=lead(d), reason="again")
    with pytest.raises(Exception, match="CANCELLED"):
        force(engine, clock, d.id, pid, Status.READY)
    assert cancel(api, d, pid).status_code == 409  # type: ignore[attr-defined]


def test_a_reason_is_required_and_blocked_cannot_be_cancelled(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = routine(api, d)
    r = cancel(api, d, pid, reason="")
    assert r.status_code == 422  # type: ignore[attr-defined]
    force(engine, clock, d.id, pid, Status.BLOCKED)
    assert cancel(api, d, pid).status_code == 409  # type: ignore[attr-defined]
    assert cancel(api, d, "pay_nope").status_code == 404  # type: ignore[attr-defined]


def test_console_cancel_is_payments_lead_only(setup: tuple[DecisionOrg, TestClient], engine: Engine) -> None:
    d, api = setup
    pid = routine(api, d)
    login(api, d.org.users[Role.REVIEWER])
    assert "Cancel this payment" not in api.get(f"/console/payments/{pid}").text
    r = api.post(f"/console/payments/{pid}/cancel", data={"reason": "x"}, follow_redirects=False)
    assert r.status_code == 403
    login(api, d.org.users[Role.PAYMENTS_LEAD])
    assert "Cancel this payment" in api.get(f"/console/payments/{pid}").text
    r = api.post(
        f"/console/payments/{pid}/cancel", data={"reason": "paid twice by mistake"}, follow_redirects=False
    )
    assert r.status_code == 303 and "error" not in r.headers["location"]
    assert status(engine, d.id, pid) == "CANCELLED"
