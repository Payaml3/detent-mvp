"""POL-02: same inputs and rule version always give the same decision; precedence always holds."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from detent.domain.money import Money
from detent.policy.engine import evaluate
from detent.policy.facts import ScreeningResult, Unavailable
from hypothesis import given, settings
from hypothesis import strategies as st
from policy_helpers import NOW, RULES, routine

facts_st = st.builds(
    lambda minor, kyb, listed, count, days_seen, days_changed, hit, scr_down, block: routine(
        amount=Money(minor, routine().amount.currency),
        counterparty=dataclasses.replace(
            routine().counterparty, kyb_status=kyb, allowlisted=listed, payment_count=count
        ),
        destination=dataclasses.replace(
            routine().destination,
            first_seen_at=NOW - timedelta(days=days_seen),
            last_changed_at=NOW - timedelta(days=min(days_seen, days_changed)),
        ),
        screening=Unavailable("screening", "TimeoutError") if scr_down else ScreeningResult(hit=hit),
        recent_block_id="pay_01X" if block else None,
    ),
    st.integers(min_value=1, max_value=200_000_000_000),
    st.sampled_from(["verified", "pending", "failed", "unknown"]),
    st.booleans(),
    st.integers(min_value=0, max_value=50),
    st.integers(min_value=0, max_value=400),
    st.integers(min_value=0, max_value=400),
    st.booleans(),
    st.booleans(),
    st.booleans(),
)


@settings(max_examples=300)
@given(facts_st)
def test_same_inputs_same_decision(f: object) -> None:
    a, b = evaluate(f, RULES), evaluate(f, RULES)  # type: ignore[arg-type]
    assert a == b


@settings(max_examples=300)
@given(facts_st)
def test_precedence(f: object) -> None:
    r = evaluate(f, RULES)  # type: ignore[arg-type]
    results = {c.result for c in r.checks}
    if "BLOCK" in results:
        assert r.outcome == "BLOCK"
    elif "ESCALATE" in results:
        assert r.outcome == "ESCALATE"
    else:
        assert r.outcome == "EXECUTE"
    if r.system_unavailable:
        assert r.outcome != "EXECUTE"
