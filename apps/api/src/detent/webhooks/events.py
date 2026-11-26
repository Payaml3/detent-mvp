"""WHK-01 and API-07: webhook events.

Events come from the audit log. `detent.audit.log.append` calls `from_audit` in the same transaction as
the change it records (invariant 12), so an event exists exactly when its change committed, and a
rolled-back change leaves no event. `append` holds the organisation's audit-head lock, so events are
numbered without gaps or races: `sequence` increases per payment (or per subject for events with no
payment), as spec/03 promises.

For every enabled endpoint of the organisation that subscribes to the type, the same transaction
enqueues one `webhook.deliver` job (WHK-03). Webhook events and `GET /v1/events` use one object shape.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from detent.clock import Clock
from detent.domain.ids import Prefix, new_id
from detent.domain.money import Currency, Money

PAYMENT_EVENT_TYPES: tuple[str, ...] = (
    "payment_intent.decided",
    "payment_intent.escalated",
    "payment_intent.ready",
    "payment_intent.submitted",
    "payment_intent.unknown",
    "payment_intent.confirmed",
    "payment_intent.failed",
    "payment_intent.blocked",
    "payment_intent.rejected",
    "payment_intent.cancelled",
)
EVENT_TYPES: tuple[str, ...] = (
    *PAYMENT_EVENT_TYPES,
    "exception.created",
    "exception.overdue",
    "exception.resolved",
    "deposit.credited",
    "deposit.exception",
    "reconciliation.break",
    "kill_switch.engaged",
    "kill_switch.released",
)
TEST_EVENT_TYPE = "webhook.test"
ALL_TYPES = "*"

# Payment status -> event type. HELD and SHADOWED have no event of their own: the first decision is
# always announced as payment_intent.decided, and HELD is internal (a hold before sending).
_STATUS_EVENTS: dict[str, str] = {
    "ESCALATED": "payment_intent.escalated",
    "READY": "payment_intent.ready",
    "SUBMITTED": "payment_intent.submitted",
    "UNKNOWN": "payment_intent.unknown",
    "CONFIRMED": "payment_intent.confirmed",
    "FAILED": "payment_intent.failed",
    "FAILED_FINAL": "payment_intent.failed",
    "BLOCKED": "payment_intent.blocked",
    "REJECTED": "payment_intent.rejected",
    "CANCELLED": "payment_intent.cancelled",
}
_SIMPLE: dict[str, str] = {
    "case.opened": "exception.created",
    "case.overdue": "exception.overdue",
    "case.resolved": "exception.resolved",
    "deposit.credited": "deposit.credited",
    "deposit.exception": "deposit.exception",
    "reconciliation.break": "reconciliation.break",
    "kill_switch.engaged": "kill_switch.engaged",
    "kill_switch.released": "kill_switch.released",
}


def types_for(kind: str, payload: dict[str, Any]) -> list[str]:
    """The event types an audit event produces (most produce none)."""
    if kind == "payment.status_changed":
        out = []
        if payload.get("from") == "RECEIVED":
            out.append("payment_intent.decided")
        t = _STATUS_EVENTS.get(str(payload.get("to")))
        if t:
            out.append(t)
        return out
    t = _SIMPLE.get(kind)
    return [t] if t else []


def from_audit(
    conn: Connection, clock: Clock, *, org_id: str, kind: str, subject_id: str | None, payload: dict[str, Any]
) -> list[str]:
    """Called by `audit.log.append`. Writes the events (if any) and enqueues their deliveries."""
    types = types_for(kind, payload)
    if not types:
        return []
    obj, payment_id = _object(conn, org_id, kind, subject_id, payload)
    return [
        emit(conn, clock, org_id=org_id, type_=t, subject_id=subject_id, payment_id=payment_id, obj=obj)
        for t in types
    ]


def emit(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    type_: str,
    subject_id: str | None,
    payment_id: str | None,
    obj: dict[str, Any],
    test: bool = False,
    only_endpoint: str | None = None,
) -> str:
    """Store one event and enqueue a delivery for each subscribed endpoint. Returns the event ID."""
    now = clock.now()
    event_id = new_id(Prefix.EVT, now)
    if payment_id is not None:
        seq_sql = (
            "SELECT coalesce(max(sequence), 0) + 1 FROM webhook_events WHERE org_id=:o AND payment_id=:k"
        )
        key: str | None = payment_id
    else:
        seq_sql = (
            "SELECT coalesce(max(sequence), 0) + 1 FROM webhook_events "
            "WHERE org_id=:o AND payment_id IS NULL AND subject_id IS NOT DISTINCT FROM :k"
        )
        key = subject_id
    sequence = int(conn.execute(text(seq_sql), {"o": org_id, "k": key}).scalar_one())
    envelope = {
        "id": event_id,
        "type": type_,
        "created": int(now.timestamp()),
        "sequence": sequence,
        "test": test,
        "data": {"object": obj},
    }
    conn.execute(
        text(
            "INSERT INTO webhook_events (id, org_id, type, subject_id, payment_id, sequence, payload, test, "
            "created_at) VALUES (:id, :o, :t, :s, :p, :seq, CAST(:body AS jsonb), :test, :now)"
        ),
        {
            "id": event_id,
            "o": org_id,
            "t": type_,
            "s": subject_id,
            "p": payment_id,
            "seq": sequence,
            "body": json.dumps(envelope),
            "test": test,
            "now": now,
        },
    )
    from detent.webhooks.delivery import enqueue_deliveries

    enqueue_deliveries(
        conn, clock, org_id=org_id, event_id=event_id, type_=type_, only_endpoint=only_endpoint
    )
    return event_id


def event_json(row: Any) -> dict[str, Any]:
    """The stored envelope, exactly as it is delivered."""
    return dict(row.payload)


# ------------------------------------------------------------------------------------------ objects
def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v is not None else None


def _object(
    conn: Connection, org_id: str, kind: str, subject_id: str | None, payload: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    if kind == "payment.status_changed" and subject_id:
        from detent.views.payments import payment_view

        view = payment_view(conn, org_id, subject_id, any_generation=True) or {"id": subject_id}
        return {"object": "payment_intent", **view}, subject_id
    if kind.startswith("case.") and subject_id:
        from detent.views.cases import case_summary

        case = case_summary(conn, org_id, subject_id)
        return case, case.get("payment_id")
    if kind.startswith("deposit."):
        cur = payload.get("currency")
        amount = (
            Money(int(payload["amount_minor"]), Currency(str(cur))).to_api()
            if cur and payload.get("amount_minor") is not None
            else None
        )
        return {
            "object": "deposit",
            "id": subject_id,
            "deposit_intent_id": payload.get("intent"),
            "status": "CREDITED" if kind == "deposit.credited" else "EXCEPTION",
            "amount": amount,
            "checks": list(payload.get("checks") or []),
            "exception_id": payload.get("case_id"),
        }, None
    if kind == "reconciliation.break":
        return {
            "object": "reconciliation_break",
            "id": subject_id,
            "kind": payload.get("kind"),
            "subject_key": payload.get("subject_key"),
            "exception_id": payload.get("case_id"),
        }, None
    if kind.startswith("kill_switch."):
        held = payload.get("held") if kind == "kill_switch.engaged" else payload.get("held_payments")
        return {
            "object": "kill_switch",
            "engaged": kind == "kill_switch.engaged",
            "held_payments": list(held or []) if isinstance(held, list) else held,
        }, None
    return {"object": "unknown", "id": subject_id}, None
