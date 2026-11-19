"""Shared builders for policy tests: a routine payout whose every check passes."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

from detent.domain.money import Money
from detent.policy.facts import (
    CounterpartyFacts,
    DestinationFacts,
    Facts,
    ScreeningResult,
    TravelRuleFacts,
)
from detent.policy.schema import load_ruleset
from detent.settings import REPO_ROOT

RULES = load_ruleset((REPO_ROOT / "fixtures" / "policy" / "default-policy.yaml").read_text())
NOW = datetime(2026, 12, 3, 10, 0, tzinfo=UTC)
ADDR = "0x5aAe000000000000000000000000000000009F3c"


def usdc(s: str) -> Money:
    return Money.parse(s, "USDC")


def routine(**kw: object) -> Facts:
    """A routine payout to a long-standing, verified supplier: every check passes."""
    base = Facts(
        now=NOW,
        source="platform",
        amount=usdc("2000.00"),
        network="base-sepolia",
        counterparty=CounterpartyFacts(
            id="cpt_x",
            name="Supplier Ltd (fictional)",
            kyb_status="verified",
            allowlisted=True,
            payment_count=10,
            median=usdc("1800.00"),
        ),
        destination=DestinationFacts(
            id="dst_x",
            registered=True,
            address=ADDR,
            account_masked=None,
            first_seen_at=NOW - timedelta(days=200),
            last_changed_at=NOW - timedelta(days=200),
            last_changed_by=None,
        ),
        screening=ScreeningResult(hit=False),
        travel_rule=TravelRuleFacts(
            originator={"name": "Demo Platform Ltd (fictional)", "account": "0xPLATFORM"},
            beneficiary={"name": "Supplier Ltd (fictional)", "account": ADDR},
            supplied=None,
        ),
        used_today_platform=usdc("0"),
        used_today_counterparty=usdc("0"),
        recent_block_id=None,
        mandate=None,
    )
    return dataclasses.replace(base, **kw)  # type: ignore[arg-type]


BASE = (REPO_ROOT / "fixtures" / "policy" / "default-policy.yaml").read_text()


def v2(*edits: tuple[str, str]) -> str:
    """The fixture rule set as version 2, with each (old, new) text edit applied once (POL-07 tests)."""
    text = BASE.replace("version: 1", "version: 2", 1)
    for old, new in edits:
        assert old in text, old
        text = text.replace(old, new, 1)
    return text
