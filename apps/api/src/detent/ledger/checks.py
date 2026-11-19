"""Does the ledger agree with each payment's status? (LED-02 AC2, spec/09 "the ledger balances")

- Every currency nets to zero across the organisation's ledger.
- CONFIRMED: one reservation, settled once, nothing open.
- FAILED_FINAL, CANCELLED, BLOCKED, REJECTED, SHADOWED: nothing open (released or never reserved).
- SUBMITTED, UNKNOWN: the reservation is open (a timeout assumes nothing).
- Any other status: a reservation is open exactly when an attempt was ever made (a retry keeps it).
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from detent.ledger.journal import trial_balance


def disagreements(conn: Connection, org_id: str) -> list[str]:
    out = [f"ledger does not net to zero in {c}: {v}" for c, v in trial_balance(conn, org_id).items() if v]
    rows = conn.execute(
        text(
            "SELECT p.id, p.status, "
            "(SELECT count(*) FROM journal_entries j WHERE j.org_id=p.org_id AND j.payment_id=p.id "
            "AND j.kind='payout.reserve') AS r, "
            "(SELECT count(*) FROM journal_entries j WHERE j.org_id=p.org_id AND j.payment_id=p.id "
            "AND j.kind='payout.settle') AS s, "
            "(SELECT count(*) FROM journal_entries j WHERE j.org_id=p.org_id AND j.payment_id=p.id "
            "AND j.kind='payout.reverse') AS v, "
            "(SELECT count(*) FROM attempts a WHERE a.org_id=p.org_id AND a.payment_id=p.id) AS n "
            "FROM payment_intents p WHERE p.org_id=:o"
        ),
        {"o": org_id},
    ).all()
    for p in rows:
        opened = int(p.r) - int(p.s) - int(p.v)
        if int(p.r) > 1 or opened < 0:
            out.append(f"{p.id}: {p.r} reservations, {p.s} settlements, {p.v} reversals")
        elif p.status == "CONFIRMED" and not (p.r == 1 and p.s == 1):
            out.append(f"{p.id}: CONFIRMED but reserve={p.r} settle={p.s}")
        elif p.status in ("FAILED_FINAL", "CANCELLED", "BLOCKED", "REJECTED", "SHADOWED") and opened:
            out.append(f"{p.id}: {p.status} with an open reservation")
        elif p.status in ("SUBMITTED", "UNKNOWN") and opened != 1:
            out.append(f"{p.id}: {p.status} without an open reservation")
        elif (
            p.status not in ("CONFIRMED", "SUBMITTED", "UNKNOWN")
            and opened != (1 if int(p.n) else 0)
            and p.status
            not in (
                "FAILED_FINAL",
                "CANCELLED",
                "BLOCKED",
                "REJECTED",
                "SHADOWED",
            )
        ):
            out.append(f"{p.id}: {p.status}, {p.n} attempts, {opened} open reservations")
    return out
