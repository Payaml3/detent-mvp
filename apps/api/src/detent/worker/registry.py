"""Job handler registry. Stories register their handlers here (UNKNOWN resolver, deadline sweeper...)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import Connection, Engine

from detent.clock import Clock
from detent.worker.queue import Job

if TYPE_CHECKING:
    from detent.settings import Settings


@dataclass(frozen=True, slots=True)
class JobContext:
    conn: Connection  # the job's transaction: writes commit together with "done"
    clock: Clock
    job: Job
    worker_id: str
    # For handlers that need transactions of their own (sending stores the signed transaction first).
    engine: Engine | None = None
    settings: Settings | None = None


Handler = Callable[[JobContext], None]

_HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        if kind in _HANDLERS and _HANDLERS[kind] is not fn:
            raise ValueError(f"duplicate handler for job kind {kind!r}")
        _HANDLERS[kind] = fn
        return fn

    return deco


def get(kind: str) -> Handler | None:
    return _HANDLERS.get(kind)


def kinds() -> list[str]:
    return sorted(_HANDLERS)


@handler("system.noop")
def _noop(ctx: JobContext) -> None:
    """Does nothing; used by smoke tests and health checks."""
