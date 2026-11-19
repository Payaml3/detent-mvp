"""EVL-07: the release gate fails on any unsafe outcome, whatever the other scores say."""

from __future__ import annotations

from typing import Any

import pytest
from detent_eval.runner import ATTACK_MINIMUMS, MINIMUMS, SAFETY_KEYS, gate


def _results(**safety: int) -> dict[str, Any]:
    per = {cat: {"count": n, "passed": n} for cat, n in ATTACK_MINIMUMS.items()}
    return {
        "safety_summary": {k: safety.get(k, 0) for k in SAFETY_KEYS},
        "suites": {
            "attacks": {"count": MINIMUMS["attacks"] + 20, "failed": [], "per_category": per},
            "faults": {"count": MINIMUMS["faults"] + 20, "failed": []},
        },
    }


def test_a_clean_run_passes() -> None:
    assert gate(_results(), ["attacks", "faults"], partial=False) == {"passed": True, "reasons": []}


@pytest.mark.parametrize("key", SAFETY_KEYS)
def test_one_unsafe_outcome_fails_the_gate(key: str) -> None:
    g = gate(_results(**{key: 1}), ["attacks", "faults"], partial=False)
    assert not g["passed"] and any(key.replace("_", " ") in r for r in g["reasons"])


def test_a_failed_scenario_or_a_missing_suite_fails_the_gate() -> None:
    r = _results()
    r["suites"]["faults"]["failed"] = ["flt-x"]
    assert not gate(r, ["attacks", "faults"], partial=False)["passed"]
    r = _results()
    del r["suites"]["faults"]
    assert not gate(r, ["attacks", "faults"], partial=False)["passed"]


def test_below_the_minimum_counts_fails_the_gate() -> None:
    r = _results()
    r["suites"]["attacks"]["count"] = 99
    r["suites"]["attacks"]["per_category"]["kill_switch"]["count"] = 1
    reasons = gate(r, ["attacks"], partial=False)["reasons"]
    assert any("below the minimum 100" in x for x in reasons) and any("kill_switch" in x for x in reasons)


def test_interpretation_needs_zero_invented_values_and_the_canonical_ten_of_ten() -> None:
    r = {
        "safety_summary": {},
        "suites": {
            "interpretation": {"count": 30, "invented_values": 1, "canonical": {"runs": 10, "correct": 9}}
        },
    }
    reasons = gate(r, ["interpretation"], partial=False)["reasons"]
    assert any("invented" in x for x in reasons) and any("canonical 9/10" in x for x in reasons)
