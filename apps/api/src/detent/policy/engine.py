"""The decision engine (POL-02 to POL-04, POL-09). Pure: no I/O, no clock, no model calls.

``evaluate`` runs every check in ``CHECKS`` order and combines the results: BLOCK if any check
blocks, else ESCALATE if any escalates, else EXECUTE. The mandate check runs first and short-circuits
on BLOCK (spec/04 Precedence). A check that raises is recorded as ESCALATE ``SYSTEM_UNAVAILABLE``, so
no error can ever turn into EXECUTE (invariant 9).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, Literal

from detent.domain.money import Money
from detent.policy.facts import CounterpartyFacts, Facts, Unavailable
from detent.policy.schema import RuleSet

Result = Literal["PASS", "ESCALATE", "BLOCK", "NOT_EVALUATED"]
Outcome = Literal["EXECUTE", "ESCALATE", "BLOCK"]


@dataclass(frozen=True, slots=True)
class CheckResult:
    check: str
    result: Result
    reason: str | None = None
    evidence: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"check": self.check, "result": self.result}
        if self.reason:
            out["reason"] = self.reason
        if self.evidence is not None:
            out["evidence"] = self.evidence
        return out


@dataclass(frozen=True, slots=True)
class Evaluation:
    outcome: Outcome
    checks: tuple[CheckResult, ...]

    @property
    def reasons(self) -> list[str]:
        return [c.reason for c in self.checks if c.reason and c.result in ("ESCALATE", "BLOCK")]

    @property
    def system_unavailable(self) -> bool:
        return "SYSTEM_UNAVAILABLE" in self.reasons


def _pass(name: str, **evidence: Any) -> CheckResult:
    return CheckResult(name, "PASS", evidence=evidence or None)


def _skip(name: str, note: str) -> CheckResult:
    return CheckResult(name, "NOT_EVALUATED", evidence={"note": note})


def _unavailable(name: str, u: Unavailable) -> CheckResult:
    return CheckResult(name, "ESCALATE", "SYSTEM_UNAVAILABLE", {"dependency": u.dependency, "error": u.error})


def _m(x: Money) -> str:
    return x.to_decimal_str()


def _cp(f: Facts) -> CounterpartyFacts:
    if f.counterparty is None:  # a counterparty check on a user payout: _run turns this into an escalation
        raise LookupError("no counterparty")
    return f.counterparty


# ---------------------------------------------------------------------------------------- checks
def mandate_scope(f: Facts, r: RuleSet) -> CheckResult:
    n = "mandate_scope"
    if f.source != "agent":
        return _skip(n, "platform intent: no mandate needed")
    if not r.checks.mandate_scope.enabled:
        # A rule set may not switch off the one check that authorises agents: fail closed.
        return CheckResult(
            n, "BLOCK", "MANDATE_MISSING", {"note": "mandate_scope is disabled for agent intents"}
        )
    if f.mandate is None:
        return CheckResult(n, "BLOCK", "MANDATE_MISSING", {})
    if isinstance(f.mandate, Unavailable):
        return _unavailable(n, f.mandate)
    if not f.mandate.valid:
        return CheckResult(
            n,
            "BLOCK",
            f.mandate.reason or "MANDATE_SIGNATURE_INVALID",
            f.mandate.evidence or {"mandate_id": f.mandate.id},
        )
    return CheckResult(n, "PASS", evidence=f.mandate.evidence or {"mandate_id": f.mandate.id})


def kyb_status(f: Facts, r: RuleSet) -> CheckResult:
    n, rule = "kyb_status", r.checks.kyb_status
    if rule is None:
        return _skip(n, "not configured")
    st = _cp(f).kyb_status
    ev = {"status": st}
    if st in rule.block_on:
        return CheckResult(n, "BLOCK", "KYB_FAILED", ev)
    if st in rule.escalate_on:
        return CheckResult(n, "ESCALATE", "KYB_PENDING", ev)
    return _pass(n, **ev)


def allowlist(f: Facts, r: RuleSet) -> CheckResult:
    n, rule = "allowlist", r.checks.allowlist
    if rule is None:
        return _skip(n, "not configured")
    cp = _cp(f)
    if rule.escalate_if_not_listed and not cp.allowlisted:
        return CheckResult(n, "ESCALATE", "NOT_ALLOWLISTED", {"counterparty_id": cp.id})
    return _pass(n)


def screening(f: Facts, r: RuleSet) -> CheckResult:
    n, rule = "screening", r.checks.screening
    if rule is None:
        return _skip(n, "not configured")
    if isinstance(f.screening, Unavailable):
        return _unavailable(n, f.screening)
    if f.screening.hit and rule.block_on_hit:
        return CheckResult(
            n, "BLOCK", "SCREENING_HIT", {"matched": f.screening.matched, "field": f.screening.field}
        )
    return _pass(n)


def travel_rule(f: Facts, r: RuleSet) -> CheckResult:
    n, rule = "travel_rule", r.checks.travel_rule
    if rule is None:
        return _skip(n, "not configured")
    threshold = rule.threshold_for(f.amount.currency)
    if threshold is None:
        return _skip(n, f"no threshold configured for {f.amount.currency.value}")
    if f.amount <= threshold:
        return _pass(n, threshold=_m(threshold))
    if isinstance(f.travel_rule, Unavailable):
        return _unavailable(n, f.travel_rule)
    data = {"originator": f.travel_rule.originator, "beneficiary": f.travel_rule.beneficiary}
    missing, mismatched = [], []
    for path in rule.required:
        party, _, field = path.partition(".")
        if not data.get(party, {}).get(field):
            missing.append(path)
    supplied = f.travel_rule.supplied if f.source == "platform" else None
    for party, values in (supplied or {}).items():
        for field, value in (values or {}).items() if isinstance(values, dict) else ():
            if value != data.get(party, {}).get(field):
                mismatched.append(f"{party}.{field}")
    if missing or mismatched:
        return CheckResult(
            n,
            "ESCALATE",
            "TRAVEL_RULE_MISSING",
            {"missing": missing, "mismatched": sorted(mismatched), "threshold": _m(threshold)},
        )
    return _pass(n, threshold=_m(threshold))


def allowed_networks(f: Facts, r: RuleSet) -> CheckResult:
    n = "allowed_networks"
    allowed = r.checks.allowed_networks.get(f.amount.currency, [])
    ev = {"network": f.network, "currency": f.amount.currency.value}
    if f.network not in allowed:
        return CheckResult(n, "BLOCK", "NETWORK_NOT_ALLOWED", ev)
    return _pass(n, **ev)


def hard_max(f: Facts, r: RuleSet) -> CheckResult:
    n, mx = "hard_max", r.checks.limits.hard_max_for(f.amount.currency)
    if mx is None:  # the schema requires it for every payable currency; fail closed anyway
        return CheckResult(n, "BLOCK", "ABOVE_HARD_MAX", {"note": "no maximum configured"})
    if f.amount > mx:
        return CheckResult(n, "BLOCK", "ABOVE_HARD_MAX", {"amount": _m(f.amount), "maximum": _m(mx)})
    return _pass(n)


def auto_limit(f: Facts, r: RuleSet) -> CheckResult:
    n, lim = "auto_limit", r.checks.limits.auto_limit_for(f.amount.currency)
    if lim is None:
        return CheckResult(n, "ESCALATE", "ABOVE_AUTO_LIMIT", {"note": "no auto limit configured"})
    if f.amount > lim:
        return CheckResult(n, "ESCALATE", "ABOVE_AUTO_LIMIT", {"amount": _m(f.amount), "auto_limit": _m(lim)})
    return _pass(n)


def _cap(n: str, reason: str, used: Money | Unavailable, cap: Money | None, amount: Money) -> CheckResult:
    if cap is None:
        return _skip(n, f"no cap configured for {amount.currency.value}")
    if isinstance(used, Unavailable):
        return _unavailable(n, used)
    ev = {"used": _m(used), "this_payment": _m(amount), "cap": _m(cap)}
    if used + amount > cap:
        return CheckResult(n, "ESCALATE", reason, ev)
    return CheckResult(n, "PASS", evidence=ev)


def daily_cap_platform(f: Facts, r: RuleSet) -> CheckResult:
    caps = r.checks.daily_caps
    cap = caps.platform.get(f.amount.currency) if caps and caps.platform else None
    return _cap("daily_cap_platform", "DAILY_CAP_PLATFORM", f.used_today_platform, cap, f.amount)


def daily_cap_counterparty(f: Facts, r: RuleSet) -> CheckResult:
    caps = r.checks.daily_caps
    cap = caps.per_counterparty.get(f.amount.currency) if caps and caps.per_counterparty else None
    return _cap("daily_cap_counterparty", "DAILY_CAP_COUNTERPARTY", f.used_today_counterparty, cap, f.amount)


def new_wallet(f: Facts, r: RuleSet) -> CheckResult:
    n, u = "new_wallet", r.checks.unusual
    if u is None:
        return _skip(n, "not configured")
    d = f.destination
    ev = {
        "address": d.address or d.account_masked,
        "first_seen_at": d.first_seen_at.isoformat(),
        "registered": d.registered,
    }
    if not d.registered or f.now - d.first_seen_at < timedelta(days=u.new_wallet_days):
        return CheckResult(n, "ESCALATE", "NEW_WALLET", ev)
    return _pass(n)


def changed_details(f: Facts, r: RuleSet) -> CheckResult:
    n, u = "changed_details", r.checks.unusual
    if u is None:
        return _skip(n, "not configured")
    d = f.destination
    if (
        d.registered
        and d.last_changed_at > d.first_seen_at
        and f.now - d.last_changed_at < timedelta(days=u.changed_details_days)
    ):
        return CheckResult(
            n,
            "ESCALATE",
            "CHANGED_DETAILS",
            {
                "destination_id": d.id,
                "current": d.address or d.account_masked,
                "previous": d.previous,
                "last_changed_at": d.last_changed_at.isoformat(),
                "changed_by": d.last_changed_by,
            },
        )
    return _pass(n)


def first_payment(f: Facts, r: RuleSet) -> CheckResult:
    n, u = "first_payment", r.checks.unusual
    if u is None or u.first_payment == "off":
        return _skip(n, "not configured")
    if _cp(f).payment_count == 0:
        return CheckResult(n, "ESCALATE", "FIRST_PAYMENT", {"counterparty_payment_count": 0})
    return _pass(n)


def above_norm(f: Facts, r: RuleSet) -> CheckResult:
    n, u = "above_norm", r.checks.unusual
    if u is None:
        return _skip(n, "not configured")
    cp = _cp(f)
    if cp.payment_count < u.above_norm_min_history or cp.median is None:
        return _skip(n, f"not evaluated: fewer than {u.above_norm_min_history} confirmed payments")
    if cp.median.currency != f.amount.currency:  # G-13
        return _skip(n, f"not evaluated: no confirmed history in {f.amount.currency.value}")
    ratio_limit = Decimal(cp.median.amount_minor) * u.above_norm_multiplier
    ratio = (Decimal(f.amount.amount_minor) / Decimal(cp.median.amount_minor)).quantize(Decimal("0.01"))
    ev = {
        "amount": _m(f.amount),
        "median": _m(cp.median),
        "ratio": str(ratio),
        "multiplier": str(u.above_norm_multiplier),
    }
    if Decimal(f.amount.amount_minor) > ratio_limit:
        return CheckResult(n, "ESCALATE", "ABOVE_NORM", ev)
    return CheckResult(n, "PASS", evidence=ev)


def user_verified(f: Facts, r: RuleSet) -> CheckResult:
    """User payout profile only (G-10): the platform's typed flag. The user's KYC is the platform's job."""
    n = "user_verified"
    if f.user is None:
        raise LookupError("no user account")
    ev = {
        "user_account_ref": f.user.ref,
        "user_verified": f.user.verified,
        "set_by": f.user.verified_set_by,
        "set_at": f.user.verified_set_at.isoformat(),
    }
    if not f.user.verified:
        return CheckResult(n, "ESCALATE", "USER_NOT_VERIFIED", ev)
    return _pass(n, **ev)


