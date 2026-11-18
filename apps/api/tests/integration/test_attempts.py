"""EXE-02: attempts and exactly-once guarantees."""

from __future__ import annotations

import pytest
from decision_helpers import payout, setup_decision_org
from detent.clock import FrozenClock
from detent.domain.states import AttemptStatus, FailureClass
from detent.execution.attempts import AttemptNotAllowed, create_attempt, mark_attempt, rail_idempotency_key
from detent.intents.service import IntentRequest, submit_intent
from detent.policy.screening import MockScreening
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}


@pytest.fixture
def pid_org(engine: Engine, clock: FrozenClock) -> tuple[str, str]:
    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO rails (id, org_id, kind, network, currency) VALUES "
                "('banksim-sepa-inst', :o, 'banksim', 'banksim-sepa-inst', 'EUR'), ('banksim-fps', :o, 'banksim', 'banksim-fps', 'GBP')"
            ),
            {"o": d.id},
        )
    req = IntentRequest.model_validate(payout("cpt_harbor", "10.00", "EUR", HARBOR))
    _, body = submit_intent(
        engine,
        clock,
        org_id=d.id,
        actor_id="usr_api",
        idempotency_key="a",
        request=req,
        decision_only=False,
        screening=MockScreening.from_fixture(),
    )
    return d.id, str(body["id"])


def test_one_attempt_in_flight(engine: Engine, clock: FrozenClock, pid_org: tuple[str, str]) -> None:
    org, pid = pid_org
    with engine.begin() as c:
        a = create_attempt(c, clock, org_id=org, payment_id=pid, rail_id="banksim-sepa-inst")
        mark_attempt(c, clock, org_id=org, attempt_id=a.id, to=AttemptStatus.SUBMITTED)
    for st in (AttemptStatus.SUBMITTED, AttemptStatus.UNKNOWN):
        if st is AttemptStatus.UNKNOWN:
            with engine.begin() as c:
                mark_attempt(c, clock, org_id=org, attempt_id=a.id, to=AttemptStatus.UNKNOWN)
        with pytest.raises(AttemptNotAllowed), engine.begin() as c:
            create_attempt(c, clock, org_id=org, payment_id=pid, rail_id="banksim-sepa-inst")


def test_new_attempt_only_after_definitive_failure(
    engine: Engine, clock: FrozenClock, pid_org: tuple[str, str]
) -> None:
    org, pid = pid_org
    with engine.begin() as c:
        a = create_attempt(c, clock, org_id=org, payment_id=pid, rail_id="banksim-sepa-inst")
        mark_attempt(c, clock, org_id=org, attempt_id=a.id, to=AttemptStatus.SUBMITTED)
        mark_attempt(
            c,
            clock,
            org_id=org,
            attempt_id=a.id,
            to=AttemptStatus.FAILED,
            failure_class=FailureClass.TECHNICAL_RETRYABLE,
            evidence={"error": "503 before acceptance"},
        )
    with engine.begin() as c:
        b = create_attempt(c, clock, org_id=org, payment_id=pid, rail_id="banksim-sepa-inst")
    assert b.attempt_no == 2 and b.payment_id == pid


def test_no_attempt_after_confirmation(engine: Engine, clock: FrozenClock, pid_org: tuple[str, str]) -> None:
    org, pid = pid_org
    with engine.begin() as c:
        a = create_attempt(c, clock, org_id=org, payment_id=pid, rail_id="banksim-sepa-inst")
        mark_attempt(c, clock, org_id=org, attempt_id=a.id, to=AttemptStatus.SUBMITTED)
        mark_attempt(c, clock, org_id=org, attempt_id=a.id, to=AttemptStatus.CONFIRMED, evidence={"ref": "x"})
    with pytest.raises(AttemptNotAllowed), engine.begin() as c:
        create_attempt(c, clock, org_id=org, payment_id=pid, rail_id="banksim-sepa-inst")


def test_timeout_never_marks_an_attempt_failed(
    engine: Engine, clock: FrozenClock, pid_org: tuple[str, str]
) -> None:
    org, pid = pid_org
    with engine.begin() as c:
        a = create_attempt(c, clock, org_id=org, payment_id=pid, rail_id="banksim-sepa-inst")
        mark_attempt(c, clock, org_id=org, attempt_id=a.id, to=AttemptStatus.SUBMITTED)
    with pytest.raises(ValueError, match="TIMEOUT"), engine.begin() as c:
        mark_attempt(
            c, clock, org_id=org, attempt_id=a.id, to=AttemptStatus.FAILED, failure_class=FailureClass.TIMEOUT
        )


def test_rail_idempotency_keys_follow_spec_06() -> None:
    assert rail_idempotency_key("pay_X", "banksim-fps", first_rail_id="banksim-fps") == "pay_X"
    assert (
        rail_idempotency_key("pay_X", "banksim-sepa-inst", first_rail_id="banksim-fps")
        == "pay_X:banksim-sepa-inst"
    )
