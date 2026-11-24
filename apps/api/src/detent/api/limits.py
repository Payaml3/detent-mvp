"""Dated API versions (API-03) and per-key rate limits (API-04).

The limiter is a fixed window held in memory per process: enough for the single-instance sandbox.
Time comes from the Clock (invariant 17). Keys are tracked by a digest of the token, never the token.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime

VERSION_HEADER = "Detent-Version"
CURRENT_VERSION = "2026-12-01"
SUPPORTED_VERSIONS = frozenset({CURRENT_VERSION})
DEFAULT_LIMIT = 120
WINDOW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class LimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


class RateLimiter:
    def __init__(self, limit: int = DEFAULT_LIMIT, window: int = WINDOW_SECONDS) -> None:
        self.limit, self.window = limit, window
        self._lock = threading.Lock()
        self._state: dict[str, tuple[int, int]] = {}  # digest -> (window index, count)

    def hit(self, token: str, now: datetime) -> LimitResult:
        digest = hashlib.sha256(token.encode()).hexdigest()
        ts = int(now.timestamp())
        idx = ts // self.window
        reset = (idx + 1) * self.window - ts
        with self._lock:
            if len(self._state) > 10_000:  # bound memory: drop windows that have passed
                self._state = {k: v for k, v in self._state.items() if v[0] == idx}
            w, n = self._state.get(digest, (idx, 0))
            if w != idx:
                n = 0
            if n >= self.limit:
                return LimitResult(False, self.limit, 0, reset)
            self._state[digest] = (idx, n + 1)
            return LimitResult(True, self.limit, self.limit - n - 1, reset)
