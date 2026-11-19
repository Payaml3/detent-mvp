"""Deposit checks (LED-05, spec/04 "Deposit checks"). Pure: facts in, results out, no I/O.

- token and network match the deposit intent: BLOCK on a mismatch (then a deposit exception);
- sender screening: BLOCK on a hit;
- amount within the organisation's tolerance of the expected amount (G-11, default 0): ESCALATE;
- the intent is still valid (G-21) and open: ESCALATE otherwise;
- no intent at all for the address or reference: ESCALATE NO_INTENT.

Precedence is the same as for payouts: BLOCK over ESCALATE over EXECUTE. EXECUTE means "credit".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from detent.policy.engine import CheckResult
from detent.policy.facts import ScreeningResult


@dataclass(frozen=True, slots=True)
class IntentFacts:
    id: str
    account_ref: str
    currency: str
    network: str
    expected_minor: int | None
    status: str
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class DepositFacts:
    amount_minor: int
    currency: str
    network: str
    sender: str
    received_at: datetime
    intent: IntentFacts | None
    screening: ScreeningResult
    tolerance_minor: int


def evaluate_deposit(f: DepositFacts) -> tuple[str, list[CheckResult]]:
    checks: list[CheckResult] = []
    i = f.intent
    if i is None:
        checks.append(
            CheckResult("deposit_intent", "ESCALATE", "NO_INTENT", {"amount_minor": f.amount_minor})
        )
    else:
        if i.network != f.network:
            checks.append(
                CheckResult(
                    "network_match", "BLOCK", "NETWORK_MISMATCH", {"intent": i.network, "received": f.network}
                )
            )
        elif i.currency != f.currency:
            checks.append(
                CheckResult(
                    "token_match", "BLOCK", "TOKEN_MISMATCH", {"intent": i.currency, "received": f.currency}
                )
            )
        else:
            checks.append(CheckResult("network_match", "PASS"))
        if i.status != "OPEN":
            checks.append(CheckResult("deposit_intent", "ESCALATE", "INTENT_NOT_OPEN", {"status": i.status}))
        elif i.expires_at is not None and f.received_at > i.expires_at:
            checks.append(
                CheckResult(
                    "deposit_intent", "ESCALATE", "INTENT_EXPIRED", {"expired_at": i.expires_at.isoformat()}
                )
            )
        else:
            checks.append(CheckResult("deposit_intent", "PASS"))
        if i.expected_minor is not None and abs(f.amount_minor - i.expected_minor) > f.tolerance_minor:
            checks.append(
                CheckResult(
                    "amount",
                    "ESCALATE",
                    "AMOUNT_MISMATCH",
                    {
                        "expected_minor": i.expected_minor,
                        "received_minor": f.amount_minor,
                        "tolerance_minor": f.tolerance_minor,
                    },
                )
            )
        else:
            checks.append(CheckResult("amount", "PASS"))
    if f.screening.hit:
        checks.append(
            CheckResult(
                "screening", "BLOCK", "SCREENING_HIT", {"sender": f.sender, "matched": f.screening.matched}
            )
        )
    else:
        checks.append(CheckResult("screening", "PASS"))
    results = {c.result for c in checks}
    outcome = "BLOCK" if "BLOCK" in results else "ESCALATE" if "ESCALATE" in results else "EXECUTE"
    return outcome, checks
