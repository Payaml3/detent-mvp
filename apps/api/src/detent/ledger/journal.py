"""Accounts and journal entries (LED-01, spec/02 "Ledger accounts and postings").

- Every entry is balanced per currency: total debits equal total credits. The database checks this
  at commit with a deferred constraint trigger, so a half-written entry can never be committed.
- Entries and postings are append-only (triggers since migration 0001). A correction is a new entry
  whose ``adjustment_of`` names what it corrects.
- Every entry references a payment, a deposit (an inbound transfer or deposit intent) or an
  adjustment (a reconciliation break); a database CHECK enforces it.
- Amounts are integer minor units with a currency. No floats.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.domain.ids import Prefix, new_id
from detent.domain.money import Currency

Kind = Literal["user_balance", "platform_operating", "rail_clearing", "fees", "suspense"]
Side = Literal["debit", "credit"]


class Unbalanced(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Line:
    account_id: str
    side: Side
    amount_minor: int


def account(
    conn: Connection, clock: Clock, org_id: str, kind: Kind, ref: str, currency: Currency | str
) -> str:
    """The account's ID, created on first use. One account per (kind, ref, currency)."""
    cur = Currency(currency).value
    found = conn.execute(
        text("SELECT id FROM accounts WHERE org_id=:o AND kind=:k AND ref=:r AND currency=:c"),
        {"o": org_id, "k": kind, "r": ref, "c": cur},
    ).scalar_one_or_none()
    if found:
        return str(found)
    new = new_id(Prefix.ACC, clock.now())
    conn.execute(
        text(
            "INSERT INTO accounts (id, org_id, kind, ref, currency) VALUES (:id, :o, :k, :r, :c) "
            "ON CONFLICT (org_id, kind, ref, currency) DO NOTHING"
        ),
        {"id": new, "o": org_id, "k": kind, "r": ref, "c": cur},
    )
    return str(
        conn.execute(
            text("SELECT id FROM accounts WHERE org_id=:o AND kind=:k AND ref=:r AND currency=:c"),
            {"o": org_id, "k": kind, "r": ref, "c": cur},
        ).scalar_one()
    )


LEDGER = Actor.system("ledger")


def post(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    kind: str,
    currency: Currency | str,
    lines: list[Line],
    payment_id: str | None = None,
    deposit_id: str | None = None,
    adjustment_of: str | None = None,
    memo: str | None = None,
) -> str:
    """Write one balanced entry. Raises ``Unbalanced`` before touching the database if it isn't."""
    if not lines or any(ln.amount_minor <= 0 or isinstance(ln.amount_minor, bool) for ln in lines):
        raise Unbalanced("every posting needs a positive integer amount")
    if not all(isinstance(ln.amount_minor, int) for ln in lines):
        raise Unbalanced("amounts are integer minor units")
    debits = sum(ln.amount_minor for ln in lines if ln.side == "debit")
    credits = sum(ln.amount_minor for ln in lines if ln.side == "credit")
    if debits != credits:
        raise Unbalanced(f"debits {debits} != credits {credits}")
    if payment_id is None and deposit_id is None and adjustment_of is None:
        raise Unbalanced("an entry must reference a payment, a deposit or an adjustment")
    cur = Currency(currency).value
    now = clock.now()
    jid = new_id(Prefix.JRN, now)
    conn.execute(
        text(
            "INSERT INTO journal_entries (id, org_id, kind, payment_id, deposit_id, adjustment_of, memo, "
            "created_at) VALUES (:id, :o, :k, :p, :d, :a, :m, :t)"
        ),
        {
            "id": jid,
            "o": org_id,
            "k": kind,
            "p": payment_id,
            "d": deposit_id,
            "a": adjustment_of,
            "m": memo,
            "t": now,
        },
    )
    for ln in lines:
        conn.execute(
            text(
                "INSERT INTO postings (id, org_id, journal_id, account_id, direction, amount_minor, "
                "currency) "
                "VALUES (:id, :o, :j, :a, :d, :m, :c)"
            ),
            {
                "id": new_id(Prefix.PST, now),
                "o": org_id,
                "j": jid,
                "a": ln.account_id,
                "d": ln.side,
                "m": ln.amount_minor,
                "c": cur,
            },
        )
    # AUD-01: every posting is audited in the same transaction as the entry it belongs to.
    append(
        conn,
        clock,
        org_id=org_id,
        actor=LEDGER,
        kind="ledger.posted",
        subject_id=payment_id or deposit_id or adjustment_of or jid,
        payload={
            "journal_id": jid,
            "kind": kind,
            "currency": cur,
            "lines": [
                {"account_id": ln.account_id, "side": ln.side, "amount_minor": ln.amount_minor}
                for ln in lines
            ],
            "adjustment_of": adjustment_of,
        },
    )
    return jid


def balances(conn: Connection, org_id: str) -> list[dict[str, object]]:
    """Each account's balance as debits minus credits, in minor units."""
    rows = conn.execute(
        text(
            "SELECT a.id, a.kind, a.ref, a.currency, "
            "coalesce(sum(CASE WHEN p.direction='debit' THEN p.amount_minor ELSE -p.amount_minor "
            "END), 0) AS bal "
            "FROM accounts a LEFT JOIN postings p ON p.org_id = a.org_id AND p.account_id = a.id "
            "WHERE a.org_id=:o GROUP BY a.id, a.kind, a.ref, a.currency ORDER BY a.kind, a.ref, a.currency"
        ),
        {"o": org_id},
    ).all()
    return [
        {"id": r.id, "kind": r.kind, "ref": r.ref, "currency": r.currency, "balance_minor": int(r.bal)}
        for r in rows
    ]


def trial_balance(conn: Connection, org_id: str) -> dict[str, int]:
    """Debits minus credits per currency over the whole ledger. Always 0 for every currency."""
    rows = conn.execute(
        text(
            "SELECT currency, coalesce(sum(CASE WHEN direction='debit' THEN amount_minor ELSE "
            "-amount_minor END), 0) "
            "FROM postings WHERE org_id=:o GROUP BY currency ORDER BY currency"
        ),
        {"o": org_id},
    ).all()
    return {str(c): int(v) for c, v in rows}


def entries_for(
    conn: Connection, org_id: str, *, payment_id: str | None = None, deposit_id: str | None = None
) -> list[dict[str, object]]:
    rows = conn.execute(
        text(
            "SELECT j.id AS journal_id, j.kind, j.created_at, j.adjustment_of, a.kind AS "
            "account_kind, a.ref, "
            "p.direction, p.amount_minor, p.currency FROM journal_entries j JOIN postings p ON "
            "p.org_id = j.org_id "
            "AND p.journal_id = j.id JOIN accounts a ON a.org_id = p.org_id AND a.id = p.account_id "
            "WHERE j.org_id=:o AND (j.payment_id = :p OR j.deposit_id = :d) ORDER BY j.created_at, "
            "j.id, p.direction DESC"
        ),
        {"o": org_id, "p": payment_id, "d": deposit_id},
    ).all()
    return [dict(r._mapping) for r in rows]
