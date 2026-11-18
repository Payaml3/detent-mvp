"""Postgres job queue (FND-06).

Exactly-once database effects per job:

1. **Claim.** A short transaction picks one due job with ``FOR UPDATE SKIP LOCKED`` and leases it
   (``locked_by``, ``locked_until``). Two workers never claim the same job at once.
2. **Run.** The handler runs inside one transaction. In that same transaction the runner marks the
   job done, but only ``WHERE locked_by = me`` (a fencing check). If the worker dies mid-job, the
   transaction rolls back, nothing the handler wrote survives, and the lease expires so another
   worker reruns it. If the lease was taken over meanwhile, the fencing check fails and this
   worker's effects roll back.
3. **Fail.** An exception rolls back the handler's writes; the job is rescheduled with backoff, and
   marked dead after ``max_attempts``.

Handlers that talk to the outside world (rails, webhooks) must use idempotency keys so a rerun can't
cause a second external effect; the execution layer's UNKNOWN logic (M3) builds on this.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, text, update

from detent.clock import Clock
from detent.db.tables import jobs
from detent.domain.ids import Prefix, new_id

CLAIM_SQL = text(
    """
    UPDATE jobs SET locked_by = :worker, locked_until = :until, attempts = attempts + 1
    WHERE id = (
        SELECT id FROM jobs
        WHERE done_at IS NULL AND dead_at IS NULL AND run_at <= :now
          AND (locked_until IS NULL OR locked_until < :now)
        ORDER BY run_at, id
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, org_id, kind, payment_id, payload, attempts, max_attempts, run_at
    """
)


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    org_id: str
    kind: str
    payment_id: str | None
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    run_at: datetime


class LeaseLost(RuntimeError):
    """Another worker took over the job; this run's effects are rolled back."""


def enqueue(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    kind: str,
    payload: dict[str, Any] | None = None,
    run_at: datetime | None = None,
    dedupe_key: str | None = None,
    payment_id: str | None = None,
    max_attempts: int = 8,
) -> str | None:
    """Add a job. Returns its ID, or None when a job with the same dedupe key already exists."""
    now = clock.now()
    job_id = new_id(Prefix.JOB, now)
    row = conn.execute(
        text(
            """
            INSERT INTO jobs (id, org_id, kind, dedupe_key, payment_id, payload, run_at, max_attempts,
                              created_at)
            VALUES (:id, :org_id, :kind, :dedupe_key, :payment_id, CAST(:payload AS jsonb), :run_at,
                    :max_attempts, :now)
            ON CONFLICT (org_id, kind, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
            RETURNING id
            """
        ),
        {
            "id": job_id,
            "org_id": org_id,
            "kind": kind,
            "dedupe_key": dedupe_key,
            "payment_id": payment_id,
            "payload": _json(payload or {}),
            "run_at": run_at or now,
            "max_attempts": max_attempts,
            "now": now,
        },
    ).scalar_one_or_none()
    return str(row) if row else None


def claim(engine: Engine, clock: Clock, worker_id: str, lease: timedelta) -> Job | None:
    now = clock.now()
    with engine.begin() as conn:
        row = (
            conn.execution_options(cross_org="worker claims the next due job from any organisation")
            .execute(CLAIM_SQL, {"worker": worker_id, "until": now + lease, "now": now})
            .one_or_none()
        )
    if row is None:
        return None
    return Job(
        row.id,
        row.org_id,
        row.kind,
        row.payment_id,
        dict(row.payload),
        row.attempts,
        row.max_attempts,
        row.run_at,
    )


def mark_done(conn: Connection, clock: Clock, job: Job, worker_id: str) -> None:
    res = conn.execute(
        update(jobs)
        .where(
            jobs.c.org_id == job.org_id,
            jobs.c.id == job.id,
            jobs.c.locked_by == worker_id,
            jobs.c.done_at.is_(None),
        )
        .values(done_at=clock.now(), locked_by=None, locked_until=None, last_error=None)
    )
    if res.rowcount != 1:
        raise LeaseLost(job.id)


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(2 ** max(attempts - 1, 0), 300))


def mark_failed(engine: Engine, clock: Clock, job: Job, worker_id: str, error: str) -> bool:
    """Reschedule or kill the job. Returns True if it is now dead."""
    now = clock.now()
    dead = job.attempts >= job.max_attempts
    with engine.begin() as conn:
        conn.execute(
            update(jobs)
            .where(jobs.c.org_id == job.org_id, jobs.c.id == job.id, jobs.c.locked_by == worker_id)
            .values(
                locked_by=None,
                locked_until=None,
                last_error=error[:2000],
                run_at=now + backoff(job.attempts),
                dead_at=now if dead else None,
            )
        )
    return dead


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"))
