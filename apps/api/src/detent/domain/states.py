"""The payment and attempt state machines as data (spec/02).

"The table is code." ``ALLOWED`` is the single source of truth for payment transitions. The
database mirrors the terminal states with a trigger (migration 0001), and a test asserts that the
trigger's list equals ``TERMINAL`` here. ``transition()`` (EXE-01, M3) must consult ``ALLOWED``.
"""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    RECEIVED = "RECEIVED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"
    READY = "READY"
    SHADOWED = "SHADOWED"
    HELD = "HELD"
    SUBMITTED = "SUBMITTED"
    UNKNOWN = "UNKNOWN"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    FAILED_FINAL = "FAILED_FINAL"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


S = Status

ALLOWED: dict[Status, frozenset[Status]] = {
    # RECEIVED -> HELD: the decision itself failed and fail_safe is 'hold' (C-03, D-09).
    S.RECEIVED: frozenset({S.BLOCKED, S.ESCALATED, S.READY, S.SHADOWED, S.HELD}),
    # ESCALATED -> ESCALATED: a re-run found a new reason, so a new case opens.
    S.ESCALATED: frozenset({S.READY, S.BLOCKED, S.REJECTED, S.ESCALATED, S.CANCELLED}),
    S.READY: frozenset({S.SUBMITTED, S.HELD, S.BLOCKED, S.CANCELLED}),
    S.HELD: frozenset({S.READY, S.ESCALATED, S.BLOCKED, S.CANCELLED}),
    S.SUBMITTED: frozenset({S.CONFIRMED, S.UNKNOWN, S.FAILED}),
    # Invariant 3: UNKNOWN resolves only on rail evidence. Never to READY, never resent.
    S.UNKNOWN: frozenset({S.CONFIRMED, S.FAILED}),
    S.FAILED: frozenset({S.READY, S.FAILED_FINAL}),
    S.CONFIRMED: frozenset(),
    S.BLOCKED: frozenset(),
    S.REJECTED: frozenset(),
    S.CANCELLED: frozenset(),
    S.FAILED_FINAL: frozenset(),
    S.SHADOWED: frozenset(),
}

TERMINAL: frozenset[Status] = frozenset(s for s, nxt in ALLOWED.items() if not nxt)
INITIAL: Status = S.RECEIVED
# Statuses whose amount counts against daily caps and mandate totals (spec/04).
IN_FLIGHT: frozenset[Status] = frozenset({S.READY, S.SUBMITTED, S.UNKNOWN})


class AttemptStatus(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    UNKNOWN = "UNKNOWN"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


A = AttemptStatus

ATTEMPT_ALLOWED: dict[AttemptStatus, frozenset[AttemptStatus]] = {
    A.CREATED: frozenset({A.SUBMITTED}),
    A.SUBMITTED: frozenset({A.CONFIRMED, A.UNKNOWN, A.FAILED}),
    A.UNKNOWN: frozenset({A.CONFIRMED, A.FAILED}),
    A.CONFIRMED: frozenset(),
    A.FAILED: frozenset(),
}

ATTEMPT_TERMINAL: frozenset[AttemptStatus] = frozenset(s for s, n in ATTEMPT_ALLOWED.items() if not n)
ATTEMPT_IN_FLIGHT: frozenset[AttemptStatus] = frozenset({A.CREATED, A.SUBMITTED, A.UNKNOWN})


class FailureClass(StrEnum):
    TECHNICAL_RETRYABLE = "TECHNICAL_RETRYABLE"
    TECHNICAL_FINAL = "TECHNICAL_FINAL"
    REJECTED_BY_RAIL = "REJECTED_BY_RAIL"
    TIMEOUT = "TIMEOUT"  # only ever leads to UNKNOWN


class InvalidTransition(ValueError):
    def __init__(self, old: StrEnum, new: StrEnum) -> None:
        super().__init__(f"invalid transition {old.value} -> {new.value}")
        self.old = old
        self.new = new


def can_transition(old: Status, new: Status) -> bool:
    return new in ALLOWED[old]


def check_transition(old: Status, new: Status) -> None:
    if not can_transition(old, new):
        raise InvalidTransition(old, new)


def check_attempt_transition(old: AttemptStatus, new: AttemptStatus) -> None:
    if new not in ATTEMPT_ALLOWED[old]:
        raise InvalidTransition(old, new)