def resubmission_after_block(f: Facts, r: RuleSet) -> CheckResult:
    n, rule = "resubmission_after_block", r.checks.resubmission_after_block
    if rule is None:
        return _skip(n, "not configured")
    if f.recent_block_id:
        return CheckResult(
            n,
            "ESCALATE",
            "RESUBMISSION_AFTER_BLOCK",
            {"blocked_payment_id": f.recent_block_id, "window_hours": rule.window_hours},
        )
    return _pass(n)


Check = Callable[[Facts, RuleSet], CheckResult]

# Order is the order a reviewer reads them. The mandate check must stay first.
CHECKS: dict[str, Check] = {
    "mandate_scope": mandate_scope,
    "kyb_status": kyb_status,
    "allowlist": allowlist,
    "screening": screening,
    "travel_rule": travel_rule,
    "allowed_networks": allowed_networks,
    "hard_max": hard_max,
    "auto_limit": auto_limit,
    "daily_cap_platform": daily_cap_platform,
    "daily_cap_counterparty": daily_cap_counterparty,
    "new_wallet": new_wallet,
    "changed_details": changed_details,
    "first_payment": first_payment,
    "above_norm": above_norm,
    "resubmission_after_block": resubmission_after_block,
}


def _run(name: str, check: Check, facts: Facts, rules: RuleSet) -> CheckResult:
    try:
        res = check(facts, rules)
    except Exception as exc:  # fail closed (POL-09): a broken check can never pass
        return CheckResult(
            name,
            "ESCALATE",
            "SYSTEM_UNAVAILABLE",
            {"dependency": f"check:{name}", "error": type(exc).__name__},
        )
    if res.check != name or res.result not in ("PASS", "ESCALATE", "BLOCK", "NOT_EVALUATED"):
        return CheckResult(
            name, "ESCALATE", "SYSTEM_UNAVAILABLE", {"dependency": f"check:{name}", "error": "BadResult"}
        )
    return res


