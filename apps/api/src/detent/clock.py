"""The Clock service (FND-05, invariant 17).

Every module in ``detent`` reads time from a ``Clock``. This file is the only place allowed to call
``datetime.now``; ruff's banned-API rule and ``tests/unit/test_no_direct_time.py`` enforce that.

- ``SystemClock``: real UTC time.
- ``FrozenClock``: fixed time that tests move explicitly.
- ``DemoClock``: real time plus an offset stored per organisation in ``demo_clock``, so the API
  and the worker agree on fast-forwarded time. Only constructed when ``APP_ENV=demo``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """A clock that only moves when told to. Thread-safe."""

    def __init__(self, at: datetime | None = None) -> None:
        start = at or datetime(2026, 12, 3, 10, 0, tzinfo=UTC)
        if start.tzinfo is None:
            raise ValueError("FrozenClock needs a timezone-aware datetime")
        self._at = start.astimezone(UTC)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._at

    def advance(self, delta: timedelta) -> datetime:
        if delta < timedelta(0):
            raise ValueError("time does not go backwards")
        with self._lock:
            self._at += delta
            return self._at

    def set(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("needs a timezone-aware datetime")
        with self._lock:
            self._at = at.astimezone(UTC)


# The fast-forward steps the console offers in demo mode.
DEMO_STEPS: dict[str, timedelta] = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
}


class DemoClock:
    """Real time plus a persisted offset.

    ``offset_loader`` returns the current offset in seconds (read from ``demo_clock``). It is cached
    for ``cache_seconds`` of real time so that hot paths don't query on every call.
    """

    def __init__(
        self,
        offset_loader: Callable[[], int],
        base: Clock | None = None,
        cache_seconds: float = 0.5,
    ) -> None:
        self._load = offset_loader
        self._base = base or SystemClock()
        self._cache_for = timedelta(seconds=cache_seconds)
        self._cached: tuple[datetime, int] | None = None
        self._lock = threading.Lock()

    def offset_seconds(self) -> int:
        real = self._base.now()
        with self._lock:
            if self._cached is None or real - self._cached[0] > self._cache_for:
                self._cached = (real, int(self._load()))
            return self._cached[1]

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None

    def now(self) -> datetime:
        return self._base.now() + timedelta(seconds=self.offset_seconds())
