"""Agent-versus-human agreement sample (EXC-09).

For the cases resolved in a period, compare the investigation agent's recommendation (the newest recorded
investigation for the case, EXC-03) with the person's final decision. ``approve`` agrees with an approval and
``reject`` with a rejection; ``needs_information`` and cases with no recorded investigation are counted but
are not compared. Disagreements are listed with both rationales: the agent's cited claims and the person's
written reason. The report only reads; it never calls a model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

AGREES = {"approve": "approved", "reject": "rejected"}


def sample(conn: Connection, org_id: str, start: datetime, end: datetime) -> dict[str, Any]:
    rows = conn.execute(
        text(
            "SELECT c.id, c.payment_id, c.resolution, c.resolution_reason, c.resolved_by, c.resolved_at, "
            "(SELECT a.parsed FROM agent_calls a WHERE a.org_id = c.org_id AND a.kind = 'investigation' "
            " AND a.subject_id = c.id AND a.status = 'recorded' ORDER BY a.created_at DESC, a.id "
            "DESC LIMIT 1) "
            "AS investigation FROM exception_cases c WHERE c.org_id=:o AND c.status='RESOLVED' "
            "AND c.resolution IN ('approved','rejected') AND c.resolved_at >= :s AND c.resolved_at < :e "
            "ORDER BY c.resolved_at, c.id"
        ),
        {"o": org_id, "s": start, "e": end},
    ).all()
    compared: list[dict[str, Any]] = []
    no_rec = 0
    for r in rows:
        inv = r.investigation or {}
        rec = inv.get("recommendation")
        if rec not in AGREES:
            no_rec += 1
            continue
        compared.append(
            {
                "case_id": r.id,
                "payment_id": r.payment_id,
                "agent": rec,
                "agent_confidence": inv.get("confidence"),
                "agent_rationale": [c.get("text", "") for c in inv.get("claims", [])][:5],
                "human": r.resolution,
                "human_rationale": r.resolution_reason,
                "resolved_by": r.resolved_by,
                "agreed": AGREES[rec] == r.resolution,
            }
        )
    agreed = sum(1 for c in compared if c["agreed"])
    bp = agreed * 10000 // len(compared) if compared else None
    return {
        "period_from": start,
        "period_to": end,
        "cases": len(rows),
        "compared": len(compared),
        "not_compared": no_rec,
        "agreed": agreed,
        "rate_bp": bp,
        "rate": f"{bp / 100:.2f}%" if bp is not None else "n/a",
        "disagreements": [c for c in compared if not c["agreed"]],
    }
