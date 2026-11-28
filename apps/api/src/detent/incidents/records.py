"""Incident records (OPS-01, spec/10 "Incidents").

- Severity 1 to 4 (``SEVERITIES``), each with a notification window. A Sev 1 is opened by the invariant
  monitor (EXE-10) or by a person; it must be notified within 1 hour, and an incident is overdue on the
  console when that window passes without a logged notification.
- The timeline is ``incident_events`` (append-only). Every change also writes an audit event in the same
  transaction (invariant 12).
- A root cause is required before a Sev 1 or Sev 2 can be resolved. Replays of affected payments are
  linked to the incident with their result (AUD-02); replay never calls a model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id


@dataclass(frozen=True, slots=True)
class Severity:
    level: int
    name: str
    meaning: str
    notify_within: timedelta


SEVERITIES: dict[int, Severity] = {
    1: Severity(
        1,
        "Sev 1",
        "An invariant broke or money may be at risk: a duplicate payment, an unauthorised execution or a "
        "double credit. The kill switch is engaged; root cause within 5 days.",
        timedelta(hours=1),
    ),
    2: Severity(
        2,
        "Sev 2",
        "A control misbehaved without loss, for example a replay that does not match its decision.",
        timedelta(hours=4),
    ),
    3: Severity(
        3, "Sev 3", "Degraded service, for example a rail that is down or slow.", timedelta(hours=24)
    ),
    4: Severity(4, "Sev 4", "A near miss or a cosmetic fault.", timedelta(days=5)),
}
NEEDS_ROOT_CAUSE = frozenset({1, 2})


class IncidentError(Exception):
    status = 409
    code = "conflict"

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        if status is not None:
            self.status = status


def _event(
    conn: Connection,
    clock: Clock,
    org_id: str,
    incident_id: str,
    kind: str,
    actor: Actor,
    payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO incident_events (id, org_id, incident_id, kind, actor, payload, at) "
            "VALUES (:id, :o, :i, :k, :a, CAST(:p AS jsonb), :t)"
        ),
        {
            "id": new_id(Prefix.INE, clock.now()),
            "o": org_id,
            "i": incident_id,
            "k": kind,
            "a": actor.id,
            "p": json.dumps(payload or {}),
            "t": clock.now(),
        },
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=actor,
        kind=f"incident.{kind}",
        subject_id=incident_id,
        payload=payload or {},
    )


def open_incident(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    severity: int,
    trigger: str,
    title: str,
    actor: Actor,
    subject_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> tuple[str, bool]:
    """Open an incident and return (id, created). An open one for the same trigger and subject is reused."""
    if severity not in SEVERITIES:
        raise IncidentError(f"severity must be 1 to 4, not {severity}", status=422)
    if not title.strip():
        raise IncidentError("a title is required", status=422)
    if subject_id is not None:
        existing = conn.execute(
            text(
                "SELECT id FROM incidents WHERE org_id=:o AND trigger=:t AND subject_id=:s AND status='open'"
            ),
            {"o": org_id, "t": trigger, "s": subject_id},
        ).scalar_one_or_none()
        if existing:
            return str(existing), False
    now = clock.now()
    inc = new_id(Prefix.INC, now)
    conn.execute(
        text(
            "INSERT INTO incidents (id, org_id, severity, trigger, title, opened_at, opened_by, subject_id, "
            "detail, status) VALUES (:id, :o, :sev, :trg, :title, :t, :by, :s, CAST(:d AS jsonb), 'open')"
        ),
        {
            "id": inc,
            "o": org_id,
            "sev": severity,
            "trg": trigger,
            "title": title.strip(),
            "t": now,
            "by": actor.id,
            "s": subject_id,
            "d": json.dumps(detail or {}),
        },
    )
    _event(
        conn,
        clock,
        org_id,
        inc,
        "opened",
        actor,
        {"severity": severity, "trigger": trigger, "title": title.strip(), "subject_id": subject_id},
    )
    return inc, True


def _lock(conn: Connection, org_id: str, incident_id: str) -> Any:
    row = conn.execute(
        text("SELECT * FROM incidents WHERE org_id=:o AND id=:i FOR UPDATE"), {"o": org_id, "i": incident_id}
    ).one_or_none()
    if row is None:
        raise IncidentError(f"no incident {incident_id}", status=404)
    return row


def record_notification(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    incident_id: str,
    actor: Actor,
    channel: str,
    recipient: str,
) -> None:
    """Log that the client (or on-call) was told. The first notification sets ``notified_at``."""
    inc = _lock(conn, org_id, incident_id)
    if inc.notified_at is None:
        conn.execute(
            text("UPDATE incidents SET notified_at=:t WHERE org_id=:o AND id=:i"),
            {"t": clock.now(), "o": org_id, "i": incident_id},
        )
    _event(conn, clock, org_id, incident_id, "notified", actor, {"channel": channel, "recipient": recipient})


def notify(
    engine: Engine, clock: Clock, *, org_id: str, incident_id: str, actor: Actor, channel: str, recipient: str
) -> None:
    if not channel.strip() or not recipient.strip():
        raise IncidentError("say how and whom you notified", status=422)
    with transaction(engine) as conn:
        record_notification(
            conn,
            clock,
            org_id=org_id,
            incident_id=incident_id,
            actor=actor,
            channel=channel.strip(),
            recipient=recipient.strip(),
        )


def add_note(engine: Engine, clock: Clock, *, org_id: str, incident_id: str, actor: Actor, note: str) -> None:
    if not note.strip():
        raise IncidentError("a note cannot be empty", status=422)
    with transaction(engine) as conn:
        _lock(conn, org_id, incident_id)
        _event(conn, clock, org_id, incident_id, "note", actor, {"note": note.strip()})


def set_root_cause(
    engine: Engine, clock: Clock, *, org_id: str, incident_id: str, actor: Actor, root_cause: str
) -> None:
    if not root_cause.strip():
        raise IncidentError("a root cause cannot be empty", status=422)
    with transaction(engine) as conn:
        _lock(conn, org_id, incident_id)
        conn.execute(
            text("UPDATE incidents SET root_cause=:r WHERE org_id=:o AND id=:i"),
            {"r": root_cause.strip(), "o": org_id, "i": incident_id},
        )
        _event(conn, clock, org_id, incident_id, "root_cause", actor, {"root_cause": root_cause.strip()})


def link_replay(
    engine: Engine, clock: Clock, *, org_id: str, incident_id: str, actor: Actor, payment_id: str
) -> dict[str, Any]:
    """Replay a payment (AUD-02, stored outputs only) and link the result to the incident."""
    from detent.audit.replay import replay_payment

    with engine.connect() as conn:
        _lock(conn, org_id, incident_id)
        exists = conn.execute(
            text("SELECT 1 FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org_id, "p": payment_id}
        ).scalar_one_or_none()
    if not exists:
        raise IncidentError(f"no payment {payment_id}", status=404)
    result = replay_payment(engine, clock, org_id=org_id, payment_id=payment_id)
    with transaction(engine) as conn:
        _lock(conn, org_id, incident_id)
        _event(
            conn,
            clock,
            org_id,
            incident_id,
            "replay_linked",
            actor,
            {"payment_id": payment_id, "match": bool(result["match"]), "status": result["status"]},
        )
    return result


def resolve(engine: Engine, clock: Clock, *, org_id: str, incident_id: str, actor: Actor) -> None:
    with transaction(engine) as conn:
        inc = _lock(conn, org_id, incident_id)
        if inc.status != "open":
            raise IncidentError(f"incident {incident_id} is already {inc.status}")
        if inc.severity in NEEDS_ROOT_CAUSE and not (inc.root_cause or "").strip():
            raise IncidentError(f"a Sev {inc.severity} needs a root cause before it is resolved", status=422)
        conn.execute(
            text(
                "UPDATE incidents SET status='resolved', resolved_at=:t, resolved_by=:a "
                "WHERE org_id=:o AND id=:i"
            ),
            {"t": clock.now(), "a": actor.id, "o": org_id, "i": incident_id},
        )
        _event(conn, clock, org_id, incident_id, "resolved", actor, {})


def open_manually(
    engine: Engine, clock: Clock, *, org_id: str, actor: Actor, severity: int, title: str
) -> str:
    with transaction(engine) as conn:
        inc, _ = open_incident(
            conn, clock, org_id=org_id, severity=severity, trigger="manual", title=title, actor=actor
        )
    return inc


def notification_overdue(inc: Any, now: datetime) -> bool:
    if inc.notified_at is not None or inc.status != "open":
        return False
    return bool(now - inc.opened_at > SEVERITIES[int(inc.severity)].notify_within)


def list_incidents(conn: Connection, org_id: str, *, limit: int = 100) -> list[Any]:
    return list(
        conn.execute(
            text("SELECT * FROM incidents WHERE org_id=:o ORDER BY opened_at DESC, id DESC LIMIT :n"),
            {"o": org_id, "n": limit},
        ).all()
    )


def open_sev1(conn: Connection, org_id: str) -> list[Any]:
    return list(
        conn.execute(
            text(
                "SELECT id, title, opened_at FROM incidents WHERE org_id=:o AND severity=1 AND status='open' "
                "ORDER BY opened_at"
            ),
            {"o": org_id},
        ).all()
    )


def timeline(conn: Connection, org_id: str, incident_id: str) -> list[Any]:
    return list(
        conn.execute(
            text("SELECT * FROM incident_events WHERE org_id=:o AND incident_id=:i ORDER BY at, id"),
            {"o": org_id, "i": incident_id},
        ).all()
    )
