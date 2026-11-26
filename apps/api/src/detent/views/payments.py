"""The payment intent as the API, the console and webhook events show it (INT-03, WHK-01). Read-only."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from detent.domain.money import Currency, Money


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def decision_json(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "outcome": row.outcome,
        "policy_version": row.policy_version,
        "policy_hash": row.policy_hash,
        "checks": row.checks,
        "approved_reasons": list(row.approved_reasons),
        "route": row.route,
        "decided_at": _iso(row.decided_at),
    }


_DEC_SQL = (
    "SELECT d.id, d.outcome, d.policy_hash, d.checks, d.approved_reasons, d.route, d.decided_at, "
    "v.version AS policy_version FROM decisions d JOIN policy_versions v "
    "ON v.org_id = d.org_id AND v.id = d.policy_version_id WHERE d.org_id=:o AND d.payment_id=:p "
    "ORDER BY d.decided_at, d.id"
)


def _open_case_ref(conn: Connection, org_id: str, payment_id: str) -> dict[str, Any] | None:
    r = conn.execute(
        text(
            "SELECT id, owner_id, deadline_at FROM exception_cases WHERE org_id=:o AND payment_id=:p "
            "AND status IN ('OPEN','HELD_OVERDUE') ORDER BY created_at DESC, id DESC LIMIT 1"
        ),
        {"o": org_id, "p": payment_id},
    ).one_or_none()
    return {"id": r.id, "owner": r.owner_id, "deadline_at": _iso(r.deadline_at)} if r else None


def payment_view(
    conn: Connection,
    org_id: str,
    payment_id: str,
    *,
    detail: bool = False,
    any_generation: bool = False,
) -> dict[str, Any] | None:
    """None for a missing payment, or one from an earlier data generation (SBX-04) unless
    `any_generation`: webhook events about a payment are built from it whichever generation it is in."""
    gen = (
        ""
        if any_generation
        else " AND p.generation = (SELECT data_generation FROM organisations WHERE org_id = :o)"
    )
    p = conn.execute(
        text(
            "SELECT p.*, d.kind AS d_kind, d.network AS d_network, d.address AS d_address "
            "FROM payment_intents p LEFT JOIN destinations d ON d.org_id = p.org_id AND d.id = "
            "p.destination_id "
            "WHERE p.org_id=:o AND p.id=:p" + gen
        ),
        {"o": org_id, "p": payment_id},
    ).one_or_none()
    if p is None:
        return None
    decisions = [decision_json(r) for r in conn.execute(text(_DEC_SQL), {"o": org_id, "p": payment_id}).all()]
    out: dict[str, Any] = {
        "id": p.id,
        "status": p.status,
        "source": p.source,
        "amount": Money(int(p.amount_minor), Currency(p.currency)).to_api(),
        "counterparty_id": p.counterparty_id,
        "user_account_ref": p.user_account_ref,
        "destination": {
            "destination_id": p.destination_id,
            "kind": p.d_kind,
            "network": p.d_network or p.network_constraint,
            "address": p.d_address,
        },
        "reference": p.reference,
        "decision": decisions[-1] if decisions else None,
        "exception": _open_case_ref(conn, org_id, payment_id),
        "awaiting_send_click": p.awaiting_send_click,
        "created_at": _iso(p.created_at),
    }
    if detail:
        events = conn.execute(
            text(
                "SELECT id, seq, at, actor, actor_role, kind, payload FROM audit_events "
                "WHERE org_id=:o AND subject_id=:p ORDER BY seq"
            ),
            {"o": org_id, "p": payment_id},
        ).all()
        attempts = conn.execute(
            text(
                "SELECT id, attempt_no, rail_id, status, failure_class, nonce, tx_hash, submitted_at, "
                "resolved_at, explorer_url, left(raw_tx, 4) = 'sim:' AS simulated "
                "FROM attempts WHERE org_id=:o AND payment_id=:p ORDER BY attempt_no"
            ),
            {"o": org_id, "p": payment_id},
        ).all()
        postings = conn.execute(
            text(
                "SELECT ps.account_id, ps.direction, ps.amount_minor, ps.currency, ps.journal_id, j.kind, "
                "a.kind AS account_kind, a.ref FROM postings ps "
                "JOIN journal_entries j ON j.org_id = ps.org_id AND j.id = ps.journal_id "
                "JOIN accounts a ON a.org_id = ps.org_id AND a.id = ps.account_id "
                "WHERE ps.org_id=:o AND j.payment_id=:p ORDER BY j.created_at, ps.id"
            ),
            {"o": org_id, "p": payment_id},
        ).all()
        out.update(
            decisions=decisions,
            attempts=[
                {
                    "id": a.id,
                    "attempt_no": a.attempt_no,
                    "rail": a.rail_id,
                    "status": a.status,
                    "failure_class": a.failure_class,
                    "nonce": a.nonce,
                    "tx_hash": a.tx_hash,
                    "explorer_url": a.explorer_url,  # SBX-03: real test networks only
                    "simulated": bool(a.simulated),  # RAL-11: on the sandbox's simulated chain
                    "submitted_at": _iso(a.submitted_at) if a.submitted_at else None,
                    "resolved_at": _iso(a.resolved_at) if a.resolved_at else None,
                }
                for a in attempts
            ],
            postings=[
                {
                    "account": f"{x.account_kind}:{x.ref}",
                    "account_id": x.account_id,
                    "entry": x.kind,
                    "direction": x.direction,
                    "journal_id": x.journal_id,
                    "amount": Money(int(x.amount_minor), Currency(x.currency)).to_api(),
                }
                for x in postings
            ],
            events=[
                {
                    "id": e.id,
                    "seq": e.seq,
                    "at": _iso(e.at),
                    "actor": e.actor,
                    "actor_role": e.actor_role,
                    "kind": e.kind,
                    "payload": e.payload,
                }
                for e in events
            ],
        )
    return out


# ------------------------------------------------------------------------------------------ the flow
