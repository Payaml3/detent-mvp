"""EXE-01: every status change goes through transition() under SELECT ... FOR UPDATE."""

from __future__ import annotations

from itertools import pairwise

import pytest
from decision_helpers import payout, setup_decision_org
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.states import ALLOWED, InvalidTransition, Status
from detent.intents.service import IntentRequest, submit_intent
from detent.intents.transition import apply_transition
from detent.policy.screening import MockScreening
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}


def new_payment(engine: Engine, clock: FrozenClock, org_id: str, key: str) -> str:
    req = IntentRequest.model_validate(payout("cpt_harbor", "10.00", "EUR", HARBOR))
    _, body = submit_intent(
        engine,
        clock,
        org_id=org_id,
        actor_id="usr_api",
        idempotency_key=key,
        request=req,
        decision_only=False,
        screening=MockScreening.from_fixture(),
    )
    return str(body["id"])


def test_illegal_transition_raises_changes_nothing_and_is_audited(engine: Engine, clock: FrozenClock) -> None:
    d = setup_decision_org(engine, clock)
    pid = new_payment(engine, clock, d.id, "t1")  # READY
    with pytest.raises(InvalidTransition):
        apply_transition(
            engine,
            clock,
            org_id=d.id,
            payment_id=pid,
            to=Status.CONFIRMED,
            actor=Actor("usr_x", "reviewer"),
            reason="skip the rail",
        )
    with engine.connect() as c:
        st_ = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": d.id, "p": pid}
        ).scalar()
        ev = c.execute(
            text(
                "SELECT actor, payload FROM audit_events WHERE org_id=:o AND subject_id=:p "
                "AND kind='payment.transition_refused'"
            ),
            {"o": d.id, "p": pid},
        ).one()
    assert st_ == "READY"
    assert ev.actor == "usr_x" and ev.payload == {
        "from": "READY",
        "to": "CONFIRMED",
        "reason": "skip the rail",
    }


def test_terminal_states_never_change(engine: Engine, clock: FrozenClock) -> None:
    d = setup_decision_org(engine, clock)
    pid = new_payment(engine, clock, d.id, "t2")
    apply_transition(engine, clock, org_id=d.id, payment_id=pid, to=Status.CANCELLED, actor=Actor("usr_x"))
    for target in Status:
        with pytest.raises(InvalidTransition):
            apply_transition(engine, clock, org_id=d.id, payment_id=pid, to=target, actor=Actor("usr_x"))


@pytest.fixture(scope="module")
def shared(engine: Engine) -> object:
    clock = FrozenClock()
    return setup_decision_org(engine, clock), clock


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st.sampled_from(list(Status)), max_size=12))
def test_random_requests_never_leave_the_table(engine: Engine, shared: object, events: list[Status]) -> None:
    d, clock = shared  # type: ignore[misc]
    pid = new_payment(engine, clock, d.id, f"prop-{clock.now().timestamp()}-{id(events)}")
    clock.advance(__import__("datetime").timedelta(seconds=1))
    with engine.connect() as c:
        start = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": d.id, "p": pid}
        ).scalar()
    path = [Status(start)]  # READY, or ESCALATED once an earlier example blocked a payment to the same payee
    for target in events:
        try:
            apply_transition(
                engine, clock, org_id=d.id, payment_id=pid, to=target, actor=Actor.system("prop")
            )
            path.append(target)
        except InvalidTransition:
            pass
    for a, b in pairwise(path):
        assert b in ALLOWED[a]
    with engine.connect() as c:
        final = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": d.id, "p": pid}
        ).scalar()
    assert final == path[-1].value
