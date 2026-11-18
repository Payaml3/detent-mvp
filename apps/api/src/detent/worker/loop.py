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
    def __init__(self, rt: Runtime, worker_id: str | None = None) -> None:
        self.rt = rt
        self.worker_id = worker_id or rt.settings.worker_id or default_worker_id()
        self.lease = timedelta(seconds=rt.settings.worker_lease_seconds)
        self.stop = threading.Event()
        importlib.import_module("detent.execution.jobs")  # payment.send, payment.confirm
        for mod in rt.settings.worker_extra_handler_modules:
            importlib.import_module(mod)

    def run_one(self) -> bool:
        """Claim and run one due job. Returns False when nothing was due."""
        job = queue.claim(self.rt.engine, self.rt.clock, self.worker_id, self.lease)
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

    def run(self) -> None:
        log.info("worker started", extra={"worker_id": self.worker_id, "handlers": registry.kinds()})
        self.startup()
        while not self.stop.is_set():
            try:
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
