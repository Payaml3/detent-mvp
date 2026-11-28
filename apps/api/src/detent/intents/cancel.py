"""Cancel an intent before it is sent (INT-05).

- Allowed from ESCALATED, HELD or READY only. SUBMITTED, UNKNOWN or any terminal state answers
  ``NotCancellable`` (409 ``not_cancellable``): once a payment may be on a rail, only rail evidence
  settles it (invariant 3).
- CANCELLED is terminal (the allowed-transitions table). The change goes through ``transition()``
  under the payment's row lock, so a send job that runs afterwards sees CANCELLED and stops, and a
  send that won the lock first leaves the payment SUBMITTED, which cannot be cancelled.
- An open exception case for the payment is resolved as ``cancelled`` in the same transaction.
- The actor and the reason are audited (``payment.cancelled``), in the same transaction (invariant 12).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.states import Status
from detent.exceptions.cases import _resolve as resolve_case
from detent.intents.transition import transition

CANCELLABLE = frozenset({Status.ESCALATED, Status.HELD, Status.READY})


class CancelError(Exception):
    status = 409
    code = "not_cancellable"


class NotCancellable(CancelError):
    pass


class PaymentMissing(CancelError):
    status = 404
    code = "not_found"


class ReasonRequired(CancelError):
    status = 422
    code = "validation_error"


@dataclass(frozen=True, slots=True)
class Cancelled:
    payment_id: str
    from_status: str
    case_id: str | None


def cancel_intent(
    engine: Engine, clock: Clock, *, org_id: str, payment_id: str, actor: Actor, reason: str
) -> Cancelled:
    why = (reason or "").strip()
    if not why:
        raise ReasonRequired("a reason is required")
    with transaction(engine) as conn:
        row = conn.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p FOR UPDATE"),
            {"o": org_id, "p": payment_id},
        ).one_or_none()
        if row is None:
            raise PaymentMissing(f"no payment {payment_id}")
        status = Status(row.status)
        if status not in CANCELLABLE:
            raise NotCancellable(
                f"payment {payment_id} is {status.value}; only ESCALATED, HELD or READY can be cancelled"
            )
        case = conn.execute(
            text(
                "SELECT id, payment_id, reasons FROM exception_cases WHERE org_id=:o AND payment_id=:p "
                "AND status IN ('OPEN','HELD_OVERDUE') FOR UPDATE"
            ),
            {"o": org_id, "p": payment_id},
        ).one_or_none()
        case_id = case.id if case is not None else None
        if case is not None:
            resolve_case(conn, clock, org_id, case, "cancelled", why, actor)
        transition(
            conn,
            clock,
            org_id=org_id,
            payment_id=payment_id,
            to=Status.CANCELLED,
            actor=actor,
            reason=f"cancelled: {why}",
            awaiting_send_click=False,
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="payment.cancelled",
            subject_id=payment_id,
            payload={"from": status.value, "reason": why, "case_id": case_id},
        )
    return Cancelled(payment_id, status.value, case_id)
