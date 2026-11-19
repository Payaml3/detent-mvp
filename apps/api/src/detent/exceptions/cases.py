"""Exception cases: owner, deadline, approve or reject with a policy re-run (EXC-01, EXC-04, EXC-05, EXC-07).

- A case opens in the same transaction as the escalation. Its tier is the rule set's deadline class
  (C-07): 1 for a payout above the auto limit, 2 for any other payout. The owner is the user in the
  rule set's owner role with the fewest open cases (G-24); an assignment notice goes to the outbox.
- Approve and reject lock the case row, so a second resolution gets ``AlreadyResolved`` (409).
- Approval needs a reason, a permitted role (G-06) and an approver who is not the initiator. It
  re-runs the policy with the active rule version and the reasons the approver saw (D-01): a BLOCK
  stays blocked, a new reason opens a new case, otherwise the payment proceeds per mode.
- A blocked payment is final: approving it raises ``PaymentBlocked`` (409 ``payment_blocked``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import SecretStr
from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.domain.money import Currency, Money
from detent.domain.roles import Role, allowed
from detent.domain.states import Status
from detent.intents.transition import transition
from detent.policy.schema import RuleSet
from detent.policy.screening import MockScreening, Screening
from detent.worker.queue import enqueue

OPEN_STATUSES = ("OPEN", "HELD_OVERDUE")


class CaseError(Exception):
    status = 409
    code = "conflict"


class CaseNotFound(CaseError):
    status, code = 404, "not_found"


class AlreadyResolved(CaseError):
    status, code = 409, "already_resolved"


class PaymentBlocked(CaseError):
    status, code = 409, "payment_blocked"


class NotPermitted(CaseError):
    status, code = 403, "insufficient_role"


class ResolveViaReconciliation(CaseError):
    """A deposit or reconciliation case is resolved by approving its proposed fix (LED-06)."""

    status, code = 409, "resolve_via_reconciliation"


class SelfApproval(CaseError):
    status, code = 403, "self_approval_forbidden"


@dataclass(frozen=True, slots=True)
class Resolution:
    case_id: str
    payment_id: str
    payment_status: str
    new_case_id: str | None = None


_DURATION = re.compile(r"^PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?$")


def parse_duration(value: str) -> timedelta:
    """ISO 8601 durations used by the rule set for payout deadlines (PT2H, PT4H, PT30M). Business-day
    deadlines (P1BD) belong to deposit exceptions and arrive with LED-05 (G-03 is still proposed)."""
    m = _DURATION.match(value)
    if not m or not (m.group("h") or m.group("m")):
        raise ValueError(f"unsupported deadline duration {value!r}")
    return timedelta(hours=int(m.group("h") or 0), minutes=int(m.group("m") or 0))


def add_business_days(start: datetime, days: int) -> datetime:
    """G-03: business days are Monday to Friday, UTC, with no public holidays in the MVP."""
    t = start
    left = days
    while left > 0:
        t += timedelta(days=1)
        if t.weekday() < 5:
            left -= 1
    return t


def deadline_after(start: datetime, value: str) -> datetime:
    """``PT2H`` style durations, or ``P{n}BD`` business days (G-03)."""
    m = re.match(r"^P(\d+)BD$", value)
    if m:
        return add_business_days(start, int(m.group(1)))
    return start + parse_duration(value)


def _pick_owner(conn: Connection, org_id: str, role: str) -> str | None:
    """G-24: the user in the role with the fewest open cases; ties go to the earliest-created user."""
    return conn.execute(
        text(
            "SELECT u.id FROM users u LEFT JOIN exception_cases c ON c.org_id = u.org_id AND c.owner_id = "
            "u.id "
            "AND c.status IN ('OPEN','HELD_OVERDUE') WHERE u.org_id=:o AND u.role=:r "
            "GROUP BY u.id, u.created_at ORDER BY count(c.id), u.created_at, u.id LIMIT 1"
        ),
        {"o": org_id, "r": role},
    ).scalar_one_or_none()


def _email(conn: Connection, org_id: str, user_id: str) -> str:
    return str(
        conn.execute(
            text("SELECT email FROM users WHERE org_id=:o AND id=:u"), {"o": org_id, "u": user_id}
        ).scalar_one()
    )


def open_case(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    payment_id: str,
    reasons: list[str],
    rules: RuleSet,
    case_type: str = "payout",
) -> str:
    now = clock.now()
    if case_type == "unknown_stuck":
        tier, deadline_key = 1, "unknown_stuck"  # C-07
    elif case_type == "payout" and "ABOVE_AUTO_LIMIT" in reasons:
        tier, deadline_key = 1, "payout_above_auto_limit"
    else:
        tier, deadline_key = 2, "payout_other"
    length = parse_duration(
        rules.deadlines.get(deadline_key, "PT30M" if case_type == "unknown_stuck" else "PT4H")
    )
    deadline = now + length
    rule = next((o for o in rules.owners if o.match.get("type") == case_type), None)
    owner = _pick_owner(conn, org_id, rule.owner_role) if rule else None
    backup = _pick_owner(conn, org_id, rule.backup_role) if rule else None
    if owner is None:  # nobody holds the role: the payments lead owns it rather than nobody
        owner = _pick_owner(conn, org_id, Role.PAYMENTS_LEAD.value)
    case_id = new_id(Prefix.EXC, now)
    conn.execute(
        text(
            "INSERT INTO exception_cases (id, org_id, payment_id, type, tier, reasons, owner_id, "
            "backup_owner_id, "
            "deadline_at, deadline_seconds, status, created_at) VALUES (:id, :o, :p, :t, :tier, :r, :own, "
            ":bk, :dl, :secs, 'OPEN', :now)"
        ),
        {
            "id": case_id,
            "o": org_id,
            "p": payment_id,
            "t": case_type,
            "tier": tier,
            "r": reasons,
            "own": owner,
            "bk": backup,
            "dl": deadline,
            "secs": int(length.total_seconds()),
            "now": now,
        },
    )
    _case_event(
        conn,
        clock,
        org_id,
        case_id,
        "opened",
        Actor.system("exceptions"),
        {"payment_id": payment_id, "reasons": reasons, "owner": owner, "tier": tier},
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=Actor.system("exceptions"),
        kind="case.opened",
        subject_id=case_id,
        payload={
            "payment_id": payment_id,
            "reasons": reasons,
            "tier": tier,
            "owner": owner,
            "backup_owner": backup,
            "deadline_at": deadline.isoformat(),
        },
    )
    if case_type == "payout":
        # EXC-03: the investigation agent runs in the worker; the case is usable before it finishes.
        enqueue(
            conn,
            clock,
            org_id=org_id,
            kind="case.investigate",
            dedupe_key=case_id,
            payload={"case_id": case_id},
        )
    if owner:
        _outbox(
            conn,
            clock,
            org_id,
            recipient=_email(conn, org_id, owner),
            template="case.assigned",
            body=(
                f"You own case {case_id} for payment {payment_id}. Reasons: {', '.join(reasons)}. "
                f"Deadline: {deadline.isoformat()}. Review it in the console; nothing is sent without a "
                "decision."
            ),
        )
    return case_id


def _outbox(conn: Connection, clock: Clock, org_id: str, *, recipient: str, template: str, body: str) -> None:
    """EXC-07: the prototype stores messages; nothing is ever emailed."""
    conn.execute(
        text(
            "INSERT INTO outbox (id, org_id, channel, recipient, template, body, created_at) "
            "VALUES (:id, :o, 'email_mock', :r, :t, :b, :now)"
        ),
        {
            "id": new_id(Prefix.OBX, clock.now()),
            "o": org_id,
            "r": recipient,
            "t": template,
            "b": body,
            "now": clock.now(),
        },
    )


def _case_event(
    conn: Connection,
    clock: Clock,
    org_id: str,
    case_id: str,
    kind: str,
    actor: Actor,
    payload: dict[str, Any],
) -> None:
    conn.execute(
        text(
            "INSERT INTO case_events (id, org_id, case_id, kind, actor, payload, at) "
            "VALUES (:id, :o, :c, :k, :a, CAST(:p AS jsonb), :t)"
        ),
        {
            "id": new_id(Prefix.CEV, clock.now()),
            "o": org_id,
            "c": case_id,
            "k": kind,
            "a": actor.id,
            "p": json.dumps(payload),
            "t": clock.now(),
        },
    )


def _lock(
    conn: Connection, org_id: str, case_id: str, actor: Actor, action: str, clock: Clock | None = None
) -> tuple[Any, Any]:
    case = conn.execute(
        text("SELECT * FROM exception_cases WHERE org_id=:o AND id=:c FOR UPDATE"),
        {"o": org_id, "c": case_id},
    ).one_or_none()
    if case is None:
        raise CaseNotFound(case_id)
    try:
        role = Role(actor.role or "")
    except ValueError:
        raise NotPermitted(f"{actor.id} has no console role") from None
    if not allowed(action, role):
        raise NotPermitted(f"{role.value} may not {action}")
    if case.status not in OPEN_STATUSES:
        raise AlreadyResolved(case_id)
    overdue = case.status == "HELD_OVERDUE" or (clock is not None and clock.now() >= case.deadline_at)
    # G-05: after the deadline only the case's current owner or the payments lead may approve.
    if (
        action == "exception.approve"
        and overdue
        and role is not Role.PAYMENTS_LEAD
        and actor.id != case.owner_id
    ):
        raise NotPermitted(
            "after the deadline only the case's current owner or the payments lead may approve"
        )
    if case.payment_id is None:
        raise ResolveViaReconciliation(case_id)
    pay = conn.execute(
        text("SELECT id, status, initiated_by FROM payment_intents WHERE org_id=:o AND id=:p FOR UPDATE"),
        {"o": org_id, "p": case.payment_id},
    ).one()
    if pay.status == Status.BLOCKED.value:
        raise PaymentBlocked(case.payment_id)
    if pay.status != Status.ESCALATED.value:
        raise AlreadyResolved(f"payment {case.payment_id} is {pay.status}")
    return case, pay


def _resolve(
    conn: Connection, clock: Clock, org_id: str, case: Any, resolution: str, reason: str, actor: Actor
) -> None:
    conn.execute(
        text(
            "UPDATE exception_cases SET status='RESOLVED', resolution=:r, resolution_reason=:why, "
            "resolved_by=:by, "
            "resolved_at=:t WHERE org_id=:o AND id=:c"
        ),
        {"r": resolution, "why": reason, "by": actor.id, "t": clock.now(), "o": org_id, "c": case.id},
    )
    _case_event(conn, clock, org_id, case.id, "resolved", actor, {"resolution": resolution, "reason": reason})
    append(
        conn,
        clock,
        org_id=org_id,
        actor=actor,
        kind="case.resolved",
        subject_id=case.id,
        payload={
            "payment_id": case.payment_id,
            "resolution": resolution,
            "reason": reason,
            "reasons_seen": list(case.reasons),
        },
    )


def _need_reason(reason: str) -> str:
    if not reason or not reason.strip():
        raise ValueError("a reason is required")
    return reason.strip()


def approve(
    engine: Engine,
    clock: Clock,
    *,
    case_id: str,
    org_id: str,
    actor: Actor,
    reason: str,
    screening: Screening | None = None,
    mandate_key: SecretStr | None = None,
) -> Resolution:
    from detent.intents.service import SEND_JOB, add_to_counters, load_org, reevaluate

    why = _need_reason(reason)
    with transaction(engine) as conn:
        case, pay = _lock(conn, org_id, case_id, actor, "exception.approve", clock)
        if pay.initiated_by == actor.id:
            raise SelfApproval("the approver cannot be the user who initiated the payment")
        result, policy = reevaluate(
            conn,
            clock,
            org_id=org_id,
            payment_id=case.payment_id,
            screening=screening or MockScreening.from_fixture(),
            reason=f"approval of {case.id}",
            approved_reasons=list(case.reasons),
            mandate_key=mandate_key,
        )
        pid = case.payment_id
        if result.outcome == "BLOCK":
            _resolve(conn, clock, org_id, case, "approved", why, actor)
            transition(
                conn,
                clock,
                org_id=org_id,
                payment_id=pid,
                to=Status.BLOCKED,
                actor=actor,
                reason="approval re-run BLOCK",
            )
            return Resolution(case.id, pid, Status.BLOCKED.value)
        if result.outcome == "ESCALATE":
            _resolve(conn, clock, org_id, case, "superseded", why, actor)
            transition(
                conn,
                clock,
                org_id=org_id,
                payment_id=pid,
                to=Status.ESCALATED,
                actor=actor,
                reason="approval re-run found a new reason",
            )
            new = open_case(
                conn, clock, org_id=org_id, payment_id=pid, reasons=result.reasons, rules=policy.rules
            )
            return Resolution(case.id, pid, Status.ESCALATED.value, new)
        _resolve(conn, clock, org_id, case, "approved", why, actor)
        org = load_org(conn, org_id)
        awaiting = org.mode == "assist"
        p = conn.execute(
            text(
                "SELECT counterparty_id, amount_minor, currency FROM payment_intents WHERE org_id=:o AND "
                "id=:p"
            ),
            {"o": org_id, "p": pid},
        ).one()
        add_to_counters(
            conn,
            org_id,
            p.counterparty_id,
            Money(int(p.amount_minor), Currency(p.currency)),
            clock.now().date().isoformat(),
            pid,
        )
        transition(
            conn,
            clock,
            org_id=org_id,
            payment_id=pid,
            to=Status.READY,
            actor=actor,
            reason="approved; policy re-run EXECUTE",
            awaiting_send_click=awaiting,
        )
        if not awaiting:
            enqueue(
                conn,
                clock,
                org_id=org_id,
                kind=SEND_JOB,
                payment_id=pid,
                dedupe_key=pid,
                payload={"payment_id": pid},
            )
        return Resolution(case.id, pid, Status.READY.value)


def reject(
    engine: Engine, clock: Clock, *, case_id: str, org_id: str, actor: Actor, reason: str
) -> Resolution:
    why = _need_reason(reason)
    with transaction(engine) as conn:
        case, _ = _lock(conn, org_id, case_id, actor, "exception.reject")
        _resolve(conn, clock, org_id, case, "rejected", why, actor)
        transition(
            conn,
            clock,
            org_id=org_id,
            payment_id=case.payment_id,
            to=Status.REJECTED,
            actor=actor,
            reason=f"rejected: {why}",
        )
        return Resolution(case.id, case.payment_id, Status.REJECTED.value)


def open_deposit_case(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    inbound_id: str,
    reasons: list[str],
    rules: RuleSet,
    case_type: str = "deposit",
) -> str:
    """LED-05: a deposit that can't be credited (or a reconciliation break, LED-06) opens a case.

    ``deposit_id`` holds the inbound transfer's ID. The deadline is ``deadlines.deposit_exception``
    (P1BD: one business day, G-03). Deposit cases are resolved by approving a reconciliation fix,
    never by a timeout: the sweeper treats them like payout cases.
    """
    existing = conn.execute(
        text(
            "SELECT id FROM exception_cases WHERE org_id=:o AND deposit_id=:d AND status IN "
            "('OPEN','HELD_OVERDUE')"
        ),
        {"o": org_id, "d": inbound_id},
    ).scalar_one_or_none()
    if existing:
        return str(existing)
    now = clock.now()
    deadline = deadline_after(now, rules.deadlines.get("deposit_exception", "P1BD"))
    rule = next((o for o in rules.owners if o.match.get("type") == case_type), None)
    owner = _pick_owner(conn, org_id, rule.owner_role) if rule else None
    backup = _pick_owner(conn, org_id, rule.backup_role) if rule else None
    if owner is None:
        owner = _pick_owner(conn, org_id, Role.PAYMENTS_LEAD.value)
    case_id = new_id(Prefix.EXC, now)
    conn.execute(
        text(
            "INSERT INTO exception_cases (id, org_id, deposit_id, type, tier, reasons, owner_id, "
            "backup_owner_id, "
            "deadline_at, deadline_seconds, status, created_at) VALUES (:id, :o, :d, :t, 2, :r, "
            ":own, :bk, :dl, "
            ":secs, 'OPEN', :now)"
        ),
        {
            "id": case_id,
            "o": org_id,
            "d": inbound_id,
            "t": case_type,
            "r": reasons,
            "own": owner,
            "bk": backup,
            "dl": deadline,
            "secs": int((deadline - now).total_seconds()),
            "now": now,
        },
    )
    _case_event(
        conn,
        clock,
        org_id,
        case_id,
        "opened",
        Actor.system("exceptions"),
        {"deposit_id": inbound_id, "reasons": reasons},
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=Actor.system("exceptions"),
        kind="case.opened",
        subject_id=case_id,
        payload={
            "deposit_id": inbound_id,
            "reasons": reasons,
            "type": case_type,
            "owner": owner,
            "deadline_at": deadline.isoformat(),
        },
    )
    if owner:
        _outbox(
            conn,
            clock,
            org_id,
            recipient=_email(conn, org_id, owner),
            template="case.assigned",
            body=(
                f"You own {case_type} case {case_id} for inbound transfer {inbound_id}. "
                f"Reasons: {', '.join(reasons)}. "
                f"Deadline: {deadline.isoformat()}. The money is held in suspense; nothing is "
                "credited without a decision."
            ),
        )
    return case_id
