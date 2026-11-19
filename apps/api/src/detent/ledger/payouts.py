"""Payout postings (LED-02, spec/02 "Ledger accounts and postings").

Called by ``transition()`` in the same transaction as each payment status change:

- SUBMITTED: reserve. Debit platform_operating, credit rail_clearing:{rail}:pending. A retry or a
  failover under the same payment ID finds the reservation already there and adds nothing.
- CONFIRMED: settle. Debit the reservation's pending account, credit rail_clearing:{rail}:settled on
  the rail that confirmed; then the rail's actual fee: debit fees:{rail}, credit the settled account.
- FAILED_FINAL, CANCELLED, BLOCKED or REJECTED with a reservation still open: reverse it.
- UNKNOWN and a retryable FAILED keep the reservation (invariant 3: nothing is assumed).

User payouts (debit user_balance) are deferred with the user-payout profile.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, text

from detent.clock import Clock
from detent.domain.money import Currency, Money
from detent.ledger.journal import Line, account, post

RELEASE = frozenset({"FAILED_FINAL", "CANCELLED", "BLOCKED", "REJECTED"})


def _open_reservation(conn: Connection, org_id: str, pid: str) -> Any:
    """The reserve entry and its pending account, if not yet settled or reversed."""
    return conn.execute(
        text(
            "SELECT j.id, a.id AS account_id, a.ref, p.amount_minor, p.currency FROM journal_entries j "
            "JOIN postings p ON p.org_id = j.org_id AND p.journal_id = j.id AND p.direction = 'credit' "
            "JOIN accounts a ON a.org_id = p.org_id AND a.id = p.account_id "
            "WHERE j.org_id=:o AND j.payment_id=:p AND j.kind='payout.reserve' "
            "AND NOT EXISTS (SELECT 1 FROM journal_entries k WHERE k.org_id = j.org_id AND "
            "k.payment_id = j.payment_id "
            "AND k.kind IN ('payout.settle','payout.reverse') AND k.adjustment_of = j.id)"
        ),
        {"o": org_id, "p": pid},
    ).one_or_none()


def _attempt(conn: Connection, org_id: str, pid: str, status: str) -> Any:
    return conn.execute(
        text(
            "SELECT a.id, a.rail_id, r.fee_flat_minor, r.fee_bps FROM attempts a JOIN rails r ON "
            "r.org_id = a.org_id "
            "AND r.id = a.rail_id WHERE a.org_id=:o AND a.payment_id=:p AND a.status = ANY(:s) "
            "ORDER BY a.attempt_no DESC LIMIT 1"
        ),
        {
            "o": org_id,
            "p": pid,
            "s": [status] if status != "IN_FLIGHT" else ["CREATED", "SUBMITTED", "UNKNOWN"],
        },
    ).one_or_none()


def on_status(  # noqa: PLR0911 - one return per ledger outcome
    conn: Connection, clock: Clock, *, org_id: str, payment_id: str, new_status: str
) -> str | None:
    """Post the entry a status change calls for. Returns the journal ID, or None."""
    if new_status not in {"SUBMITTED", "CONFIRMED"} | RELEASE:
        return None
    pay = conn.execute(
        text("SELECT amount_minor, currency FROM payment_intents WHERE org_id=:o AND id=:p"),
        {"o": org_id, "p": payment_id},
    ).one()
    amount, cur = int(pay.amount_minor), Currency(pay.currency)
    held = _open_reservation(conn, org_id, payment_id)
    if new_status == "SUBMITTED":
        if held is not None:
            return None  # retry or failover: the money is already reserved
        att = _attempt(conn, org_id, payment_id, "IN_FLIGHT")
        if att is None:
            return None
        return post(
            conn,
            clock,
            org_id=org_id,
            kind="payout.reserve",
            currency=cur,
            payment_id=payment_id,
            memo=f"reserved for attempt {att.id} on {att.rail_id}",
            lines=[
                Line(account(conn, clock, org_id, "platform_operating", "platform", cur), "debit", amount),
                Line(
                    account(conn, clock, org_id, "rail_clearing", f"{att.rail_id}:pending", cur),
                    "credit",
                    amount,
                ),
            ],
        )
    if held is None:
        return None
    if new_status == "CONFIRMED":
        att = _attempt(conn, org_id, payment_id, "CONFIRMED")
        rail = att.rail_id if att else held.ref.rsplit(":", 1)[0]
        settled = account(conn, clock, org_id, "rail_clearing", f"{rail}:settled", cur)
        jid = post(
            conn,
            clock,
            org_id=org_id,
            kind="payout.settle",
            currency=cur,
            payment_id=payment_id,
            adjustment_of=held.id,
            memo=f"confirmed on {rail}" + (f" by attempt {att.id}" if att else ""),
            lines=[Line(held.account_id, "debit", amount), Line(settled, "credit", amount)],
        )
        fee = (int(att.fee_flat_minor) + amount * int(att.fee_bps) // 10_000) if att else 0
        if fee > 0:
            post(
                conn,
                clock,
                org_id=org_id,
                kind="payout.fee",
                currency=cur,
                payment_id=payment_id,
                memo=f"{rail} fee {Money(fee, cur)}",
                lines=[
                    Line(account(conn, clock, org_id, "fees", rail, cur), "debit", fee),
                    Line(settled, "credit", fee),
                ],
            )
        return jid
    return post(
        conn,
        clock,
        org_id=org_id,
        kind="payout.reverse",
        currency=cur,
        payment_id=payment_id,
        adjustment_of=held.id,
        memo=f"reservation released: payment {new_status}",
        lines=[
            Line(held.account_id, "debit", amount),
            Line(account(conn, clock, org_id, "platform_operating", "platform", cur), "credit", amount),
        ],
    )
