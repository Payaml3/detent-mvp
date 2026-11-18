"""POL-02, POL-03, POL-04 (rules part), POL-09: the pure decision engine.

The engine reads typed facts only and never does I/O; every check returns PASS, ESCALATE, BLOCK or
NOT_EVALUATED with a reason code and evidence; BLOCK beats ESCALATE beats EXECUTE.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest
from detent.domain.money import Money
from detent.policy.engine import evaluate
from detent.policy.facts import Facts, ScreeningResult, TravelRuleFacts, Unavailable
from policy_helpers import ADDR, NOW, RULES, routine, usdc


def by_name(result: object) -> dict[str, object]:
    return {c.check: c for c in result.checks}  # type: ignore[attr-defined]


def reasons(result: object) -> set[str]:
    return {c.reason for c in result.checks if c.reason}  # type: ignore[attr-defined]


def test_routine_payout_executes_with_a_result_per_check() -> None:
    r = evaluate(routine(), RULES)
    assert r.outcome == "EXECUTE"
    assert {c.result for c in r.checks} <= {"PASS", "NOT_EVALUATED"}
    names = [c.check for c in r.checks]
    for n in [
        "kyb_status",
        "allowlist",
        "screening",
        "travel_rule",
        "allowed_networks",
        "hard_max",
        "auto_limit",
        "daily_cap_platform",
        "daily_cap_counterparty",
        "new_wallet",
        "changed_details",
        "first_payment",
        "above_norm",
        "resubmission_after_block",
    ]:
        assert n in names


def test_precedence_block_beats_escalate() -> None:
    f = routine(amount=usdc("150000.00"), screening=ScreeningResult(hit=False))
    r = evaluate(f, RULES)
    assert "ABOVE_AUTO_LIMIT" in reasons(r) and "ABOVE_HARD_MAX" in reasons(r)
    assert r.outcome == "BLOCK"


def test_every_check_runs_even_after_a_block() -> None:
    r = evaluate(
        routine(
            screening=ScreeningResult(hit=True, matched=ADDR, field="address"),
            counterparty=dataclasses.replace(routine().counterparty, payment_count=0),
        ),
        RULES,
    )
    assert r.outcome == "BLOCK"
    assert {"SCREENING_HIT", "FIRST_PAYMENT"} <= reasons(r)


@pytest.mark.parametrize(
    ("kyb", "result", "reason"),
    [
        ("verified", "PASS", None),
        ("pending", "ESCALATE", "KYB_PENDING"),
        ("failed", "BLOCK", "KYB_FAILED"),
        ("unknown", "BLOCK", "KYB_FAILED"),
    ],
)
def test_kyb(kyb: str, result: str, reason: str | None) -> None:
    f = routine(counterparty=dataclasses.replace(routine().counterparty, kyb_status=kyb))
    c = by_name(evaluate(f, RULES))["kyb_status"]
    assert (c.result, c.reason) == (result, reason)  # type: ignore[attr-defined]


def test_not_allowlisted_escalates() -> None:
    f = routine(counterparty=dataclasses.replace(routine().counterparty, allowlisted=False))
    c = by_name(evaluate(f, RULES))["allowlist"]
    assert (c.result, c.reason) == ("ESCALATE", "NOT_ALLOWLISTED")  # type: ignore[attr-defined]


def test_screening_hit_blocks_with_the_matched_entry() -> None:
    r = evaluate(routine(screening=ScreeningResult(hit=True, matched=ADDR, field="address")), RULES)
    c = by_name(r)["screening"]
    assert (c.result, c.reason) == ("BLOCK", "SCREENING_HIT")  # type: ignore[attr-defined]
    assert c.evidence["matched"] == ADDR  # type: ignore[attr-defined]
    assert r.outcome == "BLOCK"


def test_screening_unavailable_fails_closed() -> None:
    r = evaluate(routine(screening=Unavailable("screening", "TimeoutError")), RULES)
    c = by_name(r)["screening"]
    assert (c.result, c.reason) == ("ESCALATE", "SYSTEM_UNAVAILABLE")  # type: ignore[attr-defined]
    assert r.outcome == "ESCALATE" and r.system_unavailable


def test_travel_rule_missing_fields_escalate_above_threshold() -> None:
    tr = TravelRuleFacts(
        originator={"name": "Demo", "account": None},
        beneficiary={"name": "S", "account": ADDR},
        supplied=None,
    )
    c = by_name(evaluate(routine(travel_rule=tr), RULES))["travel_rule"]
    assert (c.result, c.reason) == ("ESCALATE", "TRAVEL_RULE_MISSING")  # type: ignore[attr-defined]
    assert c.evidence["missing"] == ["originator.account"]  # type: ignore[attr-defined]


def test_travel_rule_below_threshold_passes() -> None:
    tr = TravelRuleFacts(
        originator={"name": "Demo", "account": None},
        beneficiary={"name": "S", "account": ADDR},
        supplied=None,
    )
    c = by_name(evaluate(routine(travel_rule=tr, amount=usdc("999.99")), RULES))["travel_rule"]
    assert c.result == "PASS"  # type: ignore[attr-defined]


def test_travel_rule_supplied_values_must_match_the_registry() -> None:
    tr = dataclasses.replace(
        routine().travel_rule, supplied={"beneficiary": {"name": "Someone Else", "account": ADDR}}
    )
    c = by_name(evaluate(routine(travel_rule=tr), RULES))["travel_rule"]
    assert (c.result, c.reason) == ("ESCALATE", "TRAVEL_RULE_MISSING")  # type: ignore[attr-defined]
    assert c.evidence["mismatched"] == ["beneficiary.name"]  # type: ignore[attr-defined]


def test_travel_rule_threshold_is_per_currency() -> None:  # D-25
    gbp = Money.parse("1000.01", "GBP")
    tr = TravelRuleFacts(
        originator={"name": "Demo", "account": None}, beneficiary={"name": "S", "account": "x"}, supplied=None
    )
    c = by_name(
        evaluate(
            routine(
                amount=gbp,
                network="banksim-fps",
                travel_rule=tr,
                counterparty=dataclasses.replace(routine().counterparty, median=None, payment_count=0),
            ),
            RULES,
        )
    )["travel_rule"]
    assert c.result == "ESCALATE"  # type: ignore[attr-defined]


def test_network_not_allowed_blocks() -> None:
    c = by_name(evaluate(routine(network="ethereum-mainnet"), RULES))["allowed_networks"]
    assert (c.result, c.reason) == ("BLOCK", "NETWORK_NOT_ALLOWED")  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("amount", "auto", "hard"),
    [
        ("10000.00", "PASS", "PASS"),
        ("10000.01", "ESCALATE", "PASS"),
        ("100000.00", "ESCALATE", "PASS"),
        ("100000.01", "ESCALATE", "BLOCK"),
    ],
)
def test_limits(amount: str, auto: str, hard: str) -> None:
    r = by_name(evaluate(routine(amount=usdc(amount)), RULES))
    assert r["auto_limit"].result == auto and r["hard_max"].result == hard  # type: ignore[attr-defined]


def test_daily_caps_count_what_is_already_used() -> None:
    r = by_name(
        evaluate(
            routine(used_today_platform=usdc("48000.01"), used_today_counterparty=usdc("18000.01")), RULES
        )
    )
    assert (r["daily_cap_platform"].result, r["daily_cap_platform"].reason) == (
        "ESCALATE",
        "DAILY_CAP_PLATFORM",
    )  # type: ignore[attr-defined]
    assert r["daily_cap_counterparty"].reason == "DAILY_CAP_COUNTERPARTY"  # type: ignore[attr-defined]
    assert r["daily_cap_platform"].evidence == {
        "used": "48000.01",
        "this_payment": "2000.00",
        "cap": "50000.00",
    }  # type: ignore[attr-defined]


def test_daily_cap_exactly_reached_passes() -> None:
    r = by_name(evaluate(routine(used_today_platform=usdc("48000.00")), RULES))
    assert r["daily_cap_platform"].result == "PASS"  # type: ignore[attr-defined]


def test_new_wallet_and_unregistered_address_escalate() -> None:
    young = dataclasses.replace(
        routine().destination, first_seen_at=NOW - timedelta(days=2), last_changed_at=NOW - timedelta(days=2)
    )
    assert by_name(evaluate(routine(destination=young), RULES))["new_wallet"].reason == "NEW_WALLET"  # type: ignore[attr-defined]
    unreg = dataclasses.replace(
        routine().destination, registered=False, first_seen_at=NOW, last_changed_at=NOW
    )
    c = by_name(evaluate(routine(destination=unreg), RULES))["new_wallet"]
    assert c.reason == "NEW_WALLET" and c.evidence["address"] == ADDR  # type: ignore[attr-defined]


def test_changed_details_escalates_with_who_and_when() -> None:
    d = dataclasses.replace(
        routine().destination, last_changed_at=NOW - timedelta(days=3), last_changed_by="usr_pl"
    )
    c = by_name(evaluate(routine(destination=d), RULES))["changed_details"]
    assert c.reason == "CHANGED_DETAILS" and c.evidence["changed_by"] == "usr_pl"  # type: ignore[attr-defined]


def test_first_payment_escalates_and_above_norm_is_not_evaluated() -> None:
    r = by_name(
        evaluate(
            routine(counterparty=dataclasses.replace(routine().counterparty, payment_count=0, median=None)),
            RULES,
        )
    )
    assert r["first_payment"].reason == "FIRST_PAYMENT"  # type: ignore[attr-defined]
    assert r["above_norm"].result == "NOT_EVALUATED"  # type: ignore[attr-defined]


def test_above_norm() -> None:
    r = by_name(evaluate(routine(amount=usdc("5400.01")), RULES))  # median 1800, x3 = 5400
    assert r["above_norm"].reason == "ABOVE_NORM"  # type: ignore[attr-defined]
    assert by_name(evaluate(routine(amount=usdc("5400.00")), RULES))["above_norm"].result == "PASS"  # type: ignore[attr-defined]


def test_above_norm_ignores_history_in_another_currency() -> None:  # G-13
    cp = dataclasses.replace(routine().counterparty, median=Money.parse("10.00", "EUR"))
    assert by_name(evaluate(routine(counterparty=cp), RULES))["above_norm"].result == "NOT_EVALUATED"  # type: ignore[attr-defined]


def test_resubmission_after_block_escalates() -> None:
    c = by_name(evaluate(routine(recent_block_id="pay_01BLOCKED"), RULES))["resubmission_after_block"]
    assert c.reason == "RESUBMISSION_AFTER_BLOCK" and c.evidence["blocked_payment_id"] == "pay_01BLOCKED"  # type: ignore[attr-defined]


def test_agent_intent_without_a_verifiable_mandate_never_executes() -> None:
    # Mandate verification is built in S5 (MND-02); until then an agent intent fails closed.
    r = evaluate(routine(source="agent", mandate=Unavailable("mandate_verifier", "not_built")), RULES)
    assert r.checks[0].check == "mandate_scope"
    assert r.outcome != "EXECUTE"


def test_agent_intent_with_missing_mandate_blocks_and_short_circuits() -> None:
    r = evaluate(routine(source="agent", mandate=None), RULES)
    assert r.outcome == "BLOCK" and r.checks[0].reason == "MANDATE_MISSING"
    assert len(r.checks) == 1


def test_a_crashing_check_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from detent.policy import engine

    def boom(facts: Facts, rules: object) -> object:
        raise ZeroDivisionError("bug in a check")

    monkeypatch.setitem(engine.CHECKS, "auto_limit", boom)
    r = evaluate(routine(), RULES)
    c = by_name(r)["auto_limit"]
    assert (c.result, c.reason) == ("ESCALATE", "SYSTEM_UNAVAILABLE")  # type: ignore[attr-defined]
    assert c.evidence == {"dependency": "check:auto_limit", "error": "ZeroDivisionError"}  # type: ignore[attr-defined]
    assert r.outcome == "ESCALATE"


def test_checks_never_see_free_text() -> None:
    assert not any(f.name in {"notes", "reference", "invoice_text"} for f in dataclasses.fields(Facts))
