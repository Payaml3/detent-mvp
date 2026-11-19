"""Attempts: one payment, many tries, one outcome (EXE-02, invariants 1 to 3).

- A new attempt is created only when every earlier attempt is definitively FAILED.
- At most one attempt is in flight and at most one is CONFIRMED; partial unique indexes enforce both
  even if this code had a bug.
- A timeout is UNKNOWN, never FAILED.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.domain.ids import Prefix, new_id
from detent.domain.states import AttemptStatus, FailureClass, check_attempt_transition


class AttemptNotAllowed(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Attempt:
    id: str
    payment_id: str
    attempt_no: int
    rail_id: str
    status: AttemptStatus
    idempotency_key: str
    created_at: datetime


def rail_idempotency_key(payment_id: str, rail_id: str, *, first_rail_id: str) -> str:
    """spec/06: the payment ID on its first rail, so the rail deduplicates retries; ``{payment_id}:{rail_id}``
    after a failover to a different rail. EVM rails deduplicate by nonce as well."""
    return payment_id if rail_id == first_rail_id else f"{payment_id}:{rail_id}"


def create_attempt(conn: Connection, clock: Clock, *, org_id: str, payment_id: str, rail_id: str) -> Attempt:
    status = conn.execute(
        text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p FOR UPDATE"),
        {"o": org_id, "p": payment_id},
    ).scalar_one_or_none()
    if status != "READY":
        # S8 (atk-bb-03): only a payment authorised to send gets an attempt; migration 0008 backs this up.
        raise AttemptNotAllowed(f"payment {payment_id} is {status}; an attempt needs a READY payment")
    rows = conn.execute(
        text(
            "SELECT attempt_no, rail_id, status FROM attempts WHERE org_id=:o AND payment_id=:p "
            "ORDER BY attempt_no FOR UPDATE"
        ),
        {"o": org_id, "p": payment_id},
    ).all()
    for r in rows:
        if r.status != AttemptStatus.FAILED.value:
            raise AttemptNotAllowed(
                f"attempt {r.attempt_no} of {payment_id} is {r.status}; a new attempt needs every earlier "
                "one FAILED"
            )
    now = clock.now()
    no = (rows[-1].attempt_no + 1) if rows else 1
    first_rail = rows[0].rail_id if rows else rail_id
    att = Attempt(
        new_id(Prefix.ATT, now),
        payment_id,
        no,
        rail_id,
        AttemptStatus.CREATED,
        rail_idempotency_key(payment_id, rail_id, first_rail_id=first_rail),
        now,
    )
    conn.execute(
        text(
            "INSERT INTO attempts (id, org_id, payment_id, attempt_no, rail_id, status, idempotency_key, "
            "created_at) "
            "VALUES (:id, :o, :p, :n, :r, 'CREATED', :k, :t)"
        ),
        {
            "id": att.id,
            "o": org_id,
            "p": payment_id,
            "n": no,
            "r": rail_id,
            "k": att.idempotency_key,
            "t": now,
        },
    )
    return att


def mark_attempt(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    attempt_id: str,
    to: AttemptStatus,
    failure_class: FailureClass | None = None,
    evidence: dict[str, Any] | None = None,
    actor: Actor | None = None,
) -> None:
    if to is AttemptStatus.FAILED and failure_class in (None, FailureClass.TIMEOUT):
        raise ValueError(
            "a FAILED attempt needs a definitive failure class; a TIMEOUT is UNKNOWN (invariant 3)"
        )
    row = conn.execute(
        text("SELECT status, payment_id FROM attempts WHERE org_id=:o AND id=:a FOR UPDATE"),
        {"o": org_id, "a": attempt_id},
    ).one()
    check_attempt_transition(AttemptStatus(row.status), to)
    now = clock.now()
    import json

    conn.execute(
        text(
            "UPDATE attempts SET status=:s, failure_class=coalesce(:fc, failure_class), "
            "evidence=coalesce(CAST(:ev AS jsonb), evidence), "
            "submitted_at=CASE WHEN :s='SUBMITTED' THEN :t ELSE submitted_at END, "
            "resolved_at=CASE WHEN :s IN ('CONFIRMED','FAILED') THEN :t ELSE resolved_at END "
            "WHERE org_id=:o AND id=:a"
        ),
        {
            "s": to.value,
            "fc": failure_class.value if failure_class else None,
            "ev": json.dumps(evidence) if evidence is not None else None,
            "t": now,
            "o": org_id,
            "a": attempt_id,
        },
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=actor or Actor.system("execution"),
        kind=f"attempt.{to.value.lower()}",
        subject_id=row.payment_id,
        payload={
            "attempt_id": attempt_id,
            "from": row.status,
            "to": to.value,
            "failure_class": failure_class.value if failure_class else None,
            "evidence": evidence,
        },
    )
