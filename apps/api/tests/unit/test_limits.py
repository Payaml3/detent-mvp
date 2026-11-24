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
