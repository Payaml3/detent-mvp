"""Bank statement import (LED-07).

Pulls one day's statement from the simulated bank rail (JSON or CSV) and stores each line once in
``rail_records`` (source ``statement``). Importing the same rail and date again is a no-op: the first
import is recorded in ``bank_statements`` and its lines are unique per (rail, external ID).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction


@dataclass(frozen=True, slots=True)
class StatementLine:
    external_id: str
    direction: str
    amount_minor: int
    currency: str
    party: str
    reference: str


@dataclass(frozen=True, slots=True)
class Imported:
    rail_id: str
    statement_date: date
    lines: int
    new: bool


def parse_json(doc: dict[str, Any]) -> list[StatementLine]:
    out = [
        StatementLine(
            str(p["key"]),
            "out",
            int(p["amount_minor"]),
            str(p["currency"]),
            str(p["account"]),
            str(p.get("reference") or ""),
        )
        for p in doc.get("payments", [])
    ]
    out += [
        StatementLine(
            str(i["id"]),
            "in",
            int(i["amount_minor"]),
            str(i["currency"]),
            str(i["payer"]),
            str(i.get("reference") or ""),
        )
        for i in doc.get("inbound", [])
    ]
    return out


def parse_csv(body: str) -> list[StatementLine]:
    out = []
    for row in csv.DictReader(io.StringIO(body)):
        if row["direction"] not in ("in", "out"):
            raise ValueError(f"statement line {row['line_id']}: direction {row['direction']!r}")
        out.append(
            StatementLine(
                row["line_id"],
                row["direction"],
                int(row["amount_minor"]),
                row["currency"],
                row["party"],
                row["reference"],
            )
        )
    return out


def import_statement(
    engine: Engine, clock: Clock, *, org_id: str, rail_id: str, adapter: Any, day: date, fmt: str = "json"
) -> Imported:
    with engine.connect() as conn:
        done = conn.execute(
            text("SELECT lines FROM bank_statements WHERE org_id=:o AND rail_id=:r AND statement_date=:d"),
            {"o": org_id, "r": rail_id, "d": day},
        ).scalar_one_or_none()
    if done is not None:
        return Imported(rail_id, day, int(done), False)
    raw = adapter.statement(day.isoformat(), fmt)
    lines = parse_csv(raw) if fmt == "csv" else parse_json(raw)
    with transaction(engine) as conn:
        claimed = conn.execute(
            text(
                "INSERT INTO bank_statements (org_id, rail_id, statement_date, format, lines, imported_at) "
                "VALUES (:o, :r, :d, :f, :n, :t) ON CONFLICT DO NOTHING RETURNING lines"
            ),
            {"o": org_id, "r": rail_id, "d": day, "f": fmt, "n": len(lines), "t": clock.now()},
        ).scalar_one_or_none()
        if claimed is None:  # another import of the same date won the race
            return Imported(rail_id, day, len(lines), False)
        for ln in lines:
            conn.execute(
                text(
                    "INSERT INTO rail_records (id, org_id, rail_id, external_id, direction, "
                    "amount_minor, currency, "
                    "party, reference, source, occurred_at, statement_date) VALUES (:id, :o, :r, :e, "
                    ":dir, :a, :c, :p, "
                    ":ref, 'statement', :t, :d) ON CONFLICT (org_id, rail_id, external_id) DO NOTHING"
                ),
                {
                    "id": f"rr_{rail_id}_{ln.external_id}"[:200],
                    "o": org_id,
                    "r": rail_id,
                    "e": ln.external_id,
                    "dir": ln.direction,
                    "a": ln.amount_minor,
                    "c": ln.currency,
                    "p": ln.party,
                    "ref": ln.reference or None,
                    "t": clock.now(),
                    "d": day,
                },
            )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=Actor.system("statements"),
            kind="statement.imported",
            subject_id=f"{rail_id}:{day.isoformat()}",
            payload={"lines": len(lines), "format": fmt},
        )
    return Imported(rail_id, day, len(lines), True)
