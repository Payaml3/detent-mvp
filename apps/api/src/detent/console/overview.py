"""The overview numbers (CON-02): today's decisions, automation share, UNKNOWN age, cases, rails, events.

Read-only queries, all scoped to one organisation. The match rate needs reconciliation (slice S7), so
until then it is reported as not available rather than as a number.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from detent.exceptions.deadlines import approved_by_timeout
from detent.execution.modes import current_mode, orchestrate_status, pending_mode_change


def _age(seconds: int) -> str:
    h, m = seconds // 3600, (seconds % 3600) // 60
    return f"{h}h {m}m" if h else f"{m}m {seconds % 60}s"


def overview_stats(conn: Connection, org_id: str, now: datetime) -> dict[str, Any]:
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    p = {"o": org_id, "d": day, "now": now}
    by_outcome: dict[str, int] = dict(
        conn.execute(
            text(
                "SELECT outcome, count(*) FROM (SELECT DISTINCT ON (payment_id) payment_id, outcome "
                "FROM decisions "
                "WHERE org_id=:o AND decided_at >= :d ORDER BY payment_id, decided_at, id) first_decisions "
                "GROUP BY outcome"
            ),
            p,
        ).all()
    )
    by_status: dict[str, int] = dict(
        conn.execute(
            text(
                "SELECT status, count(*) FROM payment_intents WHERE org_id=:o AND created_at >= :d "
                "GROUP BY status "
                "ORDER BY status"
            ),
            p,
        ).all()
    )
    decided, with_case = conn.execute(
        text(
            "SELECT count(*), count(*) FILTER (WHERE EXISTS (SELECT 1 FROM exception_cases c WHERE "
            "c.org_id = "
            "p.org_id AND c.payment_id = p.id)) FROM payment_intents p WHERE p.org_id=:o AND "
            "p.created_at >= :d "
            "AND EXISTS (SELECT 1 FROM decisions d WHERE d.org_id = p.org_id AND d.payment_id = p.id)"
        ),
        p,
    ).one()
    oldest_unknown = conn.execute(
        text("SELECT min(unknown_at) FROM attempts WHERE org_id=:o AND status='UNKNOWN'"), p
    ).scalar_one()
    unknown_count = conn.execute(
        text("SELECT count(*) FROM payment_intents WHERE org_id=:o AND status='UNKNOWN'"), p
    ).scalar_one()
    cases = conn.execute(
        text(
            "SELECT count(*) FILTER (WHERE status IN ('OPEN','HELD_OVERDUE')), "
            "count(*) FILTER (WHERE status = 'HELD_OVERDUE' OR (status = 'OPEN' AND deadline_at < :now)) "
            "FROM exception_cases WHERE org_id=:o"
        ),
        p,
    ).one()
    rails = [
        dict(r._mapping)
        for r in conn.execute(
            text(
                "SELECT r.id, r.network, r.currency, r.enabled, "
                "count(a.id) FILTER (WHERE a.created_at >= :d) AS attempts_today, "
                "count(a.id) FILTER (WHERE a.created_at >= :d AND a.status = 'FAILED') AS failed_today, "
                "count(a.id) FILTER (WHERE a.status = 'UNKNOWN') AS unknown_now "
                "FROM rails r LEFT JOIN attempts a ON a.org_id = r.org_id AND a.rail_id = r.id "
                "WHERE r.org_id=:o GROUP BY r.id, r.network, r.currency, r.enabled ORDER BY r.id"
            ),
            p,
        )
    ]
    for r in rails:
        r["health"] = (
            "disabled"
            if not r["enabled"]
            else "attention"
            if r["unknown_now"] or (r["attempts_today"] and r["failed_today"] * 2 >= r["attempts_today"])
            else "ok"
        )
    events = [
        dict(r._mapping)
        for r in conn.execute(
            text(
                "SELECT at, actor, kind, subject_id FROM audit_events WHERE org_id=:o ORDER BY seq "
                "DESC LIMIT 10"
            ),
            p,
        )
    ]
    # Integer percent: the share of today's decided payments that needed no person.
    auto_pct = None if not decided else (100 * (decided - with_case)) // decided
    return {
        "by_outcome": {k: by_outcome.get(k, 0) for k in ("EXECUTE", "ESCALATE", "BLOCK")},
        "by_status": by_status,
        "decided_today": int(decided),
        "auto_pct": auto_pct,
        "unknown_count": int(unknown_count),
        "oldest_unknown": _age(int((now - oldest_unknown).total_seconds())) if oldest_unknown else None,
        "open_cases": int(cases[0]),
        "overdue_cases": int(cases[1]),
        "approved_by_timeout": approved_by_timeout(conn, org_id),
        "match_rate": None,  # reconciliation arrives in slice S7
        "rails": rails,
        "orchestrate": orchestrate_status(conn, org_id),
        "mode": current_mode(conn, org_id),
        "pending_mode_change": pending_mode_change(conn, org_id),
        "events": events,
    }
