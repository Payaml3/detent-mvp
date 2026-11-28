"""EXE-10 (the Sev 1 invariant monitor), OPS-01 (incident records) and CON-10 (the Settings screen)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from conftest import login, make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import Actor, verify_chain
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.domain.states import Status
from detent.execution.kill_switch import is_engaged
from detent.execution.modes import ModeError, approve_mode_change, propose_mode_change
from detent.incidents import records
from detent.incidents.monitor import check_all, check_org, find_violations
from detent.intents.transition import transition
from detent.runtime import Runtime
from detent.worker.loop import Worker
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, text

pytestmark = pytest.mark.db

HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}


@pytest.fixture
def setup(engine: Engine, clock: FrozenClock) -> Iterator[tuple[DecisionOrg, TestClient]]:
    d = setup_decision_org(engine, clock)
    s = make_settings(d.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield d, c


def create(api: TestClient, d: DecisionOrg, body: dict[str, object]) -> str:
    r = api.post("/v1/payment_intents", json=body, headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def escalated(api: TestClient, d: DecisionOrg) -> str:
    dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": d.wallets["WALLET_BLUEFIN_BASE"]}
    return create(api, d, payout("cpt_bluefin", "18500.00", "USDC", dest, reference="INV-2026-0142"))


def attempt(conn: Connection, clock: FrozenClock, org: str, pid: str, no: int, tx: str) -> str:
    from detent.rails.registry import install_rail

    if not conn.execute(text("SELECT 1 FROM rails WHERE org_id=:o AND id='banksim-fps'"), {"o": org}).first():
        install_rail(conn, org, rail_id="banksim-fps", kind="banksim", network="banksim-fps", currency="GBP")
    aid = f"att_{uuid.uuid4().hex}"
    conn.execute(
        text(
            "INSERT INTO attempts (id, org_id, payment_id, attempt_no, rail_id, status, idempotency_key, tx_hash, "
            "created_at) VALUES (:id, :o, :p, :n, 'banksim-fps', 'CONFIRMED', :k, :tx, :t)"
        ),
        {"id": aid, "o": org, "p": pid, "n": no, "k": f"{pid}:{no}", "tx": tx, "t": clock.now()},
    )
    return aid


def lead(d: DecisionOrg, role: Role = Role.PAYMENTS_LEAD) -> Actor:
    return Actor(d.org.users[role], role.value)


def outbox(engine: Engine, org: str) -> list[str]:
    with engine.connect() as c:
        return list(
            c.execute(
                text("SELECT template FROM outbox WHERE org_id=:o AND template='incident_sev1'"), {"o": org}
            ).scalars()
        )


# --------------------------------------------------------------------------------------------- EXE-10
def test_a_clean_organisation_has_no_findings(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    create(api, d, payout("cpt_harbor", "2000.00", "EUR", HARBOR, reference="INV-H-1"))
    with engine.connect() as c:
        assert find_violations(c, d.id) == []
    assert d.id not in check_all(engine, clock)
    assert not is_engaged(engine, d.id)


def test_unauthorised_execution_opens_sev1_engages_the_kill_switch_and_notifies(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = escalated(api, d)  # only an ESCALATE decision: nothing authorised it to send
    ready = create(api, d, payout("cpt_harbor", "2000.00", "EUR", HARBOR, reference="INV-H-2"))
    with engine.begin() as conn:
        for st in (Status.READY, Status.SUBMITTED):
            transition(conn, clock, org_id=d.id, payment_id=pid, to=st, actor=Actor.system("test"))
        attempt(conn, clock, d.id, pid, 1, "0xabc")
    opened = check_all(engine, clock)
    assert len(opened[d.id]) == 1
    inc_id = opened[d.id][0]
    assert is_engaged(engine, d.id)
    with engine.connect() as c:
        inc = c.execute(
            text("SELECT * FROM incidents WHERE org_id=:o AND id=:i"), {"o": d.id, "i": inc_id}
        ).one()
        kinds = [e.kind for e in records.timeline(c, d.id, inc_id)]
        held = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": d.id, "p": ready}
        ).scalar_one()
        assert verify_chain(c, d.id).ok
    assert (inc.severity, inc.trigger, inc.subject_id, inc.status) == (
        1,
        "unauthorised_execution",
        pid,
        "open",
    )
    assert inc.notified_at is not None  # notification logged at once, well inside the hour
    assert kinds == ["opened", "kill_switch_engaged", "notified"]
    assert held == "HELD"  # the kill switch held the READY payment
    assert outbox(engine, d.id) == ["incident_sev1"]
    # Every minute after: the same finding never opens a second incident.
    assert d.id not in check_all(engine, clock)
    # The red banner shows on every console page.
    login(api, d.org.users[Role.REVIEWER])
    for path in ("/console/", "/console/payments", f"/console/incidents/{inc_id}"):
        html = api.get(path).text
        assert "Sev 1 incident open" in html and inc_id in html, path


def test_duplicate_payment_and_double_credit_are_found(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    """The unique indexes make these impossible, so the test drops them inside a rolled-back transaction."""
    d, api = setup
    pid = create(api, d, payout("cpt_harbor", "2000.00", "EUR", HARBOR, reference="INV-H-3"))
    conn = engine.connect()
    tx = conn.begin()
    try:
        conn.execute(text("DROP INDEX one_confirmed_attempt"))
        conn.execute(text("DROP INDEX one_credit"))
        transition(conn, clock, org_id=d.id, payment_id=pid, to=Status.SUBMITTED, actor=Actor.system("t"))
        attempt(conn, clock, d.id, pid, 1, "0x01")
        attempt(conn, clock, d.id, pid, 2, "0x02")
        conn.execute(
            text(
                "INSERT INTO inbound_transfers (id, org_id, rail_id, tx_hash, amount_minor, token, seen_at) "
                "VALUES ('inb_dup', :o, 'banksim-fps', '0xdd', 100, 'USDC', :t)"
            ),
            {"o": d.id, "t": clock.now()},
        )
        for n in (1, 2):
            conn.execute(
                text(
                    "INSERT INTO journal_entries (id, org_id, kind, deposit_id, created_at) "
                    "VALUES (:j, :o, 'deposit', 'inb_dup', :t)"
                ),
                {"j": f"jrn_dup{n}", "o": d.id, "t": clock.now()},
            )
            conn.execute(
                text(
                    "INSERT INTO credits (id, org_id, inbound_transfer_id, account_ref, amount_minor, currency, "
                    "journal_id, created_at) VALUES (:c, :o, 'inb_dup', 'acct', 100, 'USDC', :j, :t)"
                ),
                {"c": f"crd_dup{n}", "o": d.id, "j": f"jrn_dup{n}", "t": clock.now()},
            )
        found = {v.trigger: v.subject_id for v in find_violations(conn, d.id)}
        assert found == {"duplicate_payment": pid, "double_credit": "inb_dup"}
        assert len(check_org(conn, clock, d.id)) == 2
    finally:
        tx.rollback()
        conn.close()


def test_kill_switch_engagement_is_configurable(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = escalated(api, d)
    with engine.begin() as conn:
        for st in (Status.READY, Status.SUBMITTED):
            transition(conn, clock, org_id=d.id, payment_id=pid, to=st, actor=Actor.system("test"))
        attempt(conn, clock, d.id, pid, 1, "0xabc")
    assert check_all(engine, clock, kill_switch=False)[d.id]
    assert not is_engaged(engine, d.id)


def test_the_worker_runs_the_monitor_every_minute_and_after_each_confirmation(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = create(api, d, payout("cpt_harbor", "2000.00", "EUR", HARBOR, reference="INV-H-4"))
    with engine.begin() as conn:
        for st in (Status.SUBMITTED, Status.CONFIRMED):
            transition(conn, clock, org_id=d.id, payment_id=pid, to=st, actor=Actor.system("test"))
        job = conn.execute(
            text("SELECT count(*) FROM jobs WHERE org_id=:o AND payment_id=:p AND kind='invariants.check'"),
            {"o": d.id, "p": pid},
        ).scalar_one()
    assert job == 1
    s = make_settings(d.id, api_key_pepper=SecretStr(PEPPER))
    assert s.invariant_monitor_seconds == 60.0 and s.invariant_monitor_kill_switch
    w = Worker(Runtime(s, engine, clock), worker_id="w-test", org_id=d.id)
    assert w.check_invariants(force=True) == {}
    assert w.check_invariants() == {}  # within the minute: skipped


# --------------------------------------------------------------------------------------------- OPS-01
def test_manual_incident_timeline_notification_root_cause_and_replay(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = escalated(api, d)
    oncall = lead(d, Role.ONCALL)
    inc = records.open_manually(
        engine, clock, org_id=d.id, actor=oncall, severity=1, title="Rail sent twice?"
    )
    with engine.connect() as c:
        row = c.execute(
            text("SELECT * FROM incidents WHERE org_id=:o AND id=:i"), {"o": d.id, "i": inc}
        ).one()
    assert not records.notification_overdue(row, clock.now() + timedelta(minutes=59))
    assert records.notification_overdue(row, clock.now() + timedelta(minutes=61))
    with pytest.raises(records.IncidentError, match="root cause"):
        records.resolve(engine, clock, org_id=d.id, incident_id=inc, actor=oncall)
    records.notify(
        engine, clock, org_id=d.id, incident_id=inc, actor=oncall, channel="phone", recipient="payments lead"
    )
    result = records.link_replay(engine, clock, org_id=d.id, incident_id=inc, actor=oncall, payment_id=pid)
    assert result["match"] is True and result["model_called"] is False
    records.set_root_cause(
        engine, clock, org_id=d.id, incident_id=inc, actor=oncall, root_cause="False alarm: one transfer."
    )
    records.resolve(engine, clock, org_id=d.id, incident_id=inc, actor=oncall)
    with engine.connect() as c:
        row = c.execute(
            text("SELECT * FROM incidents WHERE org_id=:o AND id=:i"), {"o": d.id, "i": inc}
        ).one()
        ev = [e.kind for e in records.timeline(c, d.id, inc)]
        audit = (
            c.execute(
                text("SELECT kind FROM audit_events WHERE org_id=:o AND subject_id=:i ORDER BY seq"),
                {"o": d.id, "i": inc},
            )
            .scalars()
            .all()
        )
        with pytest.raises(Exception, match="append-only"):
            c.execute(text("DELETE FROM incident_events WHERE org_id=:o"), {"o": d.id})
    assert row.status == "resolved" and row.notified_at is not None and row.root_cause
    assert ev == ["opened", "notified", "replay_linked", "root_cause", "resolved"]
    assert audit == [f"incident.{k}" for k in ev]
    with pytest.raises(records.IncidentError):
        records.open_manually(engine, clock, org_id=d.id, actor=oncall, severity=5, title="x")


def test_console_incidents_screens(setup: tuple[DecisionOrg, TestClient], engine: Engine) -> None:
    d, api = setup
    login(api, d.org.users[Role.REVIEWER])
    assert api.get("/console/incidents").status_code == 200
    assert api.post("/console/incidents", data={"severity": 2, "title": "x"}).status_code == 403
    login(api, d.org.users[Role.PAYMENTS_LEAD])
    r = api.post(
        "/console/incidents", data={"severity": 2, "title": "Replay mismatch seen"}, follow_redirects=False
    )
    assert r.status_code == 303
    inc = r.headers["location"].rsplit("/", 1)[1]
    page = api.get(f"/console/incidents/{inc}").text
    assert "Sev 2: Replay mismatch seen" in page and "Log notification" in page
    r = api.post(f"/console/incidents/{inc}/resolve", follow_redirects=False)
    assert "root%20cause" in r.headers["location"]
    api.post(f"/console/incidents/{inc}/root_cause", data={"root_cause": "Rule file edited by hand."})
    api.post(f"/console/incidents/{inc}/resolve")
    assert "resolved" in api.get(f"/console/incidents/{inc}").text
    assert api.get("/console/incidents/inc_nope").status_code == 404


# --------------------------------------------------------------------------------------------- CON-10
def test_fail_safe_changes_need_both_leads(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, _api = setup
    pl, cl = lead(d), lead(d, Role.COMPLIANCE_LEAD)
    with pytest.raises(ModeError):
        propose_mode_change(
            engine, clock, org_id=d.id, actor=pl, to_mode="auto", reason="x", setting="fail_safe"
        )
    ch = propose_mode_change(
        engine,
        clock,
        org_id=d.id,
        actor=pl,
        to_mode="hold",
        reason="hold while we review",
        setting="fail_safe",
    )
    # A mode change can wait at the same time: each setting has its own open change.
    propose_mode_change(engine, clock, org_id=d.id, actor=cl, to_mode="assist", reason="pilot")
    with pytest.raises(ModeError, match="both"):
        approve_mode_change(engine, clock, org_id=d.id, change_id=ch, actor=pl)
    approve_mode_change(engine, clock, org_id=d.id, change_id=ch, actor=cl)
    with engine.connect() as c:
        org = c.execute(text("SELECT mode, fail_safe FROM organisations WHERE org_id=:o"), {"o": d.id}).one()
        kinds = (
            c.execute(
                text(
                    "SELECT kind FROM audit_events WHERE org_id=:o AND kind LIKE 'org.fail_safe%' ORDER BY seq"
                ),
                {"o": d.id},
            )
            .scalars()
            .all()
        )
    assert (org.mode, org.fail_safe) == ("auto", "hold")
    assert kinds == ["org.fail_safe_change_proposed", "org.fail_safe_changed"]


def test_settings_screen_shows_fail_safe_deadlines_and_weights(
    setup: tuple[DecisionOrg, TestClient], engine: Engine
) -> None:
    d, api = setup
    login(api, d.org.users[Role.PAYMENTS_LEAD])
    html = api.get("/console/settings").text
    for s in (
        'data-section="fail-safe"',
        "Deadlines (read-only in the prototype)",
        "Routing weights",
        "liquidity",
    ):
        assert s in html, s
    r = api.post(
        "/console/settings/mode/propose",
        data={"setting": "fail_safe", "to_mode": "hold", "reason": "test"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "error" not in r.headers["location"]
    login(api, d.org.users[Role.COMPLIANCE_LEAD])
    assert "Approve the fail-safe change" in api.get("/console/settings").text