def combine(results: tuple[CheckResult, ...]) -> Outcome:
    kinds = {c.result for c in results}
    if "BLOCK" in kinds:
        return "BLOCK"
    if "ESCALATE" in kinds:
        return "ESCALATE"
    return "EXECUTE"


# The user payout profile (spec/04): checks about business counterparties do not apply to the platform's own
# end users; every safety check still runs, and user_verified runs in kyb_status's place.
USER_PROFILE_SKIPS = frozenset(
    {"kyb_status", "allowlist", "first_payment", "above_norm", "daily_cap_counterparty"}
)


def _plan(facts: Facts) -> list[tuple[str, Check | None]]:
    if facts.profile == "counterparty":
        return list(CHECKS.items())
    plan: list[tuple[str, Check | None]] = []
    for name, check in CHECKS.items():
        if name == "kyb_status":
            plan.append(("user_verified", user_verified))
        plan.append((name, None if name in USER_PROFILE_SKIPS else check))
    return plan


def evaluate(facts: Facts, rules: RuleSet) -> Evaluation:
    results: list[CheckResult] = []
    for name, check in _plan(facts):
        if check is None:
            results.append(_skip(name, "user payout profile: a business counterparty check"))
            continue
        res = _run(name, check, facts, rules)
        results.append(res)
        if name == "mandate_scope" and res.result == "BLOCK":
            break  # the other checks would act on an unauthorised request
    checks = tuple(results)
    return Evaluation(combine(checks), checks)
