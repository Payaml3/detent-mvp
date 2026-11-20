"""Builds the shared services (engine, clock) from settings, for the API and the worker."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, select

from detent.clock import Clock, DemoClock, SystemClock
from detent.db.engine import make_engine
from detent.db.tables import demo_clock
from detent.settings import Settings


@dataclass
class Runtime:
    settings: Settings
    engine: Engine
    clock: Clock


def demo_offset_loader(engine: Engine, org_id: str) -> int:
    """The demo clock's offset for the newest generation of ``org_id`` (CON-09 reset)."""
    from detent.demo.generations import active_org

    with engine.connect() as conn:
        org_id = active_org(conn, org_id)
        v = conn.execute(
            select(demo_clock.c.offset_seconds).where(demo_clock.c.org_id == org_id)
        ).scalar_one_or_none()
    return int(v or 0)


def build_runtime(settings: Settings, engine: Engine | None = None, clock: Clock | None = None) -> Runtime:
    eng = engine or make_engine(settings.database_url)
    if clock is None:
        if settings.is_demo:
            org = settings.demo_org_id
            clock = DemoClock(lambda: demo_offset_loader(eng, org))
        else:
            clock = SystemClock()
    return Runtime(settings=settings, engine=eng, clock=clock)
