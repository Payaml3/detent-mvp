"""Parallel workers never run the same job twice (SKIP LOCKED claim)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
import support.handlers  # noqa: F401
from conftest import OrgFixture, make_settings
from detent.clock import FrozenClock
from detent.runtime import build_runtime
from detent.worker import queue
from detent.worker.loop import Worker
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


def test_parallel_workers_run_each_job_exactly_once(
    engine: Engine, org: OrgFixture, clock: FrozenClock
) -> None:
    with engine.begin() as c:
        ids = [queue.enqueue(c, clock, org_id=org.id, kind="test.side_effect") for _ in range(60)]
    rt = build_runtime(make_settings(org.id), engine=engine, clock=clock)
    workers = [Worker(rt, worker_id=f"w{i}") for i in range(8)]

    def drain(w: Worker) -> int:
        n = 0
        while w.run_one():
            n += 1
        return n

    with ThreadPoolExecutor(len(workers)) as ex:
        ran = sum(ex.map(drain, workers))
    assert ran >= 60
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT job_id, count(*) AS n FROM testsupport.side_effects WHERE org_id=:o GROUP BY job_id"
            ),
            {"o": org.id},
        ).all()
    assert {r.job_id for r in rows} == set(ids)
    assert all(r.n == 1 for r in rows)
