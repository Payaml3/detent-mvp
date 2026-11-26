"""Usage metering (LED-08) and daily sandbox quotas (SBX-02).

`usage_daily` holds one counter per organisation, UTC day and metric. A counter moves in the same
transaction as the work it counts, so a rolled-back decision is never counted. A month is the sum of its
days. A quota is checked and consumed in one statement: the row lock serialises concurrent requests, so an
organisation never goes past its cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from sqlalchemy import Connection, text

from detent.clock import Clock

Metric = Literal["api_calls", "payments_decided", "agent_investigations"]
METRICS: tuple[Metric, ...] = ("api_calls", "payments_decided", "agent_investigations")
QUOTA_COLUMN: dict[Metric, str] = {
    "payments_decided": "daily_payment_quota",
    "agent_investigations": "daily_investigation_quota",
}


class QuotaExceeded(Exception):
    """The organisation used today's quota for this metric. Nothing was created."""

    def __init__(self, metric: Metric, limit: int, retry_after: int) -> None:
        super().__init__(f"The daily quota of {limit} for {metric.replace('_', ' ')} is used up.")
        self.metric, self.limit, self.retry_after = metric, limit, retry_after


def seconds_to_next_day(now: datetime) -> int:
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
    return max(1, int((tomorrow - now).total_seconds()))


def quota(conn: Connection, org_id: str, metric: Metric) -> int | None:
    """Today's cap for a metric, or None when there is none (API calls, demo and test organisations)."""
    column = QUOTA_COLUMN.get(metric)
    if column is None:
        return None
    value = conn.execute(
        text(f"SELECT {column} FROM organisations WHERE org_id=:o"),  # noqa: S608 - column from a fixed map
        {"o": org_id},
    ).scalar_one_or_none()
    return None if value is None else int(value)


def count(conn: Connection, clock: Clock, org_id: str, metric: Metric, *, limit: int | None = None) -> int:
    """Add one to today's counter and return the new count. Raises QuotaExceeded at the limit."""
    now = clock.now()
    row = conn.execute(
        text(
            "INSERT INTO usage_daily (org_id, day, metric, count) VALUES (:o, :d, :m, 1) "
            "ON CONFLICT (org_id, day, metric) DO UPDATE SET count = usage_daily.count + 1 "
            "WHERE CAST(:lim AS BIGINT) IS NULL OR usage_daily.count < CAST(:lim AS BIGINT) "
            "RETURNING count"
        ),
        {"o": org_id, "d": now.date(), "m": metric, "lim": limit},
    ).one_or_none()
    if row is None:  # the conflict update's WHERE refused: the counter is at the limit
        assert limit is not None
        raise QuotaExceeded(metric, limit, seconds_to_next_day(now))
    return int(row[0])


def consume(conn: Connection, clock: Clock, org_id: str, metric: Metric) -> int:
    """Count one unit against the organisation's own quota for the metric (SBX-02)."""
    return count(conn, clock, org_id, metric, limit=quota(conn, org_id, metric))


@dataclass(frozen=True, slots=True)
class UsageLine:
    metric: Metric
    today: int
    quota: int | None
    month: int


def summary(conn: Connection, clock: Clock, org_id: str) -> list[UsageLine]:
    """DSH-08: today's counts against the quotas, and the month to date (UTC)."""
    today = clock.now().date()
    first = date(today.year, today.month, 1)
    rows = conn.execute(
        text(
            "SELECT metric, sum(count) FILTER (WHERE day = :d) AS today, sum(count) AS month "
            "FROM usage_daily WHERE org_id=:o AND day >= :f AND day <= :d GROUP BY metric"
        ),
        {"o": org_id, "d": today, "f": first},
    ).all()
    found = {r.metric: r for r in rows}
    out = []
    for m in METRICS:
        r = found.get(m)
        out.append(
            UsageLine(m, int(r.today or 0) if r else 0, quota(conn, org_id, m), int(r.month or 0) if r else 0)
        )
    return out


def monthly(conn: Connection, org_id: str, year: int, month: int) -> dict[Metric, int]:
    """LED-08: one month's counts per metric, for billing later."""
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    rows = conn.execute(
        text(
            "SELECT metric, sum(count) AS n FROM usage_daily WHERE org_id=:o AND day >= :f AND day < :n "
            "GROUP BY metric"
        ),
        {"o": org_id, "f": first, "n": nxt},
    ).all()
    found = {r.metric: int(r.n) for r in rows}
    return {m: found.get(m, 0) for m in METRICS}
