"""EXC-08 and WHK-01: the exception case as the API, the console and webhook events show it. Read-only.

`raw_facts` is shared with the console (EXC-02): the API shows the same facts the reviewer reads first.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from detent.sandbox.generations import CURRENT

_CASE_COLS = (
    "id, type, status, payment_id, deposit_id, tier, reasons, owner_id, backup_owner_id, deadline_at, "
    "resolution, resolution_reason, resolved_by, resolved_at, created_at"
)


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v is not None else None


def summary_json(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "object": "exception",
        "type": r.type,
        "status": r.status,
        "payment_id": r.payment_id,
        "deposit_id": r.deposit_id,
        "tier": r.tier,
        "reasons": list(r.reasons or []),
        "owner_id": r.owner_id,
        "backup_owner_id": r.backup_owner_id,
        "deadline_at": _iso(r.deadline_at),
        "resolution": r.resolution,
        "resolved_by": r.resolved_by,
        "resolved_at": _iso(r.resolved_at),
        "created": _iso(r.created_at),
    }


def case_summary(conn: Connection, org_id: str, case_id: str) -> dict[str, Any]:
    r = conn.execute(
        text(f"SELECT {_CASE_COLS} FROM exception_cases WHERE org_id=:o AND id=:c"),  # noqa: S608
        {"o": org_id, "c": case_id},
    ).one_or_none()
    return summary_json(r) if r is not None else {"id": case_id, "object": "exception"}


def list_cases(
    conn: Connection,
    org_id: str,
    *,
    now: datetime,
    status: str | None,
    owner: str | None,
    tier: int | None,
    overdue: bool | None,
    limit: int,
    starting_after: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Newest first. `status=open` means OPEN or HELD_OVERDUE; `overdue=true` means past the deadline."""
    statuses = {"open": ["OPEN", "HELD_OVERDUE"], "resolved": ["RESOLVED"]}.get(status or "")
    rows = conn.execute(
        text(
            f"SELECT {_CASE_COLS} FROM exception_cases WHERE org_id=:o AND {CURRENT} "  # noqa: S608
            "AND (CAST(:st AS TEXT[]) IS NULL OR status = ANY(CAST(:st AS TEXT[]))) "
            "AND (CAST(:own AS TEXT) IS NULL OR owner_id = :own) "
            "AND (CAST(:tier AS INTEGER) IS NULL OR tier = :tier) "
            "AND (CAST(:ovd AS BOOLEAN) IS NULL OR (status <> 'RESOLVED' AND (deadline_at <= :now "
            "OR status = 'HELD_OVERDUE')) = :ovd) "
            "AND (CAST(:after AS TEXT) IS NULL OR (created_at, id) < "
            "(SELECT created_at, id FROM exception_cases WHERE org_id=:o AND id=:after)) "
            "ORDER BY created_at DESC, id DESC LIMIT :n"
        ),
        {
            "o": org_id,
            "st": statuses,
            "own": owner,
            "tier": tier,
            "ovd": overdue,
            "now": now,
            "after": starting_after,
            "n": limit + 1,
        },
    ).all()
    return [summary_json(r) for r in rows[:limit]], len(rows) > limit


