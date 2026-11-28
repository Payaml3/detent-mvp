"""Rail health and the circuit breaker (RAL-08, spec/06 Routing).

- Health per rail: the rolling success rate and p95 latency over its last ``HISTORY`` resolved attempts.
  Latency is from the attempt's creation to its confirmation. Balance and pre-funded limit usage come from the
  adapter and the counters (CON-08).
- The circuit opens when the rail's newest attempts since the circuit last changed are ``circuit_failures``
  technical failures in a row (``TECHNICAL_RETRYABLE``, ``TECHNICAL_FINAL`` or ``TIMEOUT``). A rejection by
  the rail is a business answer and does not count. Routing reads the same rule, so a rail leaves routing at
  once, before the worker records the change.
- An open circuit is probed with the adapter's ``health()`` at most every ``rail_probe_seconds``. A successful
  probe closes it; the failure count then starts again from the close.
- Opening and closing are audited (``rail.circuit_opened``, ``rail.circuit_closed``). A circuit only ever
  removes a rail from routing: it never sends, retries or re-routes anything itself.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.rails.base import RailAdapter

HISTORY = 50
TECHNICAL = ("TECHNICAL_RETRYABLE", "TECHNICAL_FINAL", "TIMEOUT")
SYSTEM = Actor("system:rail_health", None)
log = logging.getLogger("detent.rails.health")


def consecutive_failures(conn: Connection, org_id: str, rail: Any) -> int:
    """Technical failures in a row among the rail's newest finished attempts since the circuit last
    changed."""
    rows = conn.execute(
        text(
            "SELECT failure_class FROM attempts WHERE org_id=:o AND rail_id=:r "
            "AND status IN ('CONFIRMED','FAILED','UNKNOWN') "
            "AND (CAST(:since AS timestamptz) IS NULL OR created_at > CAST(:since AS timestamptz)) "
            "ORDER BY created_at DESC, id DESC LIMIT :n"
        ),
        {"o": org_id, "r": rail.id, "since": rail.circuit_changed_at, "n": int(rail.circuit_failures)},
    ).scalars()
    n = 0
    for fc in rows:
        if fc not in TECHNICAL:
            break
        n += 1
    return n


def is_open(conn: Connection, org_id: str, rail: Any) -> bool:
    """Routing's check: the stored state, or the failure count reached and not yet recorded by the worker."""
    if rail.circuit_state == "open":
        return True
    return consecutive_failures(conn, org_id, rail) >= int(rail.circuit_failures)


