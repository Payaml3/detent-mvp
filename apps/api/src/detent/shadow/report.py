"""The shadow-phase report (SHD-02) and its HTML and PDF exports. Spec: docs/product/shadow-report.md.

Sections: summary, decision mix, agreement, unsafe approvals, unreconciled items, simulated routing saving,
and method and limits. The report reads only stored rows, so the same import and rule version always give
the same report (it is replayable; no model is called).

Agreement maps the platform's own decision to DekernAI's: approved = EXECUTE, held = ESCALATE,
rejected = BLOCK. "Unsafe approvals" (the mode-gate measure, SHD-03) are rows DekernAI would have executed
that the platform rejected. The report also lists the platform's approvals that the rules would have held or
blocked, which is what a payments lead usually wants to see first.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from detent.domain.money import Currency, Money

MATCH = {"approved": "EXECUTE", "held": "ESCALATE", "rejected": "BLOCK"}
OUTCOMES = ("EXECUTE", "ESCALATE", "BLOCK")
WORDS = {"EXECUTE": "would execute", "ESCALATE": "would escalate", "BLOCK": "would block"}


class ReportNotFound(LookupError):
    pass


def _fmt(minor: int, currency: str) -> str:
    return f"{Money(minor, Currency(currency)).to_decimal_str()} {currency}"


def load_import(conn: Connection, org_id: str, import_id: str) -> Any:
    imp = conn.execute(
        text("SELECT * FROM shadow_imports WHERE org_id=:o AND id=:i"), {"o": org_id, "i": import_id}
    ).one_or_none()
    if imp is None:
        raise ReportNotFound(import_id)
    return imp


def rows_for(
    conn: Connection, org_id: str, import_id: str, start: datetime | None = None, end: datetime | None = None
) -> list[Any]:
    sql = "SELECT * FROM shadow_rows WHERE org_id=:o AND import_id=:i"
    params: dict[str, Any] = {"o": org_id, "i": import_id}
    if start is not None:
        sql += " AND occurred_at >= :s"
        params["s"] = start
    if end is not None:
        sql += " AND occurred_at < :e"
        params["e"] = end
    return list(conn.execute(text(sql + " ORDER BY row_no"), params).all())


def agreement(rows: list[Any]) -> dict[str, Any]:
    compared = [r for r in rows if r.outcome and r.platform_decision]
    agreed = [r for r in compared if MATCH[r.platform_decision] == r.outcome]
    unsafe = [r for r in compared if r.outcome == "EXECUTE" and r.platform_decision == "rejected"]
    stopped = [
        r for r in compared if r.platform_decision == "approved" and r.outcome in ("ESCALATE", "BLOCK")
    ]
    bp = (len(agreed) * 10000 // len(compared)) if compared else None
    return {
        "compared": len(compared),
        "agreed": len(agreed),
        "rate_bp": bp,
        "rate": f"{bp / 100:.2f}%" if bp is not None else "n/a",
        "disagreements": [r for r in compared if MATCH[r.platform_decision] != r.outcome],
        "unsafe": unsafe,
        "stopped": stopped,
    }


def build(
    conn: Connection, org_id: str, import_id: str, start: datetime | None = None, end: datetime | None = None
) -> dict[str, Any]:
    imp = load_import(conn, org_id, import_id)
    rows = rows_for(conn, org_id, import_id, start, end)
    decided = [r for r in rows if r.outcome]
    mix: list[dict[str, Any]] = []
    for o in OUTCOMES:
        sel = [r for r in decided if r.outcome == o]
        amounts: dict[str, int] = defaultdict(int)
        for r in sel:
            amounts[r.currency] += int(r.amount_minor)
        top = Counter(x for r in sel for x in r.reasons).most_common(1)
        mix.append(
            {
                "outcome": o,
                "label": WORDS[o],
                "count": len(sel),
                "amounts": [_fmt(v, c) for c, v in sorted(amounts.items())],
                "top_reason": top[0][0] if top else None,
            }
        )
    agr = agreement(rows)
    unreconciled = [r for r in rows if r.problems]
    savings: dict[str, int] = defaultdict(int)
    compared_fees = 0
    for r in decided:
        if r.fee_minor is not None and r.simulated_fee_minor is not None:
            savings[r.currency] += int(r.fee_minor) - int(r.simulated_fee_minor)
            compared_fees += 1
    times = [r.occurred_at for r in rows if r.occurred_at]
    return {
        "import": imp,
        "period": (min(times), max(times)) if times else (None, None),
        "filtered": start is not None or end is not None,
        "rows_read": len(rows),
        "rows_decided": len(decided),
        "deposits": sum(1 for r in rows if r.direction == "deposit" and not r.problems),
        "mix": mix,
        "agreement": agr,
        "unreconciled": unreconciled,
        "routing": {
            "rows": compared_fees,
            "saving": [_fmt(v, c) for c, v in sorted(savings.items())],
        },
    }


def weeks(conn: Connection, org_id: str, import_id: str) -> list[str]:
    """ISO weeks (for example ``2026-W44``) that have rows, for the weekly view."""
    out = conn.execute(
        text(
            "SELECT DISTINCT to_char(occurred_at AT TIME ZONE 'UTC', 'IYYY-\"W\"IW') AS w FROM shadow_rows "
            "WHERE org_id=:o AND import_id=:i AND occurred_at IS NOT NULL ORDER BY w"
        ),
        {"o": org_id, "i": import_id},
    ).scalars()
    return [str(w) for w in out]


def week_bounds(week: str) -> tuple[datetime, datetime]:
    from datetime import UTC, timedelta

    start = datetime.strptime(week + "-1", "%G-W%V-%u").replace(tzinfo=UTC)
    return start, start + timedelta(days=7)


def as_lines(rep: dict[str, Any]) -> list[str]:
    """The report as plain lines, for the PDF export (same content and order as the HTML)."""
    imp, agr = rep["import"], rep["agreement"]
    p0, p1 = rep["period"]
    lines = [
        "# Shadow-phase report",
        f"Import {imp.id}: {imp.label}",
        f"Rule version {imp.policy_version}. Period {p0:%Y-%m-%d} to {p1:%Y-%m-%d} (UTC)."
        if p0
        else "No dated rows.",
        f"{rep['rows_read']} rows read, {rep['rows_decided']} payouts decided, {rep['deposits']} deposits, "
        f"{len(rep['unreconciled'])} rows not decided. Nothing was sent.",
        "",
        "## Decision mix",
    ]
    for m in rep["mix"]:
        amt = ", ".join(m["amounts"]) or "0"
        lines.append(
            f"- {m['label']}: {m['count']} ({amt})"
            + (f"; top reason {m['top_reason']}" if m["top_reason"] else "")
        )
    lines += ["", "## Agreement with your decisions"]
    if agr["compared"]:
        lines.append(f"{agr['agreed']} of {agr['compared']} matched ({agr['rate']}).")
        for r in agr["disagreements"][:200]:
            lines.append(
                f"- {r.platform_ref}: you {r.platform_decision}, "
                f"DekernAI {WORDS[r.outcome]} {', '.join(r.reasons)}"
            )
    else:
        lines.append("The export has no decisions of your own, so agreement can't be measured.")
    lines += ["", "## Unsafe approvals (DekernAI would execute, you rejected)"]
    lines += [f"- {r.platform_ref}: {_fmt(r.amount_minor, r.currency)}" for r in agr["unsafe"]] or ["None."]
    lines += ["", "## Your approvals the rules would stop"]
    lines += [f"- {r.platform_ref}: {WORDS[r.outcome]} ({', '.join(r.reasons)})" for r in agr["stopped"]] or [
        "None."
    ]
    lines += ["", "## Unreconciled items"]
    lines += [
        f"- row {r.row_no} {r.platform_ref or ''}: {', '.join(r.problems)}" for r in rep["unreconciled"]
    ] or ["None."]
    lines += ["", "## Simulated routing saving"]
    if rep["routing"]["rows"]:
        lines.append(
            f"Simulation over {rep['routing']['rows']} payouts with a fee: "
            f"{', '.join(rep['routing']['saving'])} "
            "(fee paid minus the lowest estimated fee among your connected rails in the same currency)."
        )
    else:
        lines.append("Not shown: the export has no fee column, or no connected rail matches.")
    lines += ["", "## Method and limits", *METHOD]
    return lines


METHOD = [
    "Decided in memory with the rule version named above. Nothing was sent: no payment was created and no "
    "rail was touched.",
    "Names, addresses and account numbers were hashed with a per-import salt on import and never stored.",
    "Checks that need registry data use DekernAI's registry: a counterparty reference that is not a "
    "registry ID "
    "is treated as unregistered (unknown KYB, not allowlisted).",
    "Daily caps are counted per UTC day inside the import, from the payouts that would have executed.",
    "Prototype: the screening list is a mock and the routing saving is a simulation.",
]
