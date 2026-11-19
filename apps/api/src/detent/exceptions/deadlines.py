"""The deadline sweeper (EXC-06). A timeout never becomes an approval (invariant 7).

When a case passes its deadline:
- the case becomes HELD_OVERDUE and the payment stays where it is (held: nothing is queued to send);
- the counterparty gets a status update through the outbox (G-02; the prototype never emails);
- ownership moves on (G-04): the first miss goes to the backup owner, any later miss to the payments
  lead; each new owner gets a deadline of the same length as the original, from takeover.

The sweeper never resolves a case and never changes a payment. ``approved_by_timeout`` counts
approvals made by anything other than a person; it is reported on the overview and is always 0.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.money import Currency, Money
from detent.domain.roles import Role
from detent.exceptions.cases import OPEN_STATUSES, _case_event, _email, _outbox, _pick_owner

ACTOR = Actor.system("deadline_sweeper")


def _counterparty_notice(conn: Connection, org_id: str, case: Any) -> tuple[str, str] | None:
    p = conn.execute(
        text(
            "SELECT p.id, p.reference, p.amount_minor, p.currency, c.contact_email FROM payment_intents p "
            "LEFT JOIN counterparties c ON c.org_id = p.org_id AND c.id = p.counterparty_id "
            "WHERE p.org_id=:o AND p.id=:p"
        ),
        {"o": org_id, "p": case.payment_id},
    ).one_or_none()
    if p is None or not p.contact_email:
        return None
    amount = Money(int(p.amount_minor), Currency(p.currency)).to_api()
    ref = f" (reference {p.reference})" if p.reference else ""
    body = (
        f"Your payment of {amount['amount']} {amount['currency']}{ref} is still being reviewed. It has "
        "not been sent and will not be sent until a person approves it. We will update you when it is "
        f"decided. Payment {p.id}."
    )
    return str(p.contact_email), body


def _overdue(conn: Connection, clock: Clock, org_id: str, case: Any) -> None:
    now = clock.now()
    n = int(case.overdue_count) + 1
    if n == 1 and case.backup_owner_id:
        owner = case.backup_owner_id
    else:
        owner = _pick_owner(conn, org_id, Role.PAYMENTS_LEAD.value) or case.owner_id
    seconds = case.deadline_seconds or int((case.deadline_at - case.created_at).total_seconds())
    deadline = now + timedelta(seconds=max(int(seconds), 60))
    conn.execute(
        text(
            "UPDATE exception_cases SET status='HELD_OVERDUE', owner_id=:own, deadline_at=:dl, "
            "overdue_count=:n WHERE org_id=:o AND id=:c"
        ),
        {"own": owner, "dl": deadline, "n": n, "o": org_id, "c": case.id},
    )
    detail = {
        "payment_id": case.payment_id,
        "missed_deadline": case.deadline_at.isoformat(),
        "from_owner": case.owner_id,
        "to_owner": owner,
        "overdue_count": n,
        "new_deadline": deadline.isoformat(),
        "payment_held": True,
    }
    _case_event(conn, clock, org_id, case.id, "overdue", ACTOR, detail)
    append(conn, clock, org_id=org_id, actor=ACTOR, kind="case.overdue", subject_id=case.id, payload=detail)
    if owner:
        _outbox(
            conn,
            clock,
            org_id,
            recipient=_email(conn, org_id, owner),
            template="case.overdue_assigned",
            body=(
                f"Case {case.id} for payment {case.payment_id} passed its deadline and is now yours. "
                f"New deadline: {deadline.isoformat()}. The payment is held: it will not be sent or "
                "approved until a person decides."
            ),
        )
    notice = _counterparty_notice(conn, org_id, case)
    if notice:
        _outbox(conn, clock, org_id, recipient=notice[0], template="case.counterparty_update", body=notice[1])


def sweep(engine: Engine, clock: Clock, org_id: str) -> list[str]:
    """Handle every case in the organisation whose deadline has passed. Returns their IDs."""
    with transaction(engine) as conn:
        due = conn.execute(
            text(
                "SELECT * FROM exception_cases WHERE org_id=:o AND status = ANY(:st) AND deadline_at <= :now "
                "ORDER BY deadline_at, id FOR UPDATE SKIP LOCKED"
            ),
            {"o": org_id, "st": list(OPEN_STATUSES), "now": clock.now()},
        ).all()
        for case in due:
            _overdue(conn, clock, org_id, case)
        return [c.id for c in due]


def sweep_all(engine: Engine, clock: Clock) -> dict[str, list[str]]:
    with engine.connect() as conn:
        orgs = (
            conn.execute(
                text(
                    "SELECT DISTINCT org_id FROM exception_cases WHERE status IN ('OPEN','HELD_OVERDUE') "
                    "AND deadline_at <= :now"
                ).execution_options(cross_org="deadline sweeper: finds organisations with overdue cases"),
                {"now": clock.now()},
            )
            .scalars()
            .all()
        )
    out: dict[str, list[str]] = {}
    for org in orgs:
        ids = sweep(engine, clock, org)
        if ids:
            out[org] = ids
    return out


def approved_by_timeout(engine: Engine | Connection, org_id: str) -> int:
    """Approvals not made by a person: resolved 'approved' by a system actor, or with no approver."""
    sql = text(
        "SELECT count(*) FROM exception_cases WHERE org_id=:o AND resolution='approved' AND "
        "(resolved_by IS NULL OR resolved_by LIKE 'system:%')"
    )
    if isinstance(engine, Connection):
        return int(engine.execute(sql, {"o": org_id}).scalar_one())
    with engine.connect() as conn:
        return int(conn.execute(sql, {"o": org_id}).scalar_one())
