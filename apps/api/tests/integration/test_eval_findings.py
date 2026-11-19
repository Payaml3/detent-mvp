"""Regression tests for the gaps the S8 evaluation suites found (spec/09).

- atk-bb-03: an attempt could be created for a payment that was not READY (here, BLOCKED).
- atk-mv-10: an older, validly signed mandate version could be put back in place of the current one.
- atk-wc-01/02/07: a destination changed after the decision was paid without a fresh decision.
- atk-au-02: an expired sandbox organisation's keys still worked.
- flt-cr-01/04: a worker that died after storing the signed transaction, before broadcasting it, left the
  payment SUBMITTED for ever.
"""

from __future__ import annotations

import json
import uuid

import pytest
from decision_helpers import payout, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.money import Money
from detent.domain.states import AttemptStatus, Status
from detent.execution.attempts import AttemptNotAllowed, create_attempt, mark_attempt
from detent.execution.send import recover_interrupted_send, send_payment
from detent.intents.registry import update_destination
from detent.intents.service import IntentRequest, submit_intent
from detent.intents.transition import transition
from detent.mandates.store import fixture_mandate, issue_mandate, verify
from detent.policy.facts import MandateFacts
from detent.policy.screening import MockScreening
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.db

HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}
KEY = SecretStr("test-mandate-key-0123456789abcdef")


def _org_with_bank_rails(engine: Engine, clock: FrozenClock) -> str:
    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO rails (id, org_id, kind, network, currency) VALUES "
                "('banksim-sepa-inst', :o, 'banksim', 'banksim-sepa-inst', 'EUR')"
            ),
            {"o": d.id},
        )
    return d.id


def _pay(
    engine: Engine, clock: FrozenClock, org: str, amount: str = "10.00", cpt: str = "cpt_harbor"
) -> dict:
    _, body = submit_intent(
        engine,
        clock,
        org_id=org,
        actor_id="usr_api",
        idempotency_key=str(uuid.uuid4()),
        request=IntentRequest.model_validate(payout(cpt, amount, "EUR", HARBOR)),
        decision_only=False,
        screening=MockScreening.from_fixture(),
    )
    return body


def _status(engine: Engine, org: str, pid: str) -> str:
    with engine.connect() as c:
        return str(
            c.execute(
                text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org, "p": pid}
            ).scalar_one()
        )


def test_no_attempt_for_a_payment_that_is_not_ready(engine: Engine, clock: FrozenClock) -> None:
    org = _org_with_bank_rails(engine, clock)
    pid = str(_pay(engine, clock, org, "200000.00")["id"])  # above the hard maximum: BLOCKED
    assert _status(engine, org, pid) == "BLOCKED"
    with pytest.raises(AttemptNotAllowed), engine.begin() as c:
        create_attempt(c, clock, org_id=org, payment_id=pid, rail_id="banksim-sepa-inst")
    # The database refuses it too, whoever writes the row.
    with pytest.raises(DBAPIError, match="authorised to send"), engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO attempts (id, org_id, payment_id, attempt_no, rail_id, status, idempotency_key, "
                "created_at) VALUES ('att_x', :o, :p, 1, 'banksim-sepa-inst', 'CREATED', :k, now())"
            ),
            {"o": org, "p": pid, "k": f"{pid}:banksim-sepa-inst"},
        )


def test_an_older_signed_mandate_version_put_back_is_refused(engine: Engine, clock: FrozenClock) -> None:
    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        issue_mandate(c, clock, d.id, fixture_mandate(clock, d.id), KEY, actor=Actor.system("seed"))
        v1 = c.execute(
            text("SELECT payload, signature FROM mandates WHERE org_id=:o AND id='mnd_demo_ap_agent'"),
            {"o": d.id},
        ).one()
        c.execute(text("DELETE FROM mandate_usage WHERE org_id=:o"), {"o": d.id})
        c.execute(text("DELETE FROM mandates WHERE org_id=:o AND id='mnd_demo_ap_agent'"), {"o": d.id})
        v2 = fixture_mandate(clock, d.id)
        v2["version"] = 2
        v2["scope"]["max_per_payment"] = {"amount": "100.00", "currency": "USDC"}
        issue_mandate(c, clock, d.id, v2, KEY, actor=Actor.system("seed"))
        c.execute(
            text(
                "UPDATE mandates SET payload=CAST(:p AS jsonb), signature=:s WHERE org_id=:o AND "
                "id='mnd_demo_ap_agent'"
            ),
            {"p": json.dumps(dict(v1.payload)), "s": v1.signature, "o": d.id},
        )
        res = verify(
            c,
            org_id=d.id,
            mandate_id="mnd_demo_ap_agent",
            key=KEY,
            now=clock.now(),
            payee="cpt_bluefin",
            amount=Money.parse("50.00", "USDC"),
            network="base-sepolia",
        )
    assert isinstance(res, MandateFacts) and res.reason == "MANDATE_SIGNATURE_INVALID"


