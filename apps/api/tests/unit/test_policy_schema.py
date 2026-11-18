"""POL-01: rule sets are validated on load, with line-level errors, and identified by version and hash."""

from __future__ import annotations

import pytest
from detent.domain.money import Money
from detent.policy.schema import RuleSetError, load_ruleset
from detent.settings import REPO_ROOT
from pydantic import ValidationError

FIXTURE = (REPO_ROOT / "fixtures" / "policy" / "default-policy.yaml").read_text()


def test_fixture_rule_set_loads() -> None:
    rs = load_ruleset(FIXTURE)
    assert rs.version == 1
    assert rs.fail_safe == "manual_queue"
    assert rs.checks.limits.auto_limit_for("USDC") == Money.parse("10000.00", "USDC")
    assert rs.checks.travel_rule is not None
    assert rs.checks.travel_rule.threshold_for("GBP") == Money.parse("1000.00", "GBP")  # D-25


def test_hash_identifies_the_exact_text() -> None:
    a, b = load_ruleset(FIXTURE), load_ruleset(FIXTURE)
    assert a.content_hash == b.content_hash and len(a.content_hash) == 64
    assert load_ruleset(FIXTURE + "\n# a comment\n").content_hash != a.content_hash


def test_loaded_rule_set_is_immutable() -> None:
    rs = load_ruleset(FIXTURE)
    with pytest.raises(ValidationError, match="frozen"):
        rs.version = 2  # type: ignore[misc]


def test_invalid_value_reports_its_line() -> None:
    bad = FIXTURE.replace("block_on: [failed, unknown]", "block_on: [failed, sometimes]")
    with pytest.raises(RuleSetError) as ei:
        load_ruleset(bad)
    line = next(i for i, ln in enumerate(bad.splitlines(), start=1) if "sometimes" in ln)
    assert any(e.line == line and "kyb_status" in e.path for e in ei.value.errors)
    assert f"line {line}" in str(ei.value)


def test_unknown_key_is_rejected_with_its_line() -> None:
    bad = FIXTURE.replace("  allowlist: {", "  allowlistt: {")
    with pytest.raises(RuleSetError) as ei:
        load_ruleset(bad)
    line = next(i for i, ln in enumerate(bad.splitlines(), start=1) if "allowlistt" in ln)
    assert any(e.line == line for e in ei.value.errors)


def test_float_money_is_rejected() -> None:
    bad = FIXTURE.replace('auto_limit: {USDC: "10000.00",', "auto_limit: {USDC: 10000.5,")
    with pytest.raises(RuleSetError, match="decimal string"):
        load_ruleset(bad)


def test_every_allowed_currency_needs_limits() -> None:
    bad = FIXTURE.replace(
        'auto_limit: {USDC: "10000.00", GBP: "5000.00", EUR: "5000.00"}', 'auto_limit: {USDC: "10000.00"}'
    )
    with pytest.raises(RuleSetError, match="auto_limit"):
        load_ruleset(bad)


def test_yaml_syntax_error_reports_line() -> None:
    with pytest.raises(RuleSetError) as ei:
        load_ruleset("version: 1\nchecks: [unclosed\n")
    assert ei.value.errors[0].line is not None
