"""Applying a proposed fix (LED-06): only after a person approves it, and only as a new entry.

Only the payments lead approves (``recon.approve_fix``). Approval re-checks the fix against the current
state, then writes an adjustment entry whose ``adjustment_of`` is the break:

- ``match_to(dep_...)``: suspense -> the intent's user balance; the inbound transfer is credited once
  (the ``credits`` row is unique per inbound transfer) and the intent becomes CREDITED;
- ``credit_account(ref)``: suspense (or, for an unbooked bank line, inbound clearing) -> that balance;
- ``return_to_sender``: suspense -> rail_clearing:{rail}:refund_due, and the payments lead is told
  in the outbox to send the refund. The refund payout itself is not automated in the prototype;
- ``write_off_to_suspense``: no entry; the money stays in suspense, recorded as a decision;
- ``needs_investigation`` can't be applied: it is a question, not a fix.

The break's case is resolved by the same transaction. Rejecting a fix leaves the case open.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.domain.money import Currency
from detent.domain.roles import Role, allowed
from detent.ledger.journal import Line, account, post


class FixError(Exception):
    def __init__(self, message: str, *, status: int = 409, code: str = "fix_refused") -> None:
        super().__init__(message)
        self.status, self.code = status, code


def _lock(conn: Connection, org_id: str, break_id: str, actor: Actor) -> Any:
    try:
        role = Role(actor.role or "")
    except ValueError:
        raise FixError(f"{actor.id} has no console role", status=403, code="insufficient_role") from None
    if not allowed("recon.approve_fix", role):
        raise FixError(
            f"{role.value} may not approve a reconciliation fix", status=403, code="insufficient_role"
        )
    b = conn.execute(
        text("SELECT * FROM recon_breaks WHERE org_id=:o AND id=:i FOR UPDATE"), {"o": org_id, "i": break_id}
    ).one_or_none()
    if b is None:
        raise FixError(f"no break {break_id}", status=404, code="not_found")
    if b.status != "OPEN":
        raise FixError(f"break {break_id} is {b.status}", code="already_decided")
    return b


def _credit(
    conn: Connection,
    clock: Clock,
    org_id: str,
    b: Any,
    inb: Any,
    account_ref: str,
    intent_id: str | None,
    from_suspense: bool,
) -> str:
    cur = Currency(inb.currency)
    amount = int(inb.amount_minor)
    src = (
        account(conn, clock, org_id, "suspense", "suspense", cur)
        if from_suspense
        else account(conn, clock, org_id, "rail_clearing", f"{inb.rail_id}:inbound", cur)
    )
    jid = post(
        conn,
        clock,
        org_id=org_id,
        kind="adjustment.credit",
        currency=cur,
        deposit_id=inb.id,
        adjustment_of=b.id,
        memo=f"approved fix for {b.id}: credit {account_ref}",
        lines=[
            Line(src, "debit", amount),
            Line(account(conn, clock, org_id, "user_balance", account_ref, cur), "credit", amount),
        ],
    )
    conn.execute(
        text(
            "INSERT INTO credits (id, org_id, inbound_transfer_id, deposit_intent_id, account_ref, "
            "amount_minor, currency, "
            "journal_id, created_at) VALUES (:id, :o, :i, :d, :a, :m, :c, :j, :t)"
        ),
        {
            "id": new_id(Prefix.CRD, clock.now()),
            "o": org_id,
            "i": inb.id,
            "d": intent_id,
            "a": account_ref,
            "m": amount,
            "c": cur.value,
            "j": jid,
            "t": clock.now(),
        },
    )
    conn.execute(
        text(
            "UPDATE inbound_transfers SET status='CREDITED', deposit_intent_id=coalesce(:d, "
            "deposit_intent_id) WHERE org_id=:o AND id=:i"
        ),
        {"d": intent_id, "o": org_id, "i": inb.id},
    )
    if intent_id:
        conn.execute(
            text("UPDATE deposit_intents SET status='CREDITED' WHERE org_id=:o AND id=:i"),
            {"o": org_id, "i": intent_id},
        )
    return jid


def _inbound_for(conn: Connection, clock: Clock, org_id: str, b: Any) -> tuple[Any, bool]:
    """The inbound transfer a deposit break is about; for an unbooked bank line, book it now."""
    if b.subject_key.startswith("suspense:"):
        inb = conn.execute(
            text("SELECT * FROM inbound_transfers WHERE org_id=:o AND id=:i FOR UPDATE"),
            {"o": org_id, "i": b.subject_key.split(":", 1)[1]},
        ).one()
        if inb.status != "SUSPENSE":
            raise FixError(f"inbound transfer {inb.id} is {inb.status}, not in suspense")
        return inb, True
    s = b.subject
    if b.kind != "rail_record_unbooked" or s.get("direction") != "in":
        raise FixError("this fix applies to money held in suspense or an unbooked incoming line")
    iid = new_id(Prefix.INB, clock.now())
    conn.execute(
        text(
            "INSERT INTO inbound_transfers (id, org_id, rail_id, tx_hash, log_index, from_address, "
            "to_address, amount_minor, "
            "token, confirmations, seen_at, currency, network, status, decided_at, decision) SELECT "
            ":id, :o, r.id, :h, 0, :f, "
            ":to, :a, r.currency, r.confirmations, :t, r.currency, r.network, 'SUSPENSE', :t, "
            "CAST(:d AS jsonb) FROM rails r "
            "WHERE r.org_id=:o AND r.id=:r"
        ),
        {
            "id": iid,
            "o": org_id,
            "r": s["rail_id"],
            "h": s["external_id"],
            "f": s.get("party"),
            "to": s.get("reference"),
            "a": int(s["amount_minor"]),
            "t": clock.now(),
            "d": '{"outcome": "BOOKED_BY_FIX", "break": "' + b.id + '"}',
        },
    )
    inb = conn.execute(
        text("SELECT * FROM inbound_transfers WHERE org_id=:o AND id=:i"), {"o": org_id, "i": iid}
    ).one()
    return inb, False


def approve_fix(
    engine: Engine, clock: Clock, *, org_id: str, break_id: str, actor: Actor, reason: str
) -> str | None:
    """Apply the proposed fix. Returns the adjustment's journal ID (None for a write-off)."""
    if not reason.strip():
        raise FixError("a reason is required", status=422, code="reason_required")
    with transaction(engine) as conn:
        b = _lock(conn, org_id, break_id, actor)
        fix = b.proposed_fix or {"action": "needs_investigation"}
        action, target = fix.get("action"), fix.get("target")
        jid: str | None = None
        if action == "needs_investigation":
            raise FixError(
                "needs_investigation is a question, not a fix: investigate, then reject or record a decision"
            )
        if action in ("match_to", "credit_account"):
            inb, from_suspense = _inbound_for(conn, clock, org_id, b)
            if action == "match_to":
                intent = conn.execute(
                    text(
                        "SELECT id, account_ref, currency, status FROM deposit_intents WHERE "
                        "org_id=:o AND id=:i FOR UPDATE"
                    ),
                    {"o": org_id, "i": target},
                ).one_or_none()
                if intent is None or intent.status != "OPEN" or intent.currency != inb.currency:
                    raise FixError(f"deposit intent {target} is no longer an open {inb.currency} intent")
                jid = _credit(conn, clock, org_id, b, inb, intent.account_ref, intent.id, from_suspense)
            else:
                jid = _credit(conn, clock, org_id, b, inb, str(target), None, from_suspense)
        elif action == "return_to_sender":
            inb, from_suspense = _inbound_for(conn, clock, org_id, b)
            cur = Currency(inb.currency)
            src = (
                account(conn, clock, org_id, "suspense", "suspense", cur)
                if from_suspense
                else account(conn, clock, org_id, "rail_clearing", f"{inb.rail_id}:inbound", cur)
            )
            jid = post(
                conn,
                clock,
                org_id=org_id,
                kind="adjustment.refund_due",
                currency=cur,
                deposit_id=inb.id,
                adjustment_of=b.id,
                memo=f"approved fix for {b.id}: return to sender {inb.from_address}",
                lines=[
                    Line(src, "debit", int(inb.amount_minor)),
                    Line(
                        account(conn, clock, org_id, "rail_clearing", f"{inb.rail_id}:refund_due", cur),
                        "credit",
                        int(inb.amount_minor),
                    ),
                ],
            )
            lead = conn.execute(
                text(
                    "SELECT email FROM users WHERE org_id=:o AND role='payments_lead' ORDER BY "
                    "created_at, id LIMIT 1"
                ),
                {"o": org_id},
            ).scalar_one_or_none()
            if lead:
                conn.execute(
                    text(
                        "INSERT INTO outbox (id, org_id, channel, recipient, template, body, "
                        "created_at) VALUES (:id, :o, "
                        "'email_mock', :r, 'recon.refund_due', :b, :t)"
                    ),
                    {
                        "id": new_id(Prefix.OBX, clock.now()),
                        "o": org_id,
                        "r": lead,
                        "b": f"Refund due: return {inb.amount_minor} minor units of {inb.currency} "
                        "on {inb.rail_id} to "
                        f"{inb.from_address} (inbound {inb.id}). The prototype does not send refunds "
                        "automatically.",
                        "t": clock.now(),
                    },
                )
        conn.execute(
            text(
                "UPDATE recon_breaks SET status='APPLIED', approved_by=:a, decided_at=:t, "
                "decision_reason=:r, "
                "applied_journal_id=:j WHERE org_id=:o AND id=:i"
            ),
            {"a": actor.id, "t": clock.now(), "r": reason.strip(), "j": jid, "o": org_id, "i": b.id},
        )
        if b.case_id:
            conn.execute(
                text(
                    "UPDATE exception_cases SET status='RESOLVED', resolution='approved', "
                    "resolution_reason=:r, "
                    "resolved_by=:a, resolved_at=:t WHERE org_id=:o AND id=:c AND status IN "
                    "('OPEN','HELD_OVERDUE')"
                ),
                {
                    "r": f"reconciliation fix {action} approved: {reason.strip()}",
                    "a": actor.id,
                    "t": clock.now(),
                    "o": org_id,
                    "c": b.case_id,
                },
            )
            append(
                conn,
                clock,
                org_id=org_id,
                actor=actor,
                kind="case.resolved",
                subject_id=b.case_id,
                payload={"resolution": "approved", "via": b.id},
            )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="reconciliation.fix_applied",
            subject_id=b.id,
            payload={"fix": fix, "journal_id": jid, "reason": reason.strip()},
        )
        return jid


def reject_fix(
    engine: Engine, clock: Clock, *, org_id: str, break_id: str, actor: Actor, reason: str
) -> None:
    if not reason.strip():
        raise FixError("a reason is required", status=422, code="reason_required")
    with transaction(engine) as conn:
        b = _lock(conn, org_id, break_id, actor)
        conn.execute(
            text(
                "UPDATE recon_breaks SET status='REJECTED', approved_by=:a, decided_at=:t, "
                "decision_reason=:r WHERE org_id=:o AND id=:i"
            ),
            {"a": actor.id, "t": clock.now(), "r": reason.strip(), "o": org_id, "i": b.id},
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="reconciliation.fix_rejected",
            subject_id=b.id,
            payload={"reason": reason.strip()},
        )