def test_a_destination_changed_after_the_decision_is_decided_again_before_sending(
    engine: Engine, clock: FrozenClock
) -> None:
    org = _org_with_bank_rails(engine, clock)
    pid = str(_pay(engine, clock, org)["id"])
    assert _status(engine, org, pid) == "READY"
    with engine.begin() as c:
        update_destination(
            c,
            clock,
            org,
            "dst_harbor_iban",
            actor=Actor("usr_x", "payments_lead"),
            account_masked="DE** **** 9999",
        )
    st = send_payment(engine, clock, {}, org_id=org, payment_id=pid, screening=MockScreening.from_fixture())
    assert st.value in ("ESCALATED", "HELD", "BLOCKED")  # never sent on the old decision
    with engine.connect() as c:
        reason = c.execute(
            text(
                "SELECT payload->>'reason' FROM audit_events WHERE org_id=:o AND subject_id=:p AND "
                "kind='decision.made' ORDER BY seq DESC LIMIT 1"
            ),
            {"o": org, "p": pid},
        ).scalar()
        n = c.execute(
            text("SELECT count(*) FROM attempts WHERE org_id=:o AND payment_id=:p"), {"o": org, "p": pid}
        )
        assert n.scalar_one() == 0
    assert reason is None or "destination_changed" in reason


def test_an_expired_organisation_gets_403_organisation_expired(engine: Engine, clock: FrozenClock) -> None:
    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        c.execute(
            text("UPDATE organisations SET expires_at=:t WHERE id=:o").execution_options(
                cross_org="test setup"
            ),
            {"t": clock.now(), "o": d.id},
        )
    from conftest import make_settings
    from decision_helpers import PEPPER

    app = create_app(
        make_settings(d.id, api_key_pepper=SecretStr(PEPPER)),
        engine=engine,
        clock=clock,
        configure_logging=False,
    )
    with TestClient(app) as client:
        r = client.get("/v1/payment_intents", headers=d.auth())
    assert r.status_code == 403 and r.json()["error"]["code"] == "organisation_expired"


def test_a_send_interrupted_before_the_broadcast_was_recorded_becomes_unknown(
    engine: Engine, clock: FrozenClock
) -> None:
    org = _org_with_bank_rails(engine, clock)
    pid = str(_pay(engine, clock, org)["id"])
    actor = Actor.system("execution")
    with engine.begin() as c:
        a = create_attempt(c, clock, org_id=org, payment_id=pid, rail_id="banksim-sepa-inst")
        mark_attempt(c, clock, org_id=org, attempt_id=a.id, to=AttemptStatus.SUBMITTED)
        transition(c, clock, org_id=org, payment_id=pid, to=Status.SUBMITTED, actor=actor, reason="test")
    # The worker died here: no rail.submitted event. When the job runs again it hands the payment to the
    # resolver as UNKNOWN (never FAILED), which looks for it before anything is sent again.
    assert recover_interrupted_send(engine, clock, org_id=org, payment_id=pid) is not None
    assert _status(engine, org, pid) == "UNKNOWN"
    with engine.connect() as c:
        att = c.execute(text("SELECT status FROM attempts WHERE org_id=:o AND id=:a"), {"o": org, "a": a.id})
        assert att.scalar_one() == "UNKNOWN"
        job = c.execute(
            text(
                "SELECT count(*) FROM jobs WHERE org_id=:o AND kind='payment.resolve_unknown' AND payment_id=:p"
            ),
            {"o": org, "p": pid},
        )
        assert job.scalar_one() == 1
    # Once a broadcast is recorded, a re-run leaves the attempt to the confirmation poller.
    assert recover_interrupted_send(engine, clock, org_id=org, payment_id=pid) is None
