"""A reconciliation run (LED-06).

Every money movement in the ledger must match the rail's own record, and every rail record must be in
the ledger:

- a settled payout matches an outgoing chain transfer (its transaction hash) or a bank statement line
  (its idempotency key), for the same amount;
- a credited deposit matches its incoming chain transfer or bank statement line;
- money held in suspense is a break until an approved fix moves it;
- a rail record that matches nothing in the ledger is a break.

An item whose evidence is not in yet (the bank statement for that day has not been imported, or the
chain watcher has not scanned past it) is pending and not counted. The match rate is matched items
over counted items, in basis points (integers, no floats).

Each new break gets a fix proposed by the reconciliation agent and an exception case (a deposit break
joins the deposit's existing case). Nothing is changed until a person approves the fix (``fixes``).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.agents.llm import LLMClient
from detent.agents.reconciliation import propose_fix
from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.domain.ids import Prefix, new_id
from detent.exceptions.cases import open_deposit_case
from detent.policy.store import active_policy

LLMFactory = Callable[[Mapping[str, str]], LLMClient]


@dataclass
class Break:
    kind: str
    subject_key: str
    evidence_id: str
    record: dict[str, Any]
    inbound_id: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RunResult:
    run_id: str
    counted: int
    matched: int
    pending: int
    breaks: list[str]

    @property
    def match_rate_bps(self) -> int:
        return 10_000 if not self.counted else (10_000 * self.matched) // self.counted

    def rate_text(self) -> str:
        return f"{self.match_rate_bps // 100}.{self.match_rate_bps % 100:02d}%"


def _applied(conn: Connection, org_id: str, key: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM recon_breaks WHERE org_id=:o AND subject_key=:k AND status='APPLIED' LIMIT 1"
            ),
            {"o": org_id, "k": key},
        ).first()
    )


def _jsonable(row: Any) -> dict[str, Any]:
    out = {}
    for k, v in row._mapping.items():
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    return out


def _gather(conn: Connection, org_id: str) -> tuple[int, int, int, list[Break]]:  # noqa: PLR0912, PLR0915 - one block per item kind
    counted = matched = pending = 0
    breaks: list[Break] = []
    used: set[str] = set()  # rail_records matched to the ledger

    # --- settled payouts
    for p in conn.execute(
        text(
            "SELECT j.payment_id, j.created_at, p.amount_minor, p.currency, a.rail_id, a.tx_hash, "
            "a.idempotency_key, "
            "r.kind FROM journal_entries j JOIN payment_intents p ON p.org_id=j.org_id AND p.id=j.payment_id "
            "JOIN attempts a ON a.org_id=p.org_id AND a.payment_id=p.id AND a.status='CONFIRMED' "
            "JOIN rails r ON r.org_id=a.org_id AND r.id=a.rail_id WHERE j.org_id=:o AND "
            "j.kind='payout.settle'"
        ),
        {"o": org_id},
    ):
        if p.kind == "evm":
            ready = conn.execute(
                text("SELECT 1 FROM watch_cursors WHERE org_id=:o AND rail_id=:r AND updated_at >= :t"),
                {"o": org_id, "r": p.rail_id, "t": p.created_at},
            ).first()
            rec = conn.execute(
                text(
                    "SELECT id, amount_minor FROM rail_records WHERE org_id=:o AND rail_id=:r AND "
                    "direction='out' "
                    "AND lower(external_id) LIKE lower(:h) || ':%' LIMIT 1"
                ),
                {"o": org_id, "r": p.rail_id, "h": p.tx_hash or "-"},
            ).one_or_none()
        else:
            ready = conn.execute(
                text("SELECT 1 FROM bank_statements WHERE org_id=:o AND rail_id=:r AND imported_at >= :t"),
                {"o": org_id, "r": p.rail_id, "t": p.created_at},
            ).first()
            rec = conn.execute(
                text(
                    "SELECT id, amount_minor FROM rail_records WHERE org_id=:o AND rail_id=:r AND "
                    "direction='out' "
                    "AND external_id=:k"
                ),
                {"o": org_id, "r": p.rail_id, "k": p.idempotency_key},
            ).one_or_none()
        if rec is not None:
            used.add(rec.id)
        if rec is None and not ready:
            pending += 1
            continue
        counted += 1
        if rec is not None and int(rec.amount_minor) == int(p.amount_minor):
            matched += 1
            continue
        key = f"payout:{p.payment_id}"
        if _applied(conn, org_id, key):
            matched += 1
            continue
        kind = "payout_missing_on_rail" if rec is None else "amount_mismatch"
        breaks.append(
            Break(
                kind,
                key,
                f"ev_pay_{p.payment_id}",
                {
                    "payment_id": p.payment_id,
                    "rail_id": p.rail_id,
                    "amount_minor": int(p.amount_minor),
                    "currency": p.currency,
                    "rail_amount_minor": int(rec.amount_minor) if rec else None,
                },
            )
        )

    # --- inbound transfers (credited, or held in suspense)
    for i in conn.execute(
        text(
            "SELECT t.*, r.kind AS rail_kind FROM inbound_transfers t JOIN rails r ON "
            "r.org_id=t.org_id AND r.id=t.rail_id "
            "WHERE t.org_id=:o AND t.decided_at IS NOT NULL"
        ),
        {"o": org_id},
    ):
        ext = f"{i.tx_hash}:{i.log_index}" if i.rail_kind == "evm" else i.tx_hash
        rec = conn.execute(
            text(
                "SELECT id, amount_minor FROM rail_records WHERE org_id=:o AND rail_id=:r AND "
                "direction='in' AND lower(external_id)=lower(:e)"
            ),
            {"o": org_id, "r": i.rail_id, "e": ext},
        ).one_or_none()
        if rec is not None:
            used.add(rec.id)
        if i.status == "SUSPENSE":
            counted += 1
            key = f"suspense:{i.id}"
            if _applied(conn, org_id, key):
                matched += 1
                continue
            breaks.append(Break("unallocated_inbound", key, f"ev_inb_{i.id}", _jsonable(i), inbound_id=i.id))
            continue
        has_evidence = bool(
            rec is not None
            or i.rail_kind == "evm"
            or conn.execute(
                text("SELECT 1 FROM bank_statements WHERE org_id=:o AND rail_id=:r AND imported_at >= :t"),
                {"o": org_id, "r": i.rail_id, "t": i.decided_at},
            ).first()
        )
        if not has_evidence:
            pending += 1
            continue
        counted += 1
        if rec is not None and int(rec.amount_minor) == int(i.amount_minor):
            matched += 1
            continue
        key = f"deposit:{i.id}"
        if _applied(conn, org_id, key):
            matched += 1
            continue
        breaks.append(
            Break(
                "deposit_missing_on_rail" if rec is None else "amount_mismatch",
                key,
                f"ev_inb_{i.id}",
                _jsonable(i),
                inbound_id=i.id,
            )
        )

    # --- rail records nothing in the ledger accounts for
    for r in conn.execute(
        text("SELECT * FROM rail_records WHERE org_id=:o ORDER BY occurred_at, id"), {"o": org_id}
    ):
        if r.id in used:
            continue
        if r.direction == "out":
            known = conn.execute(
                text(
                    "SELECT 1 FROM attempts WHERE org_id=:o AND rail_id=:r AND (idempotency_key=:e OR "
                    "lower(:e) LIKE lower(tx_hash) || ':%') LIMIT 1"
                ),
                {"o": org_id, "r": r.rail_id, "e": r.external_id},
            ).first()
        else:
            known = conn.execute(
                text(
                    "SELECT 1 FROM inbound_transfers WHERE org_id=:o AND rail_id=:r AND decided_at "
                    "IS NULL AND "
                    "(tx_hash=:e OR lower(:e) = lower(tx_hash) || ':' || log_index) LIMIT 1"
                ),
                {"o": org_id, "r": r.rail_id, "e": r.external_id},
            ).first()
        if known:  # booked moments from now (a payout not yet settled, a deposit not yet decided)
            pending += 1
            continue
        counted += 1
        key = f"record:{r.rail_id}:{r.external_id}"
        if _applied(conn, org_id, key):
            matched += 1
            continue
        breaks.append(Break("rail_record_unbooked", key, f"ev_rec_{r.id}", _jsonable(r)))
    return counted, matched, pending, breaks


def _candidates(conn: Connection, org_id: str, b: Break) -> list[dict[str, Any]]:
    if b.kind == "unallocated_inbound":
        tol = int(
            conn.execute(
                text("SELECT deposit_tolerance_minor FROM organisations WHERE org_id=:o"), {"o": org_id}
            ).scalar_one()
        )
        rows = conn.execute(
            text(
                "SELECT id, account_ref, currency, network, expected_amount_minor, status FROM "
                "deposit_intents "
                "WHERE org_id=:o AND status='OPEN' AND currency=:c AND expected_amount_minor IS NOT NULL "
                "AND abs(expected_amount_minor - :a) <= :t AND id IS DISTINCT FROM :own ORDER BY "
                "created_at, id LIMIT 5"
            ),
            {
                "o": org_id,
                "c": b.record["currency"],
                "a": int(b.record["amount_minor"]),
                "t": tol,
                "own": b.record.get("deposit_intent_id"),
            },
        ).all()
    elif b.kind == "rail_record_unbooked" and b.record.get("direction") == "in" and b.record.get("reference"):
        rows = conn.execute(
            text(
                "SELECT id, account_ref, currency, network, expected_amount_minor, status FROM "
                "deposit_intents "
                "WHERE org_id=:o AND reference=:r"
            ),
            {"o": org_id, "r": b.record["reference"]},
        ).all()
    else:
        rows = []
    return [
        {
            "evidence_id": f"ev_dep_{r.id}",
            "deposit_intent_id": r.id,
            "account_ref": r.account_ref,
            "currency": r.currency,
            "network": r.network,
            "expected_amount_minor": None
            if r.expected_amount_minor is None
            else int(r.expected_amount_minor),
            "status": r.status,
        }
        for r in rows
    ]


def run_reconciliation(
    engine: Engine, clock: Clock, *, org_id: str, llm_factory: LLMFactory, model: str, daily_token_budget: int
) -> RunResult:
    now = clock.now()
    run_id = new_id(Prefix.REC, now)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO recon_runs (id, org_id, started_at) VALUES (:i, :o, :t)"),
            {"i": run_id, "o": org_id, "t": now},
        )
        counted, matched, pending, found = _gather(conn, org_id)
    ids: list[str] = []
    for b in found:
        with engine.begin() as conn:
            existing = conn.execute(
                text(
                    "SELECT id FROM recon_breaks WHERE org_id=:o AND subject_key=:k AND status IN "
                    "('OPEN','APPROVED')"
                ),
                {"o": org_id, "k": b.subject_key},
            ).scalar_one_or_none()
            if existing:
                ids.append(str(existing))
                continue
            b.candidates = _candidates(conn, org_id, b)
            brk = new_id(Prefix.BRK, clock.now())
            rules = active_policy(conn, org_id).rules
            case_id = open_deposit_case(
                conn,
                clock,
                org_id=org_id,
                inbound_id=b.inbound_id or b.subject_key,
                reasons=[b.kind.upper()],
                rules=rules,
                case_type="deposit" if b.inbound_id else "reconciliation",
            )
            conn.execute(
                text(
                    "INSERT INTO recon_breaks (id, org_id, run_id, subject, status, created_at, "
                    "kind, subject_key, case_id) "
                    "VALUES (:i, :o, :r, CAST(:s AS jsonb), 'OPEN', :t, :k, :sk, :c)"
                ),
                {
                    "i": brk,
                    "o": org_id,
                    "r": run_id,
                    "s": json.dumps(b.record, default=str),
                    "t": clock.now(),
                    "k": b.kind,
                    "sk": b.subject_key,
                    "c": case_id,
                },
            )
            append(
                conn,
                clock,
                org_id=org_id,
                actor=Actor.system("reconciliation"),
                kind="reconciliation.break",
                subject_id=brk,
                payload={"kind": b.kind, "subject_key": b.subject_key, "case_id": case_id},
            )
        evidence = {b.evidence_id: {"type": b.kind, **b.record}} | {c["evidence_id"]: c for c in b.candidates}
        top = b.candidates[0] if b.candidates else {}
        placeholders = {
            "BREAK_EVIDENCE": b.evidence_id,
            "TOP_INTENT": str(top.get("deposit_intent_id", "")),
            "TOP_EVIDENCE": str(top.get("evidence_id", "")),
            "TOP_ACCOUNT": str(top.get("account_ref", "")),
        }
        prop = propose_fix(
            engine,
            clock,
            org_id=org_id,
            break_id=brk,
            break_type=b.kind,
            evidence=json.loads(json.dumps(evidence, default=str)),
            candidates=b.candidates,
            llm=llm_factory(placeholders),
            model=model,
            daily_token_budget=daily_token_budget,
        )
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE recon_breaks SET proposed_fix=CAST(:f AS jsonb), rationale=CAST(:r AS "
                    "jsonb), agent_call_id=:a "
                    "WHERE org_id=:o AND id=:i"
                ),
                {
                    "f": json.dumps(prop["fix"]),
                    "r": json.dumps(
                        {
                            "claims": prop["rationale"],
                            "confidence": prop["confidence"],
                            "flags": prop["flags"],
                            "source": prop["source"],
                        }
                    ),
                    "a": prop["agent_call_id"],
                    "o": org_id,
                    "i": brk,
                },
            )
        ids.append(brk)
    result = RunResult(run_id, counted, matched, pending, ids)
    with engine.begin() as conn:
        stats = {
            "counted": counted,
            "matched": matched,
            "pending": pending,
            "breaks": len(ids),
            "match_rate_bps": result.match_rate_bps,
        }
        conn.execute(
            text("UPDATE recon_runs SET finished_at=:t, stats=CAST(:s AS jsonb) WHERE org_id=:o AND id=:i"),
            {"t": clock.now(), "s": json.dumps(stats), "o": org_id, "i": run_id},
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=Actor.system("reconciliation"),
            kind="reconciliation.run",
            subject_id=run_id,
            payload=stats,
        )
    return result


def product_llm_factory(settings: Any) -> LLMFactory:
    """The model when an API key is configured, otherwise the labelled stand-in recordings."""
    from detent.agents.llm import llm_for

    return lambda ph: llm_for(settings, ph, kind="reconciliation")[0]


def run_for(engine: Engine, clock: Clock, settings: Any, org_id: str) -> RunResult:
    return run_reconciliation(
        engine,
        clock,
        org_id=org_id,
        llm_factory=product_llm_factory(settings),
        model=settings.model_agent,
        daily_token_budget=settings.ai_daily_token_budget,
    )


def run_all(engine: Engine, clock: Clock, settings: Any) -> dict[str, str]:
    """Worker schedule: every organisation with ledger entries is reconciled."""
    import logging

    with engine.connect() as conn:
        orgs = [
            str(o)
            for o in conn.execute(
                text("SELECT DISTINCT org_id FROM journal_entries").execution_options(
                    cross_org="scheduled reconciliation covers every organisation with a ledger"
                )
            ).scalars()
        ]
    out = {}
    for org in orgs:
        try:
            out[org] = run_for(engine, clock, settings, org).rate_text()
        except Exception:
            logging.getLogger("detent.reconciliation").exception(
                "reconciliation failed", extra={"org_id": org}
            )
    return out


def latest_runs(conn: Connection, org_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, started_at, finished_at, stats FROM recon_runs WHERE org_id=:o AND "
            "generation = (SELECT data_generation FROM organisations WHERE org_id = :o) ORDER BY "
            "started_at DESC, id DESC LIMIT :n"
        ),
        {"o": org_id, "n": limit},
    ).all()
    return [
        {
            "id": r.id,
            "started_at": r.started_at.isoformat().replace("+00:00", "Z"),
            "finished_at": r.finished_at.isoformat().replace("+00:00", "Z") if r.finished_at else None,
            **dict(r.stats or {}),
        }
        for r in rows
    ]


def list_breaks(conn: Connection, org_id: str, status: str | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, run_id, kind, subject_key, subject, proposed_fix, rationale, status, "
            "case_id, approved_by, "
            "decision_reason, applied_journal_id, created_at, decided_at FROM recon_breaks WHERE org_id=:o "
            "AND generation = (SELECT data_generation FROM organisations WHERE org_id = :o) "
            "AND (CAST(:s AS text) IS NULL OR status=:s) ORDER BY created_at DESC, id DESC"
        ),
        {"o": org_id, "s": status},
    ).all()
    out = []
    for r in rows:
        d = dict(r._mapping)
        for k in ("created_at", "decided_at"):
            d[k] = d[k].isoformat().replace("+00:00", "Z") if d[k] else None
        out.append(d)
    return out
