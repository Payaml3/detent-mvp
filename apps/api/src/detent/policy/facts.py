"""Typed facts the policy reads (spec/04 "Typed inputs only").

There is deliberately no field for notes, references or any other free text: the policy never reads
it (invariant 11). The decision service gathers these facts from the database before evaluation; a
dependency that fails while gathering is passed in as ``Unavailable`` so the matching check fails
closed (POL-09).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from detent.domain.money import Money


@dataclass(frozen=True, slots=True)
class Unavailable:
    """A dependency that could not be read. The check that needs it returns SYSTEM_UNAVAILABLE."""

    dependency: str
    error: str


@dataclass(frozen=True, slots=True)
class CounterpartyFacts:
    id: str
    name: str
    kyb_status: Literal["verified", "pending", "failed", "unknown"]
    allowlisted: bool
    payment_count: int
    median: Money | None  # of confirmed payments (INT-04)


@dataclass(frozen=True, slots=True)
class UserFacts:
    """An end user of the platform (USR-01, G-10). The platform owns the user's KYC; the policy reads only
    its typed ``user_verified`` flag."""

    ref: str
    verified: bool
    verified_set_by: str
    verified_set_at: datetime


@dataclass(frozen=True, slots=True)
class DestinationFacts:
    id: str | None  # None when the address was not registered before this intent (G-01)
    registered: bool
    address: str | None
    account_masked: str | None
    first_seen_at: datetime
    last_changed_at: datetime
    last_changed_by: str | None
    previous: str | None = None  # the address or account before the last change, from the audit log


@dataclass(frozen=True, slots=True)
class ScreeningResult:
    hit: bool
    matched: str | None = None
    field: Literal["address", "name"] | None = None


@dataclass(frozen=True, slots=True)
class TravelRuleFacts:
    """Registry values (organisation settings and the counterparty registry), never agent text (D-03)."""

    originator: dict[str, str | None]
    beneficiary: dict[str, str | None]
    supplied: dict[str, Any] | None  # what a platform intent sent; must match the registry


@dataclass(frozen=True, slots=True)
class MandateFacts:
    """The result of verifying a signed mandate against an intent (MND-02)."""

    id: str
    valid: bool
    reason: str | None = None
    evidence: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Facts:
    now: datetime
    source: Literal["platform", "agent"]
    amount: Money
    network: str
    counterparty: CounterpartyFacts | None  # None for a user payout
    destination: DestinationFacts
    screening: ScreeningResult | Unavailable
    travel_rule: TravelRuleFacts | Unavailable
    used_today_platform: Money | Unavailable
    used_today_counterparty: Money | Unavailable
    recent_block_id: str | None
    mandate: MandateFacts | Unavailable | None
    user: UserFacts | None = None  # set for a user payout (spec/04 User payouts)

    @property
    def profile(self) -> Literal["counterparty", "user"]:
        return "user" if self.user is not None else "counterparty"
