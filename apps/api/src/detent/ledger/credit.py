"""Deposit decision and credit-once (LED-05).

For each inbound transfer the watchers stored:

1. Wait until it has the rail's confirmation threshold. Before that nothing is decided.
2. Find the deposit intent: by address (chain) or reference (bank), preferring an open intent whose
   network, token and amount match.
3. Run the deposit checks (``detent.policy.deposits``): network and token match, sender screening,
   amount within tolerance (G-11), intent open and unexpired (G-21).
4. EXECUTE: credit the user's balance. Debit rail_clearing:{rail}:inbound, credit
   user_balance:{account}, and insert the ``credits`` row. ``credits`` is unique per inbound transfer,
   so a duplicate notification or a second run can never credit twice.
   Anything else: the money goes to suspense (debit inbound clearing, credit suspense) and a deposit
   exception opens. It is credited later only through an approved reconciliation fix (LED-06).

The inbound row is locked while deciding, so concurrent runs serialise; a decided row is skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.domain.money import Currency
from detent.exceptions.cases import open_deposit_case
from detent.ledger.journal import Line, account, post
from detent.policy.deposits import DepositFacts, IntentFacts, evaluate_deposit
from detent.policy.screening import Screening
from detent.policy.store import active_policy

ACTOR = Actor.system("deposits")


@dataclass(frozen=True, slots=True)
class Outcome:
    inbound_id: str
    status: str  # WAITING | CREDITED | SUSPENSE | ALREADY_DECIDED
    reasons: list[str]
    case_id: str | None = None
    credit_id: str | None = None


def _candidates(conn: Connection, org_id: str, inb: Any, rail_kind: str) -> list[Any]:
    if rail_kind == "evm":
        where, arg = "lower(deposit_address) = lower(:k)", inb.to_address
    else:
        where, arg = "reference = :k", inb.to_address
    return list(
        conn.execute(
            text(
                f"SELECT id, account_ref, currency, network, expected_amount_minor, status, expires_at "  # noqa: S608
                f"FROM deposit_intents WHERE org_id=:o AND {where} ORDER BY created_at, id"
            ),
            {"o": org_id, "k": arg},
        ).all()
    )


def _pick(cands: list[Any], inb: Any, tolerance: int) -> Any:
    """The open intent that fits best: same network and token and an acceptable amount, oldest first."""

    def fits(c: Any) -> int:
        score: int = 0
        score += 4 * int(c.status == "OPEN")
        score += 2 * int(c.network == inb.network and c.currency == inb.currency)
        score += int(
            c.expected_amount_minor is None
            or abs(int(inb.amount_minor) - int(c.expected_amount_minor)) <= tolerance
        )
        return score

    return max(cands, key=fits) if cands else None  # max keeps the first (oldest) among equals


def process_inbound(
    engine: Engine, clock: Clock, *, org_id: str, inbound_id: str, screening: Screening
) -> Outcome:
    with transaction(engine) as conn:
        inb = conn.execute(
            text("SELECT * FROM inbound_transfers WHERE org_id=:o AND id=:i FOR UPDATE"),
            {"o": org_id, "i": inbound_id},
        ).one()
        if inb.decided_at is not None:
            return Outcome(inbound_id, "ALREADY_DECIDED", [])
        rail = conn.execute(
            text("SELECT id, kind, confirmations FROM rails WHERE org_id=:o AND id=:r"),
            {"o": org_id, "r": inb.rail_id},
        ).one()
        if int(inb.confirmations) < int(rail.confirmations):
            return Outcome(
                inbound_id, "WAITING", [f"{inb.confirmations} of {rail.confirmations} confirmations"]
            )
        tolerance = int(
            conn.execute(
                text("SELECT deposit_tolerance_minor FROM organisations WHERE org_id=:o"), {"o": org_id}
            ).scalar_one()
        )
        intent = _pick(_candidates(conn, org_id, inb, rail.kind), inb, tolerance)
        if intent is not None:
            conn.execute(
                text("SELECT id FROM deposit_intents WHERE org_id=:o AND id=:i FOR UPDATE"),
                {"o": org_id, "i": intent.id},
            )
        facts = DepositFacts(
            amount_minor=int(inb.amount_minor),
            currency=str(inb.currency),
            network=str(inb.network),
            sender=str(inb.from_address or ""),
            received_at=inb.seen_at,
            intent=IntentFacts(
                intent.id,
                intent.account_ref,
                intent.currency,
                intent.network,
                None if intent.expected_amount_minor is None else int(intent.expected_amount_minor),
                intent.status,
                intent.expires_at,
            )
            if intent is not None
            else None,
            screening=screening.check(address=inb.from_address, name=None)
            if rail.kind == "evm"
            else screening.check(address=None, name=inb.from_address),
            tolerance_minor=tolerance,
        )
        outcome, checks = evaluate_deposit(facts)
        reasons = [c.reason for c in checks if c.result != "PASS" and c.reason]
        cur = Currency(inb.currency)
        amount = int(inb.amount_minor)
        inbound_acc = account(conn, clock, org_id, "rail_clearing", f"{inb.rail_id}:inbound", cur)
        decision = {
            "outcome": outcome,
            "checks": [c.to_json() for c in checks],
            "intent": intent.id if intent else None,
        }
        now = clock.now()
        if outcome == "EXECUTE":
            assert intent is not None
            jid = post(
                conn,
                clock,
                org_id=org_id,
                kind="deposit.credit",
                currency=cur,
                deposit_id=inbound_id,
                memo=f"deposit {intent.id} for {intent.account_ref}",
                lines=[
                    Line(inbound_acc, "debit", amount),
                    Line(
                        account(conn, clock, org_id, "user_balance", intent.account_ref, cur),
                        "credit",
                        amount,
                    ),
                ],
            )
            credit_id = new_id(Prefix.CRD, now)
            conn.execute(
                text(
                    "INSERT INTO credits (id, org_id, inbound_transfer_id, deposit_intent_id, "
                    "account_ref, amount_minor, "
                    "currency, journal_id, created_at) VALUES (:id, :o, :i, :d, :a, :m, :c, :j, :t)"
                ),
                {
                    "id": credit_id,
                    "o": org_id,
                    "i": inbound_id,
                    "d": intent.id,
                    "a": intent.account_ref,
                    "m": amount,
                    "c": cur.value,
                    "j": jid,
                    "t": now,
                },
            )
            conn.execute(
                text("UPDATE deposit_intents SET status='CREDITED' WHERE org_id=:o AND id=:i"),
                {"o": org_id, "i": intent.id},
            )
            status, case_id = "CREDITED", None
        else:
            post(
                conn,
                clock,
                org_id=org_id,
                kind="deposit.suspense",
                currency=cur,
                deposit_id=inbound_id,
                memo=f"held in suspense: {', '.join(reasons)}",
                lines=[
                    Line(inbound_acc, "debit", amount),
                    Line(account(conn, clock, org_id, "suspense", "suspense", cur), "credit", amount),
                ],
            )
            # The intent it was compared with stays OPEN: its own deposit may still arrive (dep-07 vs dep-05).
            case_id = open_deposit_case(
                conn,
                clock,
                org_id=org_id,
                inbound_id=inbound_id,
                reasons=reasons,
                rules=active_policy(conn, org_id).rules,
            )
            status, credit_id = "SUSPENSE", None
        conn.execute(
            text(
                "UPDATE inbound_transfers SET status=:s, deposit_intent_id=:d, decision=CAST(:j AS "
                "jsonb), decided_at=:t "
                "WHERE org_id=:o AND id=:i"
            ),
            {
                "s": status,
                "d": intent.id if intent else None,
                "j": json.dumps(decision),
                "t": now,
                "o": org_id,
                "i": inbound_id,
            },
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=ACTOR,
            kind="deposit.credited" if status == "CREDITED" else "deposit.exception",
            subject_id=inbound_id,
            payload={**decision, "amount_minor": amount, "currency": cur.value, "case_id": case_id},
        )
        return Outcome(inbound_id, status, reasons, case_id, credit_id)


def process_pending(engine: Engine, clock: Clock, *, org_id: str, screening: Screening) -> list[Outcome]:
    with engine.connect() as conn:
        ids = [
            str(i)
            for i in conn.execute(
                text(
                    "SELECT id FROM inbound_transfers WHERE org_id=:o AND decided_at IS NULL ORDER "
                    "BY seen_at, id"
                ),
                {"o": org_id},
            ).scalars()
        ]
    return [process_inbound(engine, clock, org_id=org_id, inbound_id=i, screening=screening) for i in ids]
