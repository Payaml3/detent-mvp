"""POL-07, C-08: the structured diff and the loosening detector (union of spec/04 and POL-07)."""

from __future__ import annotations

import pytest
from detent.policy.changes import diff, loosening_reasons
from detent.policy.schema import load_ruleset
from policy_helpers import BASE, v2


def reasons(*edits: tuple[str, str]) -> list[str]:
    return loosening_reasons(load_ruleset(BASE), load_ruleset(v2(*edits)))


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        (('auto_limit: {USDC: "10000.00"', 'auto_limit: {USDC: "15000.00"'), "LIMIT_RAISED"),
        (('hard_max:   {USDC: "100000.00"', 'hard_max:   {USDC: "200000.00"'), "LIMIT_RAISED"),
        (('platform: {USDC: "50000.00"', 'platform: {USDC: "90000.00"'), "LIMIT_RAISED"),
        (("  allowlist: {escalate_if_not_listed: true}\n", ""), "CHECK_REMOVED"),
        (("mandate_scope: {enabled: true}", "mandate_scope: {enabled: false}"), "CHECK_DISABLED"),
        (("block_on_hit: true", "block_on_hit: false"), "CHECK_DISABLED"),
        (("first_payment: escalate", 'first_payment: "off"'), "CHECK_DISABLED"),
        (("block_on: [failed, unknown]", "block_on: [failed]"), "LIST_SHRUNK"),
        (("escalate_on: [pending]", "escalate_on: []"), "LIST_SHRUNK"),
        (('threshold: {USDC: "1000.00"', 'threshold: {USDC: "3000.00"'), "TRAVEL_RULE_LOOSENED"),
        (("beneficiary.name, beneficiary.account]", "beneficiary.name]"), "TRAVEL_RULE_LOOSENED"),
        (("GBP: [banksim-fps]", "GBP: [banksim-fps, banksim-sepa-inst]"), "NETWORKS_WIDENED"),
        (("new_wallet_days: 7", "new_wallet_days: 2"), "WINDOW_CHANGED"),
        (("window_hours: 24", "window_hours: 6"), "WINDOW_CHANGED"),
        (("max_decision_age_seconds: 300", "max_decision_age_seconds: 900"), "WINDOW_CHANGED"),
        (("above_norm_multiplier: 3.0", "above_norm_multiplier: 5.0"), "THRESHOLD_RAISED"),
        (("list: fixtures/screening-list.yaml", "list: fixtures/other-list.yaml"), "SCREENING_SCOPE_CHANGED"),
    ],
)
def test_each_loosening_kind_is_detected(edit: tuple[str, str], code: str) -> None:
    assert code in [r["code"] for r in reasons(edit)]  # type: ignore[index]


@pytest.mark.parametrize(
    "edit",
    [
        ('auto_limit: {USDC: "10000.00"', 'auto_limit: {USDC: "8000.00"'),
        ("block_on: [failed, unknown]", "block_on: [failed, unknown, pending]"),
        ("new_wallet_days: 7", "new_wallet_days: 14"),
        ("GBP: [banksim-fps]", "GBP: []"),
        ('threshold: {USDC: "1000.00"', 'threshold: {USDC: "500.00"'),
    ],
)
def test_tightening_is_not_loosening(edit: tuple[str, str]) -> None:
    assert reasons(edit) == []


def test_diff_lists_changed_paths_with_old_and_new_values() -> None:
    d = diff(
        load_ruleset(BASE),
        load_ruleset(v2(('auto_limit: {USDC: "10000.00"', 'auto_limit: {USDC: "15000.00"'))),
    )
    assert {"path": "checks.limits.auto_limit.USDC", "old": "10000.00", "new": "15000.00"} in d
    assert {"path": "version", "old": 1, "new": 2} in d