def stats(conn: Connection, org_id: str, rail_id: str) -> dict[str, Any]:
    """Rolling success rate and p95 latency over the last ``HISTORY`` resolved attempts."""
    rows = conn.execute(
        text(
            "SELECT status, EXTRACT(EPOCH FROM (resolved_at - created_at)) AS secs FROM attempts "
            "WHERE org_id=:o AND rail_id=:r AND status IN ('CONFIRMED','FAILED') "
            "ORDER BY created_at DESC, id DESC LIMIT :n"
        ),
        {"o": org_id, "r": rail_id, "n": HISTORY},
    ).all()
    ok = [r for r in rows if r.status == "CONFIRMED"]
    secs = sorted(Decimal(str(r.secs)) for r in ok if r.secs is not None)
    p95 = None
    if secs:
        rank = max(1, -(-95 * len(secs) // 100))  # nearest rank: ceil(0.95 * n)
        p95 = secs[rank - 1].quantize(Decimal("0.1"))
    rate_bp = len(ok) * 10000 // len(rows) if rows else None
    return {
        "attempts": len(rows),
        "success_rate_bp": rate_bp,
        "success_rate": f"{rate_bp / 100:.1f}%" if rate_bp is not None else "no attempts yet",
        "p95_seconds": p95,
    }


def _set(conn: Connection, org_id: str, rail_id: str, **cols: Any) -> None:
    conn.execute(
        text(
            "UPDATE rails SET circuit_state=coalesce(:state, circuit_state), "
            "circuit_changed_at=coalesce(:changed, circuit_changed_at), "
            "circuit_probe_at=coalesce(:probe_at, circuit_probe_at), "
            "circuit_probe_ok=coalesce(:probe_ok, circuit_probe_ok) WHERE org_id=:o AND id=:r"
        ),
        {
            "o": org_id,
            "r": rail_id,
            "state": cols.get("state"),
            "changed": cols.get("changed"),
            "probe_at": cols.get("probe_at"),
            "probe_ok": cols.get("probe_ok"),
        },
    )


def check_rail(
    engine: Engine,
    clock: Clock,
    org_id: str,
    rail_id: str,
    adapter: RailAdapter | None,
    *,
    probe_seconds: float,
) -> str:
    """Opens, probes or closes one rail's circuit. Returns the state after the check."""
    with transaction(engine) as conn:
        rail = conn.execute(
            text("SELECT * FROM rails WHERE org_id=:o AND id=:r FOR UPDATE"), {"o": org_id, "r": rail_id}
        ).one()
        now = clock.now()
        if rail.circuit_state == "closed":
            failures = consecutive_failures(conn, org_id, rail)
            if failures < int(rail.circuit_failures):
                return "closed"
            _set(conn, org_id, rail_id, state="open", changed=now)
            append(
                conn,
                clock,
                org_id=org_id,
                actor=SYSTEM,
                kind="rail.circuit_opened",
                subject_id=rail_id,
                payload={"failures_in_a_row": failures, "threshold": int(rail.circuit_failures)},
            )
            log.warning("rail circuit opened", extra={"org_id": org_id, "rail": rail_id})
            return "open"
        due = rail.circuit_probe_at is None or now - rail.circuit_probe_at >= timedelta(seconds=probe_seconds)
        if not due:
            return "open"
        ok = False
        detail: dict[str, Any] = {"error": "no adapter configured"}
        if adapter is not None:
            try:
                h = adapter.health()
                ok, detail = bool(h.ok), dict(h.detail)
            except Exception as exc:  # a failing probe keeps the circuit open (fail closed)
                ok, detail = False, {"error": type(exc).__name__}
        if not ok:
            _set(conn, org_id, rail_id, probe_at=now, probe_ok=False)
            return "open"
        _set(conn, org_id, rail_id, state="closed", changed=now, probe_at=now, probe_ok=True)
        append(
            conn,
            clock,
            org_id=org_id,
            actor=SYSTEM,
            kind="rail.circuit_closed",
            subject_id=rail_id,
            payload={"probe": {k: str(v) for k, v in detail.items()}},
        )
        return "closed"


def check_org(
    engine: Engine, clock: Clock, org_id: str, adapters: Mapping[str, RailAdapter], *, probe_seconds: float
) -> dict[str, str]:
    with engine.connect() as conn:
        ids = [
            str(r)
            for r in conn.execute(
                text("SELECT id FROM rails WHERE org_id=:o AND enabled ORDER BY id"), {"o": org_id}
            ).scalars()
        ]
    return {
        r: check_rail(engine, clock, org_id, r, adapters.get(r), probe_seconds=probe_seconds) for r in ids
    }


def check_all(engine: Engine, clock: Clock, settings: Any) -> dict[str, dict[str, str]]:
    """Worker schedule: every organisation with an enabled rail."""
    from detent.rails.registry import build_adapters

    with engine.connect() as conn:
        orgs = [
            str(o)
            for o in conn.execute(
                text("SELECT DISTINCT org_id FROM rails WHERE enabled ORDER BY org_id").execution_options(
                    cross_org="the rail health check covers every organisation's rails"
                )
            ).scalars()
        ]
    out: dict[str, dict[str, str]] = {}
    for org in orgs:
        try:
            adapters = build_adapters(settings, engine, org, clock=clock)
        except Exception:
            log.exception("rail adapters could not be built", extra={"org_id": org})
            adapters = {}
        try:
            out[org] = check_org(engine, clock, org, adapters, probe_seconds=settings.rail_probe_seconds)
        except Exception:
            log.exception("rail health check failed", extra={"org_id": org})
    return out