def case_detail(conn: Connection, org_id: str, case_id: str) -> dict[str, Any] | None:
    """Raw facts first, then the rule hits, the agent's evidence and the case history (EXC-02, EXC-03)."""
    r = conn.execute(
        text(
            f"SELECT {_CASE_COLS} FROM exception_cases WHERE org_id=:o AND id=:c AND {CURRENT}"  # noqa: S608
        ),
        {"o": org_id, "c": case_id},
    ).one_or_none()
    if r is None:  # missing, or from an earlier data generation (SBX-04)
        return None
    out = summary_json(r)
    out["resolution_reason"] = r.resolution_reason
    if r.payment_id is not None:
        f = raw_facts(conn, org_id, r.payment_id)
        out["raw_facts"] = {
            "payee": f["payee"],
            "kyb_status": f["kyb"],
            "allowlisted": f["allowlisted"],
            "destination": {
                "network": f["network"],
                "address": f["address"],
                "account_masked": f["account_masked"],
                "verified": f["verified"],
                "first_seen_at": _iso(f["first_seen"]),
                "last_changed_at": _iso(f["last_changed"]),
                "last_changed_by": f["changed_by"],
            },
            "amount": f["amount_money"].to_api(),
            "median_amount": f["median_money"].to_api() if f["median_money"] else None,
            "amount_to_median": f["ratio"],
            "payment_count": f["payment_count"],
            "mandate_id": f["mandate"],
            "source": f["source"],
            "reference": f["reference"],
            "initiated_by": f["initiated_by"],
        }
        out["rule_hits"] = f["hits"]
    else:
        out["raw_facts"] = None
        out["rule_hits"] = []
    from detent.agents.investigation import latest_investigation

    out["investigation"] = latest_investigation(conn, org_id, case_id)
    out["history"] = [
        {"kind": e.kind, "actor": e.actor, "at": _iso(e.at), "detail": dict(e.payload)}
        for e in conn.execute(
            text(
                "SELECT kind, actor, payload, at FROM case_events WHERE org_id=:o AND case_id=:c "
                "ORDER BY at, id"
            ),
            {"o": org_id, "c": case_id},
        ).all()
    ]
    return out


def raw_facts(conn: Connection, org_id: str, payment_id: str) -> dict[str, Any]:
    """EXC-02: what the reviewer reads first, straight from the registry and the decision."""
    from web3 import Web3

    from detent.domain.money import Currency, Money

    p = conn.execute(
        text(
            "SELECT p.*, c.name AS payee, c.kyb_status, c.allowlisted, c.payment_count, "
            "c.median_amount_minor, "
            "c.median_currency, d.address, d.account_masked, d.network AS d_network, d.first_seen_at, "
            "d.last_changed_at, d.last_changed_by, d.verified FROM payment_intents p "
            "LEFT JOIN counterparties c ON c.org_id = p.org_id AND c.id = p.counterparty_id "
            "LEFT JOIN destinations d ON d.org_id = p.org_id AND d.id = p.destination_id "
            "WHERE p.org_id=:o AND p.id=:p"
        ),
        {"o": org_id, "p": payment_id},
    ).one()
    dec = conn.execute(
        text(
            "SELECT checks FROM decisions WHERE org_id=:o AND payment_id=:p ORDER BY decided_at DESC, id "
            "DESC LIMIT 1"
        ),
        {"o": org_id, "p": payment_id},
    ).scalar_one()
    amount = Money(int(p.amount_minor), Currency(p.currency))
    median = (
        Money(int(p.median_amount_minor), Currency(p.median_currency))
        if p.median_amount_minor is not None
        else None
    )
    ratio = None
    if median is not None and median.currency == amount.currency and median.amount_minor:
        from decimal import Decimal

        ratio = str((Decimal(amount.amount_minor) / Decimal(median.amount_minor)).quantize(Decimal("0.01")))
    hits = [c for c in dec if c.get("result") in ("ESCALATE", "BLOCK")]
    return {
        "payee": p.payee,
        "kyb": p.kyb_status,
        "allowlisted": p.allowlisted,
        "address": Web3.to_checksum_address(p.address) if p.address else None,
        "account_masked": p.account_masked,
        "network": p.d_network or p.network_constraint,
        "verified": p.verified,
        "first_seen": p.first_seen_at,
        "last_changed": p.last_changed_at,
        "changed_by": p.last_changed_by,
        "amount": str(amount),
        "median": str(median) if median else None,
        "amount_money": amount,
        "median_money": median,
        "ratio": ratio,
        "payment_count": p.payment_count,
        "hits": hits,
        "mandate": p.mandate_id,
        "source": p.source,
        "reference": p.reference,
        "initiated_by": p.initiated_by,
    }
