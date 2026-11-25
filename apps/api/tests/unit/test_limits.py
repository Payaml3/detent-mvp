"""API-03 and API-04: versions and rate limits (no database)."""

from __future__ import annotations

from datetime import UTC, datetime

from detent.api.limits import RateLimiter

T = datetime(2026, 12, 1, 12, 0, 10, tzinfo=UTC)


def test_limit_counts_down_then_blocks_and_resets() -> None:
    rl = RateLimiter(limit=2, window=60)
    a, b = rl.hit("k", T), rl.hit("k", T)
    assert (a.allowed, a.remaining, a.reset_seconds) == (True, 1, 50)
    assert b.remaining == 0
    c = rl.hit("k", T)
    assert not c.allowed and c.remaining == 0 and c.reset_seconds == 50
    assert rl.hit("k", T.replace(minute=1)).allowed  # next window


def test_limits_are_per_key() -> None:
    rl = RateLimiter(limit=1)
    assert rl.hit("a", T).allowed and rl.hit("b", T).allowed and not rl.hit("a", T).allowed


def test_memory_is_bounded_and_overflow_fails_closed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import detent.api.limits as lim

    monkeypatch.setattr(lim, "MAX_TRACKED", 5)
    rl = RateLimiter(limit=1)
    for i in range(5):
        assert rl.hit(f"k{i}", T).allowed
    assert rl.hit("new1", T).allowed  # first overflow hit uses the shared bucket
    assert not rl.hit("new2", T).allowed  # then new keys share it: fail closed
    assert len(rl._state) <= 6
