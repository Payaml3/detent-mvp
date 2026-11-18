from datetime import UTC, datetime, timedelta

import pytest
from detent.clock import DemoClock, FrozenClock, SystemClock


def test_frozen_clock_moves_only_when_told() -> None:
    c = FrozenClock(datetime(2026, 12, 3, 10, tzinfo=UTC))
    assert c.now() == c.now()
    c.advance(timedelta(hours=2))
    assert c.now() == datetime(2026, 12, 3, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="backwards"):
        c.advance(timedelta(seconds=-1))


def test_system_clock_is_utc() -> None:
    assert SystemClock().now().tzinfo is UTC


def test_demo_clock_adds_persisted_offset_and_caches() -> None:
    base = FrozenClock(datetime(2026, 12, 3, 10, tzinfo=UTC))
    offset = {"v": 0, "loads": 0}

    def load() -> int:
        offset["loads"] += 1
        return offset["v"]

    c = DemoClock(load, base=base, cache_seconds=5)
    assert c.now() == base.now()
    offset["v"] = 3600
    assert c.now() == base.now()  # cached
    c.invalidate()
    assert c.now() == base.now() + timedelta(hours=1)
    base.advance(timedelta(seconds=10))  # cache expires with real time
    offset["v"] = 7200
    assert c.now() == base.now() + timedelta(hours=2)
