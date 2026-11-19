"""``transition()``: the only way a payment's status changes (invariant 13).

It locks the payment row (``SELECT ... FOR UPDATE``), checks the move against
``detent.domain.states.ALLOWED``, updates the row and writes the audit event, all in the caller's
transaction. The database trigger independently refuses any change out of a terminal state.
EXE-01 (slice S2) builds attempts on top of this function. Since S7 it also writes the payout's
ledger entry (LED-02) in the same transaction.
"""

from __future__ import annotations

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.domain.states import InvalidTransition, Status, check_transition
from detent.ledger.payouts import on_status


class PaymentNotFound(LookupError):
    pass


def apply_transition(
    engine: Engine,
    clock: Clock,
    *,
    org_id: str,
    payment_id: str,
    to: Status,
    actor: Actor,
    reason: str | None = None,
) -> Status:
    """``transition()`` in its own transaction. A refused move changes nothing, is audited, and raises."""
    try:
        with engine.begin() as conn:
            return transition(
                conn, clock, org_id=org_id, payment_id=payment_id, to=to, actor=actor, reason=reason
            )
    except InvalidTransition as exc:
        record_refusal(
            engine, clock, org_id=org_id, payment_id=payment_id, exc=exc, actor=actor, reason=reason
        )
        raise


def record_refusal(
    engine: Engine,
    clock: Clock,
    *,
    org_id: str,
    payment_id: str,
    exc: InvalidTransition,
    actor: Actor,
    reason: str | None,
) -> None:
    """The refused change was rolled back; its record is written in a transaction of its own."""
    with engine.begin() as conn:
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="payment.transition_refused",
            subject_id=payment_id,
            payload={"from": exc.old.value, "to": exc.new.value, "reason": reason},
        )


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
    # LED-02: the ledger entry for this change is written in the same transaction.
    on_status(conn, clock, org_id=org_id, payment_id=payment_id, new_status=to.value)
    return old
