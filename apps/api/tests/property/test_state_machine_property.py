"""Property tests: random event sequences never leave the state table (spec/09)."""

from itertools import pairwise

from detent.domain.money import Currency, Money
from detent.domain.states import ALLOWED, INITIAL, TERMINAL, InvalidTransition, Status, check_transition
from hypothesis import given, settings
from hypothesis import strategies as st


@settings(max_examples=500)
@given(st.lists(st.sampled_from(list(Status)), max_size=40))
def test_random_events_never_leave_the_table(events: list[Status]) -> None:
    state = INITIAL
    path = [state]
    for target in events:
        try:
            check_transition(state, target)
        except InvalidTransition:
            assert target not in ALLOWED[state]
            continue
        assert state not in TERMINAL, "a terminal state had an outgoing transition"
        state = target
        path.append(state)
    for a, b in pairwise(path):
        assert b in ALLOWED[a]
    # UNKNOWN is only ever entered from SUBMITTED, and left only to CONFIRMED or FAILED.
    for a, b in pairwise(path):
        if b is Status.UNKNOWN:
            assert a is Status.SUBMITTED
        if a is Status.UNKNOWN:
            assert b in {Status.CONFIRMED, Status.FAILED}


@given(st.integers(min_value=-(10**15), max_value=10**15), st.sampled_from(list(Currency)))
def test_money_round_trips_through_decimal_strings(minor: int, cur: Currency) -> None:
    m = Money(minor, cur)
    assert Money.parse(m.to_decimal_str(), cur) == m


@given(st.lists(st.integers(min_value=0, max_value=10**12), max_size=30))
def test_money_sum_is_exact(parts: list[int]) -> None:
    total = Money.zero("USDC")
    for p in parts:
        total = total + Money(p, Currency.USDC)
    assert total.amount_minor == sum(parts)
