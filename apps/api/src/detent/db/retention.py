"""Retention sweeps for operational data that is not part of the audit record.

API-06: request logs are kept for 30 days. They hold metadata only and are not audit events, so
deleting old rows is allowed (audit_events and ledger entries are never deleted).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import Engine, text

from detent.clock import Clock

REQUEST_LOG_DAYS = 30


def purge_request_logs(engine: Engine, clock: Clock) -> int:
    """Delete request logs older than the retention window, for every organisation. Returns the count."""
    since = clock.now() - timedelta(days=REQUEST_LOG_DAYS)
    with engine.begin() as conn:
        res = conn.execute(
            text("DELETE FROM request_logs WHERE at < :since").execution_options(
                cross_org="retention sweep: request logs older than 30 days, every organisation"
            ),
            {"since": since},
        )
    return int(res.rowcount or 0)
