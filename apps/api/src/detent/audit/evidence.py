"""Evidence pack for a payment or a date range (AUD-03), for an auditor to review offline.

The pack reads stored rows only and calls no model (like replay). Per payment: the intent's inputs, every
decision with its rule version and checks, the people who approved or rejected it, every state change from the
audit log, and each attempt with its transaction hash and explorer link. The whole pack carries the result of
the organisation's hash-chain check at the time it was built. Exports: JSON (the pack itself) and a readable
HTML or PDF of the same content (``as_lines``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from detent.audit.log import verify_chain
from detent.domain.money import Currency, Money

MAX_PAYMENTS = 500


class EvidenceError(ValueError):
    pass


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


def _money(minor: int, currency: str) -> str:
    return f"{Money(int(minor), Currency(currency)).to_decimal_str()} {currency}"


def _payment(conn: Connection, org_id: str, p: Any) -> dict[str, Any]:
    q = {"o": org_id, "p": p.id}
    decisions = conn.execute(
        text(
            "SELECT d.id, d.outcome, d.decided_at, d.actor, d.checks, d.inputs_snapshot, d.approved_reasons, "
            "d.policy_hash, v.version FROM decisions d JOIN policy_versions v ON v.org_id = d.org_id "
            "AND v.id = d.policy_version_id WHERE d.org_id=:o AND d.payment_id=:p ORDER BY d.decided_at, d.id"
        ),
        q,
    ).all()
    cases = conn.execute(
        text(
            "SELECT id, status, resolution, resolution_reason, resolved_by, resolved_at FROM exception_cases "
            "WHERE org_id=:o AND payment_id=:p ORDER BY created_at, id"
        ),
        q,
    ).all()
    changes = conn.execute(
        text(
            "SELECT seq, at, actor, actor_role, payload FROM audit_events WHERE org_id=:o AND subject_id=:p "
            "AND kind='payment.status_changed' ORDER BY seq"
        ),
        q,
    ).all()
    attempts = conn.execute(
        text(
            "SELECT id, attempt_no, rail_id, status, failure_class, tx_hash, rail_reference, explorer_url, "
            "created_at, submitted_at, resolved_at FROM attempts WHERE org_id=:o AND payment_id=:p "
            "ORDER BY attempt_no"
        ),
        q,
    ).all()
    return {
        "id": p.id,
        "status": p.status,
        "inputs": {
            "source": p.source,
            "amount": _money(p.amount_minor, p.currency),
            "counterparty_id": p.counterparty_id,
            "user_account_ref": p.user_account_ref,
            "destination_id": p.destination_id,
            "network": p.network_constraint,
            "allow_network_switch": p.allow_network_switch,
            "reference": p.reference,
            "mandate_id": p.mandate_id,
            "initiated_by": p.initiated_by,
            "created_at": _iso(p.created_at),
        },
        "decisions": [
            {
                "id": d.id,
                "outcome": d.outcome,
                "rule_version": int(d.version),
                "rule_hash": d.policy_hash,
                "decided_at": _iso(d.decided_at),
                "actor": d.actor,
                "approved_reasons": list(d.approved_reasons),
                "checks": d.checks,
                "inputs_snapshot": d.inputs_snapshot,
            }
            for d in decisions
        ],
        "approvals": [
            {
                "case_id": c.id,
                "resolution": c.resolution,
                "by": c.resolved_by,
                "at": _iso(c.resolved_at),
                "reason": c.resolution_reason,
            }
            for c in cases
            if c.resolution
        ],
        "state_changes": [
            {
                "seq": int(e.seq),
                "at": _iso(e.at),
                "actor": e.actor,
                "role": e.actor_role,
                "from": (e.payload or {}).get("from"),
                "to": (e.payload or {}).get("to"),
                "reason": (e.payload or {}).get("reason"),
            }
            for e in changes
        ],
        "attempts": [
            {
                "id": a.id,
                "attempt_no": int(a.attempt_no),
                "rail": a.rail_id,
                "status": a.status,
                "failure_class": a.failure_class,
                "tx_hash": a.tx_hash,
                "rail_reference": a.rail_reference,
                "explorer_url": a.explorer_url,
                "created_at": _iso(a.created_at),
                "resolved_at": _iso(a.resolved_at),
            }
            for a in attempts
        ],
    }


def build(
    conn: Connection,
    org_id: str,
    *,
    now: datetime,
    payment_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """One payment, or every payment created in [start, end). Raises EvidenceError for a bad scope."""
    if payment_id is None and (start is None or end is None):
        raise EvidenceError("choose a payment, or a date range with a start and an end")
    if start is not None and end is not None and end <= start:
        raise EvidenceError("the range must end after it starts")
    if payment_id is not None:
        rows = conn.execute(
            text("SELECT * FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org_id, "p": payment_id}
        ).all()
        if not rows:
            raise EvidenceError(f"no payment {payment_id}")
    else:
        rows = conn.execute(
            text(
                "SELECT * FROM payment_intents WHERE org_id=:o AND created_at >= :s AND created_at < :e "
                "ORDER BY created_at, id LIMIT :n"
            ),
            {"o": org_id, "s": start, "e": end, "n": MAX_PAYMENTS + 1},
        ).all()
    truncated = len(rows) > MAX_PAYMENTS
    chain = verify_chain(conn, org_id)
    return {
        "kind": "dekernai.evidence_pack",
        "version": 1,
        "org_id": org_id,
        "generated_at": _iso(now),
        "scope": {"payment_id": payment_id, "from": _iso(start), "to": _iso(end)},
        "hash_chain": {
            "ok": chain.ok,
            "events": chain.events,
            "first_bad_seq": chain.first_bad_seq,
            "problem": chain.problem,
        },
        "truncated": truncated,
        "payments": [_payment(conn, org_id, p) for p in rows[:MAX_PAYMENTS]],
        "note": (
            "Prototype: test networks and the simulated bank only. "
            "Built from stored rows; no model was called."
        ),
    }


def as_lines(pack: dict[str, Any]) -> list[str]:
    """The pack as plain lines for the PDF export (same content and order as the HTML)."""
    ch = pack["hash_chain"]
    sc = pack["scope"]
    scope = (
        f"payment {sc['payment_id']}" if sc["payment_id"] else f"payments created {sc['from']} to {sc['to']}"
    )
    lines = [
        "# Evidence pack",
        f"Organisation {pack['org_id']}. Scope: {scope}. Built {pack['generated_at']}.",
        (
            f"Hash chain: verified, {ch['events']} events."
            if ch["ok"]
            else f"Hash chain: BROKEN at seq {ch['first_bad_seq']} ({ch['problem']})."
        ),
        f"{len(pack['payments'])} payments" + (" (truncated)" if pack["truncated"] else "") + ".",
    ]
    for p in pack["payments"]:
        i = p["inputs"]
        lines += ["", f"## {p['id']} ({p['status']})"]
        lines.append(
            f"Inputs: {i['amount']} to {i['counterparty_id'] or i['user_account_ref']}, network "
            f"{i['network']}, "
            f"reference {i['reference'] or '-'}, source {i['source']}, created {i['created_at']}."
        )
        for d in p["decisions"]:
            reasons = [c.get("reason") or c.get("check") for c in d["checks"] if c.get("result") != "pass"]
            lines.append(
                f"- Decision {d['outcome']} under rule version {d['rule_version']} at {d['decided_at']} "
                f"by {d['actor']}" + (f"; reasons {', '.join(str(r) for r in reasons)}" if reasons else "")
            )
        for a in p["approvals"]:
            lines.append(f"- {a['resolution']} by {a['by']} at {a['at']}: {a['reason'] or ''}")
        for s in p["state_changes"]:
            lines.append(f"- {s['at']} {s['from']} to {s['to']} by {s['actor']}")
        for a in p["attempts"]:
            tx = a["tx_hash"] or a["rail_reference"] or "-"
            link = f" ({a['explorer_url']})" if a["explorer_url"] else ""
            lines.append(f"- Attempt {a['attempt_no']} on {a['rail']}: {a['status']}, {tx}{link}")
    lines += ["", pack["note"]]
    return lines
