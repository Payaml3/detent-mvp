"""EXE-09, C-09, G-09, G-16: Shadow, Assist and Auto; two-person mode changes; the Send click."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from conftest import make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.domain.states import Status
from detent.execution.modes import (
    ModeError,
    approve_mode_change,
    confirm_send,
    orchestrate_status,
    propose_mode_change,
)
from detent.execution.send import send_payment
from detent.policy.screening import MockScreening
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}


def make(engine: Engine, clock: FrozenClock, mode: str) -> tuple[DecisionOrg, TestClient]:
    d = setup_decision_org(engine, clock, mode=mode)
    s = make_settings(d.id, api_key_pepper=SecretStr(PEPPER))
    return d, TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False))


@pytest.fixture
def assist(engine: Engine, clock: FrozenClock) -> Iterator[tuple[DecisionOrg, TestClient]]:
    d, c = make(engine, clock, "assist")
    with c:
        yield d, c


@pytest.fixture
def auto(engine: Engine, clock: FrozenClock) -> Iterator[tuple[DecisionOrg, TestClient]]:
    d, c = make(engine, clock, "auto")
    with c:
        yield d, c


def routine(api: TestClient, d: DecisionOrg) -> dict[str, object]:
    r = api.post(
        "/v1/payment_intents",
        json=payout("cpt_harbor", "2000.00", "EUR", HARBOR, reference="INV-H-1"),
        headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def send_jobs(engine: Engine, org: str, pid: str) -> int:
    with engine.connect() as c:
        return int(
            c.execute(
                text("SELECT count(*) FROM jobs WHERE org_id=:o AND payment_id=:p AND kind='payment.send'"),
                {"o": org, "p": pid},
            ).scalar_one()
        )


def who(d: DecisionOrg, role: Role) -> Actor:
    return Actor(d.org.users[role], role.value)


def change_mode(engine: Engine, clock: FrozenClock, d: DecisionOrg, to: str) -> None:
    ch = propose_mode_change(
        engine, clock, org_id=d.id, actor=who(d, Role.PAYMENTS_LEAD), to_mode=to, reason="test"
    )
    approve_mode_change(engine, clock, org_id=d.id, change_id=ch, actor=who(d, Role.COMPLIANCE_LEAD))


def attempts(engine: Engine, org: str, pid: str) -> int:
    with engine.connect() as c:
        return int(
            c.execute(
                text("SELECT count(*) FROM attempts WHERE org_id=:o AND payment_id=:p"), {"o": org, "p": pid}
            ).scalar_one()
        )


# ----------------------------------------------------------------------------------------- the modes
def test_shadow_records_the_decision_and_sends_nothing(engine: Engine, clock: FrozenClock) -> None:
    d, api = make(engine, clock, "shadow")
    with api:
        j = routine(api, d)
    assert j["decision"]["outcome"] == "EXECUTE" and j["status"] == "SHADOWED"  # type: ignore[index]
    assert send_jobs(engine, d.id, str(j["id"])) == 0


def test_auto_sends_execute_decisions_automatically(
    auto: tuple[DecisionOrg, TestClient], engine: Engine
) -> None:
    d, api = auto
    j = routine(api, d)
    assert j["status"] == "READY" and j["awaiting_send_click"] is False
    assert send_jobs(engine, d.id, str(j["id"])) == 1


def test_assist_waits_for_a_send_click(
    assist: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = assist
    j = routine(api, d)
    pid = str(j["id"])
    assert j["status"] == "READY" and j["awaiting_send_click"] is True
    assert send_jobs(engine, d.id, pid) == 0
    # Even if a send is triggered, nothing goes out without the click.
    assert (
        send_payment(engine, clock, {}, org_id=d.id, payment_id=pid, screening=MockScreening.from_fixture())
        is Status.READY
    )
    assert attempts(engine, d.id, pid) == 0
    # G-09: the initiator (the payments lead's API key) may not click Send; a reviewer may.
    with pytest.raises(ModeError, match="initiated"):
        confirm_send(engine, clock, org_id=d.id, payment_id=pid, actor=who(d, Role.PAYMENTS_LEAD))
    with pytest.raises(ModeError, match="may not"):
        confirm_send(engine, clock, org_id=d.id, payment_id=pid, actor=who(d, Role.ONCALL))
    confirm_send(engine, clock, org_id=d.id, payment_id=pid, actor=who(d, Role.REVIEWER))
    assert send_jobs(engine, d.id, pid) == 1
    with engine.connect() as c:
        p = c.execute(
            text(
                "SELECT awaiting_send_click, send_confirmed_by FROM payment_intents WHERE org_id=:o AND id=:p"
            ),
            {"o": d.id, "p": pid},
        ).one()
        kinds = (
            c.execute(
                text("SELECT kind FROM audit_events WHERE org_id=:o AND subject_id=:p"), {"o": d.id, "p": pid}
            )
            .scalars()
            .all()
        )
    assert p.awaiting_send_click is False and p.send_confirmed_by == d.org.users[Role.REVIEWER]
    assert "payment.send_confirmed" in kinds
    with pytest.raises(ModeError, match="not waiting"):
        confirm_send(engine, clock, org_id=d.id, payment_id=pid, actor=who(d, Role.REVIEWER))


def test_send_click_over_the_api(assist: tuple[DecisionOrg, TestClient], engine: Engine) -> None:
    d, api = assist
    pid = str(routine(api, d)["id"])
    r = api.post(f"/v1/payment_intents/{pid}/send", headers=d.auth())
    assert r.status_code == 403 and r.json()["error"]["code"] == "self_approval_forbidden"


# --------------------------------------------------------------------------------- G-16, mode change
def test_mode_is_read_at_send_time(
    auto: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = auto
    pid = str(routine(api, d)["id"])  # READY under Auto, send job queued
    change_mode(engine, clock, d, "assist")
    st = send_payment(engine, clock, {}, org_id=d.id, payment_id=pid, screening=MockScreening.from_fixture())
    assert st is Status.READY and attempts(engine, d.id, pid) == 0
    with engine.connect() as c:
        assert (
            c.execute(
                text("SELECT awaiting_send_click FROM payment_intents WHERE org_id=:o AND id=:p"),
                {"o": d.id, "p": pid},
            ).scalar_one()
            is True
        )


def test_shadow_after_ready_sends_nothing_even_with_a_click(
    auto: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = auto
    pid = str(routine(api, d)["id"])
    change_mode(engine, clock, d, "shadow")
    assert (
        send_payment(engine, clock, {}, org_id=d.id, payment_id=pid, screening=MockScreening.from_fixture())
        is Status.READY
    )
    with pytest.raises(ModeError, match="shadow"):
        confirm_send(engine, clock, org_id=d.id, payment_id=pid, actor=who(d, Role.REVIEWER))
    assert attempts(engine, d.id, pid) == 0


def test_mode_change_needs_both_leads_as_two_people(engine: Engine, clock: FrozenClock) -> None:
    d = setup_decision_org(engine, clock, mode="shadow")
    pl, cl = who(d, Role.PAYMENTS_LEAD), who(d, Role.COMPLIANCE_LEAD)
    with pytest.raises(ModeError, match="may not"):
        propose_mode_change(
            engine, clock, org_id=d.id, actor=who(d, Role.REVIEWER), to_mode="auto", reason="x"
        )
    ch = propose_mode_change(engine, clock, org_id=d.id, actor=pl, to_mode="assist", reason="pilot week 2")
    with pytest.raises(ModeError, match="both"):
        approve_mode_change(engine, clock, org_id=d.id, change_id=ch, actor=pl)
    with pytest.raises(ModeError, match="both"):
        approve_mode_change(engine, clock, org_id=d.id, change_id=ch, actor=who(d, Role.REVIEWER))
    with pytest.raises(ModeError, match="already"):
        propose_mode_change(engine, clock, org_id=d.id, actor=cl, to_mode="auto", reason="x")
    approve_mode_change(engine, clock, org_id=d.id, change_id=ch, actor=cl)
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT mode FROM organisations WHERE org_id=:o"), {"o": d.id}).scalar_one()
            == "assist"
        )
        ev = c.execute(
            text("SELECT payload FROM audit_events WHERE org_id=:o AND kind='org.mode_changed'"), {"o": d.id}
        ).scalar_one()
    assert ev == {
        "from": "shadow",
        "to": "assist",
        "proposed_by": pl.id,
        "approved_by": cl.id,
        "reason": "pilot week 2",
        "change_id": ch,
    }
    with pytest.raises(ModeError, match="already"):
        propose_mode_change(engine, clock, org_id=d.id, actor=cl, to_mode="assist", reason="x")


def test_orchestrate_means_routing_with_two_or_more_rails(engine: Engine, clock: FrozenClock) -> None:
    from detent.rails.registry import install_rail

    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        assert orchestrate_status(c, d.id) == {"enabled": False, "rails": 0}
        install_rail(
            c, d.id, rail_id="banksim-sepa-inst", kind="banksim", network="banksim-sepa-inst", currency="EUR"
        )
        assert orchestrate_status(c, d.id) == {"enabled": False, "rails": 1}
        install_rail(c, d.id, rail_id="banksim-fps", kind="banksim", network="banksim-fps", currency="GBP")
        assert orchestrate_status(c, d.id) == {"enabled": True, "rails": 2}
        c.execute(text("UPDATE rails SET enabled=false WHERE org_id=:o AND id='banksim-fps'"), {"o": d.id})
        assert orchestrate_status(c, d.id) == {"enabled": False, "rails": 1}
