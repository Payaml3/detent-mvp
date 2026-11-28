"""The worker loop (FND-06)."""

from __future__ import annotations

import importlib
import logging
import socket
import threading
import time
from datetime import timedelta

from detent.logging import payment_context
from detent.runtime import Runtime
from detent.worker import queue, registry

log = logging.getLogger("detent.worker")


def default_worker_id() -> str:
    import os

    return f"{socket.gethostname()}:{os.getpid()}"


class Worker:
    def __init__(self, rt: Runtime, worker_id: str | None = None, *, org_id: str | None = None) -> None:
        self.rt = rt
        self.org_id = org_id  # None: every organisation (production); set: one (evaluation runs)
        self.worker_id = worker_id or rt.settings.worker_id or default_worker_id()
        self.lease = timedelta(seconds=rt.settings.worker_lease_seconds)
        self.stop = threading.Event()
        self._last_sweep: float | None = None
        # Deposit watching and reconciliation first run one interval after start-up, so a fresh worker
        # sends and confirms payments straight away.
        self._last_watch: float | None = time.monotonic()
        self._last_recon: float | None = time.monotonic()
        self._last_log_purge: float | None = None
        self._last_invariants: float | None = None
        self._last_rail_health: float | None = None
        importlib.import_module("detent.execution.jobs")  # payment.send, payment.confirm
        importlib.import_module("detent.exceptions.investigation_job")  # case.investigate (EXC-03)
        importlib.import_module("detent.webhooks.delivery")  # webhook.deliver (WHK-03)
        importlib.import_module("detent.incidents.jobs")  # invariants.check (EXE-10)
        for mod in rt.settings.worker_extra_handler_modules:
            importlib.import_module(mod)

    def run_one(self) -> bool:
        """Claim and run one due job. Returns False when nothing was due."""
        job = queue.claim(self.rt.engine, self.rt.clock, self.worker_id, self.lease, org_id=self.org_id)
        if job is None:
            return False
        fields = {"job_id": job.id, "job_kind": job.kind, "attempt": job.attempts, "org_id": job.org_id}
        with payment_context(job.payment_id):
            started = time.perf_counter()  # duration only; domain time uses the Clock
            fn = registry.get(job.kind)
            try:
                if fn is None:
                    raise LookupError(f"no handler registered for job kind {job.kind!r}")
                with self.rt.engine.begin() as conn:
                    fn(
                        registry.JobContext(
                            conn, self.rt.clock, job, self.worker_id, self.rt.engine, self.rt.settings
                        )
                    )
                    queue.mark_done(conn, self.rt.clock, job, self.worker_id)
            except queue.LeaseLost:
                log.warning("job lease lost; effects rolled back", extra=fields)
            except Exception as exc:
                dead = queue.mark_failed(self.rt.engine, self.rt.clock, job, self.worker_id, repr(exc))
                log.exception(
                    "job failed",
                    extra={**fields, "dead": dead, "duration_ms": _ms(started), "error": type(exc).__name__},
                )
            else:
                log.info("job done", extra={**fields, "duration_ms": _ms(started)})
        return True

    def startup(self) -> None:
        """EXE-04: before sending anything, check every used wallet's nonce against the chain."""
        from detent.execution.jobs import reconcile_all

        reconcile_all(self.rt.engine, self.rt.clock, self.rt.settings)

    def tick(self, *, force: bool = False) -> dict[str, list[str]]:
        """Scheduled work between jobs: the deadline sweeper (EXC-06). Returns the cases it moved."""
        from detent.exceptions.deadlines import sweep_all

        try:
            self.watch_deposits(force=force)
            self.reconcile(force=force)
            self.purge_request_logs(force=force)
        except Exception:
            log.exception("deposit watching or reconciliation failed")  # never stops the sweeper or job loop
        try:
            self.check_invariants(force=force)
        except Exception:
            log.exception("invariant monitor failed")  # never stops the sweeper or job loop
        try:
            self.check_rails(force=force)
        except Exception:
            log.exception("rail health check failed")  # never stops the sweeper or job loop
        mono = time.monotonic()  # scheduling cadence only; the sweep itself reads the Clock
        recent = (
            self._last_sweep is not None and mono - self._last_sweep < self.rt.settings.deadline_sweep_seconds
        )
        if recent and not force:
            return {}
        self._last_sweep = mono
        moved = sweep_all(self.rt.engine, self.rt.clock)
        if moved:
            log.info(
                "overdue cases held and reassigned", extra={"cases": sum(len(v) for v in moved.values())}
            )
        return moved

    def watch_deposits(self, *, force: bool = False) -> dict[str, int]:
        """LED-04: deposit watchers and the credit-once step, on their own cadence."""
        from detent.ledger.watchers import watch_all

        mono = time.monotonic()
        last = self._last_watch
        if not force and last is not None and mono - last < self.rt.settings.deposit_watch_seconds:
            return {}
        self._last_watch = mono
        return watch_all(self.rt.engine, self.rt.clock, self.rt.settings)

    def reconcile(self, *, force: bool = False) -> dict[str, str]:
        """LED-06: the scheduled reconciliation run."""
        from detent.reconciliation.run import run_all

        mono = time.monotonic()
        last = self._last_recon
        if not force and last is not None and mono - last < self.rt.settings.reconciliation_seconds:
            return {}
        self._last_recon = mono
        return run_all(self.rt.engine, self.rt.clock, self.rt.settings)

    def purge_request_logs(self, *, force: bool = False) -> int:
        """API-06: drop request logs past the 30-day window, at most once an hour."""
        from detent.db.retention import purge_request_logs

        mono = time.monotonic()
        last = self._last_log_purge
        if not force and last is not None and mono - last < 3600:
            return 0
        self._last_log_purge = mono
        return purge_request_logs(self.rt.engine, self.rt.clock)

    def check_invariants(self, *, force: bool = False) -> dict[str, list[str]]:
        """EXE-10: the Sev 1 invariant monitor, every minute by default."""
        from detent.incidents.monitor import check_all

        mono = time.monotonic()
        last = self._last_invariants
        if not force and last is not None and mono - last < self.rt.settings.invariant_monitor_seconds:
            return {}
        self._last_invariants = mono
        opened = check_all(
            self.rt.engine, self.rt.clock, kill_switch=self.rt.settings.invariant_monitor_kill_switch
        )
        if opened:
            log.error("Sev 1: an invariant broke", extra={"incidents": sum(len(v) for v in opened.values())})
        return opened

    def check_rails(self, *, force: bool = False) -> dict[str, dict[str, str]]:
        """RAL-08: open, probe and close rail circuits."""
        from detent.rails.health import check_all

        mono = time.monotonic()
        last = self._last_rail_health
        if not force and last is not None and mono - last < self.rt.settings.rail_health_seconds:
            return {}
        self._last_rail_health = mono
        return check_all(self.rt.engine, self.rt.clock, self.rt.settings)

    def run(self) -> None:
        log.info("worker started", extra={"worker_id": self.worker_id, "handlers": registry.kinds()})
        self.startup()
        while not self.stop.is_set():
            try:
                self.tick()
                busy = self.run_one()
            except Exception:
                # Database unavailable or similar: back off, never crash-loop.
                log.exception("worker loop error")
                busy = False
            if not busy:
                self.stop.wait(self.rt.settings.worker_poll_seconds)
        log.info("worker stopped", extra={"worker_id": self.worker_id})


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
