"""FND-06: Postgres job loop; idempotent jobs; a killed worker never duplicates a side effect."""

from __future__ import annotations

import logging
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import support.handlers  # noqa: F401  (registers test handlers)
from conftest import OrgFixture, child_env, make_settings
from detent.clock import FrozenClock
from detent.runtime import build_runtime
from detent.settings import REPO_ROOT
from detent.worker import queue
from detent.worker.loop import Worker
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


def _effects(engine: Engine, job_id: str) -> int:
    with engine.connect() as c:
        return int(
            c.execute(
                text("SELECT count(*) FROM testsupport.side_effects WHERE job_id=:j"), {"j": job_id}
            ).scalar_one()
        )


def _job(engine: Engine, org: OrgFixture, job_id: str):  # type: ignore[no-untyped-def]
    with engine.connect() as c:
        return c.execute(
            text("SELECT * FROM jobs WHERE org_id=:o AND id=:j"), {"o": org.id, "j": job_id}
        ).one()


def _worker(engine: Engine, org: OrgFixture, clock: FrozenClock, wid: str = "w1", **kw: object) -> Worker:
    s = make_settings(org.id, worker_lease_seconds=30, **kw)
    return Worker(build_runtime(s, engine=engine, clock=clock), worker_id=wid)


def _enqueue(engine: Engine, org: OrgFixture, clock: FrozenClock, **kw: object) -> str:
    with engine.begin() as c:
        jid = queue.enqueue(c, clock, org_id=org.id, kind="test.side_effect", **kw)  # type: ignore[arg-type]
    assert jid
    return jid


def _drain(w: Worker) -> None:
    while w.run_one():
        pass


def test_job_runs_once_and_is_done(
    engine: Engine, org: OrgFixture, clock: FrozenClock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="detent.worker")
    jid = _enqueue(engine, org, clock, payment_id="pay_x")
    w = _worker(engine, org, clock)
    _drain(w)
    done = [r for r in caplog.records if r.getMessage() == "job done" and getattr(r, "job_id", None) == jid]
    assert done and done[0].payment_id == "pay_x" and done[0].duration_ms >= 0  # type: ignore[attr-defined]
    assert _effects(engine, jid) == 1
    assert _job(engine, org, jid).done_at is not None
    _drain(w)
    assert _effects(engine, jid) == 1


def test_dedupe_key_makes_enqueue_idempotent(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    with engine.begin() as c:
        a = queue.enqueue(c, clock, org_id=org.id, kind="test.side_effect", dedupe_key="resolve:att_1")
        b = queue.enqueue(c, clock, org_id=org.id, kind="test.side_effect", dedupe_key="resolve:att_1")
    assert a and b is None


def test_future_jobs_wait_for_the_clock(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    jid = _enqueue(engine, org, clock, run_at=clock.now() + timedelta(minutes=5))
    w = _worker(engine, org, clock)
    _drain(w)
    assert _effects(engine, jid) == 0
    clock.advance(timedelta(minutes=5))
    _drain(w)
    assert _effects(engine, jid) == 1


def test_failure_rolls_back_effects_and_retries_with_backoff(
    engine: Engine, org: OrgFixture, clock: FrozenClock
) -> None:
    jid = _enqueue(engine, org, clock, payload={"fail_times": 2})
    w = _worker(engine, org, clock)
    w.run_one()
    j = _job(engine, org, jid)
    assert _effects(engine, jid) == 0, "a failed run's writes must roll back"
    assert j.done_at is None and j.attempts == 1 and "planned failure" in j.last_error
    assert j.run_at == clock.now() + timedelta(seconds=1)
    clock.advance(timedelta(seconds=1))
    w.run_one()
    clock.advance(timedelta(seconds=2))
    w.run_one()
    assert _effects(engine, jid) == 1 and _job(engine, org, jid).attempts == 3


def test_job_dies_after_max_attempts(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    jid = _enqueue(engine, org, clock, payload={"fail_times": 99}, max_attempts=2)
    w = _worker(engine, org, clock)
    for _ in range(3):
        w.run_one()
        clock.advance(timedelta(minutes=10))
    j = _job(engine, org, jid)
    assert j.dead_at is not None and j.attempts == 2 and _effects(engine, jid) == 0


def test_unknown_job_kind_fails_closed(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    with engine.begin() as c:
        jid = queue.enqueue(c, clock, org_id=org.id, kind="no.such.handler", max_attempts=1)
    _worker(engine, org, clock).run_one()
    j = _job(engine, org, jid)
    assert j.dead_at is not None and "no handler" in j.last_error


def test_lost_lease_rolls_back_effects(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    jid = _enqueue(engine, org, clock)
    job = queue.claim(engine, clock, "w-old", timedelta(seconds=30))
    assert job is not None
    clock.advance(timedelta(seconds=31))  # lease expires; another worker takes it
    newer = queue.claim(engine, clock, "w-new", timedelta(seconds=30))
    assert newer is not None and newer.id == jid
    from detent.worker.registry import JobContext, get

    with pytest.raises(queue.LeaseLost), engine.begin() as c:
        get("test.side_effect")(JobContext(c, clock, job, "w-old"))  # type: ignore[misc]
        queue.mark_done(c, clock, job, "w-old")
    assert _effects(engine, jid) == 0
    with engine.begin() as c:
        get("test.side_effect")(JobContext(c, clock, newer, "w-new"))  # type: ignore[misc]
        queue.mark_done(c, clock, newer, "w-new")
    assert _effects(engine, jid) == 1


@pytest.mark.slow
def test_killed_worker_never_duplicates_a_side_effect(
    engine: Engine, org: OrgFixture, clock: FrozenClock, tmp_path: Path
) -> None:
    marker = tmp_path / "in-handler"
    # The worker subprocess uses real time, so make the job due in the real past.
    jid = _enqueue(
        engine, org, clock, payload={"marker": str(marker)}, run_at=datetime(2020, 1, 1, tzinfo=UTC)
    )
    env = child_env(
        WORKER_EXTRA_HANDLER_MODULES="support.handlers",
        WORKER_LEASE_SECONDS="2",
        WORKER_POLL_SECONDS="0.1",
    )
    cmd = [sys.executable, "-m", "detent.worker"]
    first = subprocess.Popen(cmd, env=env, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(200):
            if marker.exists():
                break
            time.sleep(0.1)
        assert marker.exists(), "worker never reached the handler"
        first.send_signal(signal.SIGKILL)  # die mid-job, after the side effect was written
        first.wait(10)
    finally:
        if first.poll() is None:
            first.kill()
    assert _effects(engine, jid) == 0, "uncommitted effects of a killed worker must not survive"
    assert _job(engine, org, jid).done_at is None

    second = subprocess.Popen(cmd, env=env, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(200):
            if _job(engine, org, jid).done_at is not None:
                break
            time.sleep(0.1)
    finally:
        second.terminate()
        out = second.communicate(timeout=10)[0].decode()
    j = _job(engine, org, jid)
    assert j.done_at is not None, out
    assert j.attempts == 2
    assert _effects(engine, jid) == 1, "exactly one side effect after a crash and a rerun"
    assert '"job_id": "' + jid in out and "job done" in out
