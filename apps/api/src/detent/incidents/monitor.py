"""The Sev 1 invariant monitor (EXE-10, spec/10 "Sev 1").

It runs every minute in the worker (``Worker.check_invariants``) and after each confirmation (the
``invariants.check`` job that ``transition()`` queues when a payment becomes CONFIRMED). It looks for:

- ``duplicate_payment``: two CONFIRMED attempts, or two distinct confirmed transaction hashes, for one
  payment ID (invariants 1 and 2; the partial unique index should make this impossible).
- ``unauthorised_execution``: a CONFIRMED attempt whose payment has no EXECUTE decision (an approval
  re-runs the policy and records EXECUTE, so an approved payment has one too: invariants 5 and 8).
- ``double_credit``: two credits for one inbound transfer (LED-04; the unique index should prevent it).

A hit opens one Sev 1 incident per finding, engages the kill switch (``INVARIANT_MONITOR_KILL_SWITCH``,
on by default), posts a notice to the mock outbox (which logs the notification) and shows a red banner
on every console page until the incident is resolved. The checks only read; they never send or undo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.incidents.records import _event, open_incident, record_notification

MONITOR = Actor("system:invariant_monitor", "oncall")  # on-call may engage the kill switch (invariant 10)
JOB_KIND = "invariants.check"

TITLES = {
    "duplicate_payment": "Duplicate payment: two confirmed transfers for one payment ID",
    "unauthorised_execution": "Unauthorised execution: a confirmed attempt without an EXECUTE decision",
    "double_credit": "Double credit: two credits for one inbound transfer",
}


@dataclass(frozen=True, slots=True)
class Violation:
    org_id: str
    trigger: str
    subject_id: str
    detail: dict[str, Any]


def find_violations(conn: Connection, org_id: str) -> list[Violation]:
    out: list[Violation] = []
    for r in conn.execute(
        text(
            "SELECT payment_id, count(*) AS n, count(DISTINCT tx_hash) AS hashes, "
            "array_agg(id ORDER BY id) AS attempts FROM attempts WHERE org_id=:o AND status='CONFIRMED' "
            "GROUP BY payment_id HAVING count(*) > 1 OR count(DISTINCT tx_hash) > 1"
        ),
        {"o": org_id},
    ):
        out.append(
            Violation(
                org_id,
                "duplicate_payment",
                r.payment_id,
                {"payment_id": r.payment_id, "confirmed_attempts": list(r.attempts)},
            )
        )
    for r in conn.execute(
        text(
            "SELECT a.payment_id, min(a.id) AS attempt_id FROM attempts a WHERE a.org_id=:o "
            "AND a.status='CONFIRMED' AND NOT EXISTS (SELECT 1 FROM decisions d WHERE d.org_id=a.org_id "
            "AND d.payment_id=a.payment_id AND d.outcome='EXECUTE') GROUP BY a.payment_id"
        ),
        {"o": org_id},
    ):
        out.append(
            Violation(
                org_id,
                "unauthorised_execution",
                r.payment_id,
                {"payment_id": r.payment_id, "attempt_id": r.attempt_id},
            )
        )
    for r in conn.execute(
        text(
            "SELECT inbound_transfer_id, array_agg(id ORDER BY id) AS credits FROM credits WHERE org_id=:o "
            "GROUP BY inbound_transfer_id HAVING count(*) > 1"
        ),
        {"o": org_id},
    ):
        out.append(
            Violation(
                org_id,
                "double_credit",
                r.inbound_transfer_id,
                {"inbound_transfer_id": r.inbound_transfer_id, "credits": list(r.credits)},
            )
        )
    return out


def _engage(conn: Connection, clock: Clock, org_id: str) -> bool:
    from detent.execution.kill_switch import engage_in

    engaged = conn.execute(
        text("SELECT engaged FROM kill_switch WHERE org_id=:o FOR UPDATE"), {"o": org_id}
    ).scalar_one_or_none()
    if engaged:
        return False
    engage_in(conn, clock, org_id=org_id, actor=MONITOR)
    return True


def raise_alarm(conn: Connection, clock: Clock, v: Violation, *, kill_switch: bool) -> str | None:
    """Open the Sev 1 for one finding (once), engage the kill switch and post the notice. Returns a new ID."""
    inc, created = open_incident(
        conn,
        clock,
        org_id=v.org_id,
        severity=1,
        trigger=v.trigger,
        title=TITLES[v.trigger],
        actor=MONITOR,
        subject_id=v.subject_id,
        detail=v.detail,
    )
    if not created:
        return None
    if kill_switch and _engage(conn, clock, v.org_id):
        _event(conn, clock, v.org_id, inc, "kill_switch_engaged", MONITOR, {"by": "invariant monitor"})
    recipient = "on-call and the client's payments lead (mock)"
    conn.execute(
        text(
            "INSERT INTO outbox (id, org_id, channel, recipient, template, body, created_at) "
            "VALUES (:id, :o, 'email_mock', :r, 'incident_sev1', :b, :t)"
        ),
        {
            "id": new_id(Prefix.OBX, clock.now()),
            "o": v.org_id,
            "r": recipient,
            "b": f"Sev 1 incident {inc}: {TITLES[v.trigger]} ({v.subject_id}). "
            + ("The kill switch is engaged. " if kill_switch else "")
            + "Nothing more is sent until the payments lead releases it.",
            "t": clock.now(),
        },
    )
    record_notification(
        conn, clock, org_id=v.org_id, incident_id=inc, actor=MONITOR, channel="outbox", recipient=recipient
    )
    return inc


def check_org(conn: Connection, clock: Clock, org_id: str, *, kill_switch: bool = True) -> list[str]:
    opened: list[str] = []
    for v in find_violations(conn, org_id):
        inc = raise_alarm(conn, clock, v, kill_switch=kill_switch)
        if inc:
            opened.append(inc)
    return opened


def check_all(engine: Engine, clock: Clock, *, kill_switch: bool = True) -> dict[str, list[str]]:
    with engine.connect() as conn:
        orgs = (
            conn.execution_options(cross_org="invariant monitor: every organisation")
            .execute(text("SELECT id FROM organisations ORDER BY id"))
            .scalars()
            .all()
        )
    out: dict[str, list[str]] = {}
    for org in orgs:
        with transaction(engine) as conn:
            opened = check_org(conn, clock, str(org), kill_switch=kill_switch)
        if opened:
            out[str(org)] = opened
    return out
