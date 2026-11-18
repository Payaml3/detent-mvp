"""The rule-set format (spec/04-policy.md, POL-01) and its loader.

A rule set is a YAML document owned by the client. ``load_ruleset`` validates it against the models
below and reports every problem with its line number. A loaded rule set is frozen and identified by
its ``version`` and the SHA-256 of its exact text.

Money amounts are decimal strings, parsed exactly into minor units; a float is rejected
(invariant 15).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from detent.domain.money import Currency, Money, MoneyError

KybStatus = Literal["verified", "pending", "failed", "unknown"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _money_map(v: Any) -> Any:
    if not isinstance(v, dict):
        return v
    out: dict[str, str] = {}
    for cur, amount in v.items():
        if not isinstance(amount, str):
            raise ValueError(f'{cur}: amount must be a decimal string such as "1000.00", not {amount!r}')
        try:
            Money.parse(amount, cur)
        except (MoneyError, ValueError) as exc:
            raise ValueError(f"{cur}: {exc}") from exc
        out[cur] = amount
    return out


class MoneyMap(_Frozen):
    """Amounts per currency, kept as the client wrote them."""

    amounts: dict[Currency, str]

    def get(self, currency: Currency | str) -> Money | None:
        cur = Currency(currency)
        raw = self.amounts.get(cur)
        return None if raw is None else Money.parse(raw, cur)


def _to_moneymap(v: Any) -> Any:
    v = _money_map(v)
    return {"amounts": v} if isinstance(v, dict) else v


class Enabled(_Frozen):
    enabled: bool = True


class KybCheck(_Frozen):
    block_on: list[KybStatus] = Field(default_factory=list)
    escalate_on: list[KybStatus] = Field(default_factory=list)


class AllowlistCheck(_Frozen):
    escalate_if_not_listed: bool = True


class ScreeningCheck(_Frozen):
    provider: Literal["mock"] = "mock"
    list: str | None = None
    block_on_hit: bool = True


class TravelRuleCheck(_Frozen):
    threshold: MoneyMap
    required: list[str]

    @field_validator("threshold", mode="before")
    @classmethod
    def _t(cls, v: Any) -> Any:
        return _to_moneymap(v)

    def threshold_for(self, currency: Currency | str) -> Money | None:
        return self.threshold.get(currency)


class Limits(_Frozen):
    auto_limit: MoneyMap
    hard_max: MoneyMap

    @field_validator("auto_limit", "hard_max", mode="before")
    @classmethod
    def _a(cls, v: Any) -> Any:
        return _to_moneymap(v)

    def auto_limit_for(self, currency: Currency | str) -> Money | None:
        return self.auto_limit.get(currency)

    def hard_max_for(self, currency: Currency | str) -> Money | None:
        return self.hard_max.get(currency)


class DailyCaps(_Frozen):
    platform: MoneyMap | None = None
    per_counterparty: MoneyMap | None = None

    @field_validator("platform", "per_counterparty", mode="before")
    @classmethod
    def _c(cls, v: Any) -> Any:
        return _to_moneymap(v)


class Unusual(_Frozen):
    new_wallet_days: int = Field(ge=0)
    changed_details_days: int = Field(ge=0)
    first_payment: Literal["escalate", "off"] = "escalate"
    above_norm_multiplier: Decimal = Field(gt=0)
    above_norm_min_history: int = Field(ge=1)

    @field_validator("above_norm_multiplier", mode="before")
    @classmethod
    def _exact(cls, v: Any) -> Any:
        # A ratio, not money: read YAML's number through its text so 3.0 stays exactly 3.0.
        return Decimal(str(v)) if isinstance(v, int | float) else v


class Resubmission(_Frozen):
    window_hours: int = Field(ge=0)
    action: Literal["escalate"] = "escalate"


class Checks(_Frozen):
    mandate_scope: Enabled = Enabled()
    kyb_status: KybCheck | None = None
    allowlist: AllowlistCheck | None = None
    screening: ScreeningCheck | None = None
    travel_rule: TravelRuleCheck | None = None
    allowed_networks: dict[Currency, list[str]]
    limits: Limits
    daily_caps: DailyCaps | None = None
    unusual: Unusual | None = None
    resubmission_after_block: Resubmission | None = None

    @model_validator(mode="after")
    def _limits_cover_every_currency(self) -> Checks:
        # A currency that can be paid must have both limits; a missing limit would silently loosen.
        for cur in self.allowed_networks:
            for name in ("auto_limit", "hard_max"):
                if getattr(self.limits, name).get(cur) is None:
                    raise ValueError(
                        f"limits.{name} has no amount for {cur.value}, which allowed_networks permits"
                    )
        return self


class OwnerRule(_Frozen):
    match: dict[str, str]
    owner_role: str
    backup_role: str


class Retry(_Frozen):
    max_attempts: int = Field(ge=1)
    retryable: list[Literal["TECHNICAL_RETRYABLE"]]
    backoff_seconds: list[int]


class Execution(_Frozen):
    max_decision_age_seconds: int = Field(ge=1)
    unknown_stuck_after: str


class RuleSetDoc(_Frozen):
    version: int = Field(ge=1)
    platform: str
    fail_safe: Literal["hold", "manual_queue"]
    attestation: str | None = None
    currency_defaults: dict[Currency, int] | None = None
    checks: Checks
    deadlines: dict[str, str] = Field(default_factory=dict)
    owners: list[OwnerRule] = Field(default_factory=list)
    retry: Retry | None = None  # C-11 (D-23)
    execution: Execution | None = None  # C-11 (D-23)


class RuleSet(RuleSetDoc):
    content_hash: str
    text: str


@dataclass(frozen=True, slots=True)
class RuleSetProblem:
    path: str
    line: int | None
    message: str

    def __str__(self) -> str:
        where = f"line {self.line}" if self.line else "unknown line"
        return f"{where}: {self.path}: {self.message}"


class RuleSetError(ValueError):
    def __init__(self, errors: list[RuleSetProblem]) -> None:
        self.errors = errors
        super().__init__("invalid rule set:\n" + "\n".join(f"  {e}" for e in errors))


def _line_of(root: yaml.Node | None, loc: tuple[int | str, ...]) -> int | None:
    """Follow a pydantic error location through the YAML node tree; return the deepest line found."""
    node = root
    line = node.start_mark.line + 1 if node is not None else None
    for part in loc:
        if isinstance(node, yaml.MappingNode):
            nxt = None
            for k, v in node.value:
                if str(k.value) == str(part):
                    nxt = v
                    line = k.start_mark.line + 1
                    break
            if nxt is None:
                break
            node = nxt
            line = node.start_mark.line + 1
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int) and part < len(node.value):
            node = node.value[part]
            line = node.start_mark.line + 1
        else:
            continue  # pydantic adds synthetic parts (e.g. "amounts"); skip them
    return line


def load_ruleset(text: str) -> RuleSet:
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise RuleSetError(
            [RuleSetProblem("(document)", mark.line + 1 if mark else 1, str(getattr(exc, "problem", exc)))]
        ) from exc
    if not isinstance(data, dict):
        raise RuleSetError([RuleSetProblem("(document)", 1, "a rule set must be a YAML mapping")])
    try:
        RuleSetDoc.model_validate(data)
    except ValidationError as exc:
        problems = []
        for e in exc.errors():
            loc = tuple(e["loc"])
            path = ".".join(str(p) for p in loc if p != "amounts") or "(document)"
            problems.append(RuleSetProblem(path, _line_of(root, loc), e["msg"]))
        raise RuleSetError(problems) from exc
    digest = hashlib.sha256(text.encode()).hexdigest()
    return RuleSet.model_validate({**data, "content_hash": digest, "text": text})
