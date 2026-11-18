"""The state table is code (spec/02). These pin the safety-relevant edges."""

import pytest
from detent.domain.states import (
    ALLOWED,
    ATTEMPT_ALLOWED,
    TERMINAL,
    AttemptStatus,
    InvalidTransition,
    Status,
    check_attempt_transition,
    check_transition,
)

S, A = Status, AttemptStatus


def test_every_status_has_a_row() -> None:
    assert set(ALLOWED) == set(Status)
    assert set(ATTEMPT_ALLOWED) == set(AttemptStatus)
    for targets in ALLOWED.values():
        assert targets <= set(Status)


def test_terminal_states_match_spec() -> None:
    assert {S.CONFIRMED, S.BLOCKED, S.REJECTED, S.CANCELLED, S.FAILED_FINAL, S.SHADOWED} == TERMINAL


@pytest.mark.parametrize("terminal", sorted(TERMINAL))
@pytest.mark.parametrize("target", list(Status))
def test_nothing_leaves_a_terminal_state(terminal: Status, target: Status) -> None:
    with pytest.raises(InvalidTransition):
        check_transition(terminal, target)


def test_unknown_is_never_resent_or_retried() -> None:
    # Invariant 3: UNKNOWN resolves only to CONFIRMED or FAILED (on evidence).
    assert ALLOWED[S.UNKNOWN] == {S.CONFIRMED, S.FAILED}
    for bad in (S.READY, S.SUBMITTED, S.FAILED_FINAL, S.HELD):
        with pytest.raises(InvalidTransition):
            check_transition(S.UNKNOWN, bad)


def test_no_escalated_to_ready_shortcut_from_received() -> None:
    # Escalated payments reach READY only from ESCALATED (after approval + re-run), never skipping.
    assert S.SUBMITTED not in ALLOWED[S.ESCALATED]
    assert S.SUBMITTED not in ALLOWED[S.RECEIVED]


def test_timeout_path_goes_through_unknown() -> None:
    check_transition(S.SUBMITTED, S.UNKNOWN)
    check_transition(S.UNKNOWN, S.CONFIRMED)
    check_attempt_transition(A.SUBMITTED, A.UNKNOWN)
    with pytest.raises(InvalidTransition):
        check_attempt_transition(A.CONFIRMED, A.FAILED)
    with pytest.raises(InvalidTransition):
        check_attempt_transition(A.FAILED, A.CREATED)
