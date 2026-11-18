"""``transition()``: the only way a payment's status changes (invariant 13).

It locks the payment row (``SELECT ... FOR UPDATE``), checks the move against
``detent.domain.states.ALLOWED``, updates the row and writes the audit event, all in the caller's
transaction. The database trigger independently refuses any change out of a terminal state.
EXE-01 (slice S2) builds attempts on top of this function.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.domain.states import Status, check_transition


class PaymentNotFound(LookupError):
    pass


def transition(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    payment_id: str,
    to: Status,
    actor: Actor,
    reason: str | None = None,
    awaiting_send_click: bool | None = None,
) -> Status:
    row = conn.execute(
        text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p FOR UPDATE"),
        {"o": org_id, "p": payment_id},
    ).one_or_none()
    if row is None:
        raise PaymentNotFound(payment_id)
    old = Status(row.status)
    check_transition(old, to)
    conn.execute(
        text(
            "UPDATE payment_intents SET status=:s, updated_at=:t, "
            "awaiting_send_click=coalesce(:a, awaiting_send_click) WHERE org_id=:o AND id=:p"
        ),
        {"s": to.value, "t": clock.now(), "a": awaiting_send_click, "o": org_id, "p": payment_id},
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=actor,
        kind="payment.status_changed",
        subject_id=payment_id,
        payload={"from": old.value, "to": to.value, "reason": reason},
    )
    return old
