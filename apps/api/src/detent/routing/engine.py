"""The routing engine (RAL-06, spec/06 Routing). Runs only after EXECUTE: a BLOCK never gets here.

1. Candidates: the organisation's enabled rails in the payment's currency.
2. Eligibility: the network is the intent's own, or the intent allows a network switch and the payee has
   a verified destination on that network; the rail has not definitively failed this payment; an
   adapter exists; the adapter says yes (balance, gas, limits); the pre-funded limit has room.
3. Score (lower wins): w_cost * norm(fee) + w_speed * norm(expected seconds)
   + w_success * (1 - success rate) + w_liquidity * (1 - liquidity headroom). Ties go to the rail ID.
4. Every candidate, its score and the reason for the winner are stored on the decision.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from detent.domain.money import Currency, Money
from detent.rails.base import IntentView, RailAdapter

DEFAULT_WEIGHTS = {
    "cost": Decimal("0.4"),
    "speed": Decimal("0.2"),
    "success": Decimal("0.3"),
    "liquidity": Decimal("0.1"),
}
HISTORY = 50  # recent attempts used for a rail's success rate


@dataclass
class Candidate:
    rail: str
    eligible: bool
    reason: str | None = None
    destination_address: str | None = None
    fee_minor: int = 0
    expected_seconds: int = 0
    success_rate: Decimal = Decimal(1)
    headroom: Decimal = Decimal(1)
    score: Decimal | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "rail": self.rail,
            "eligible": self.eligible,
            "reason": self.reason,
            "score": str(self.score) if self.score is not None else None,
            "fee_minor": self.fee_minor,
            "expected_seconds": self.expected_seconds,
            "success_rate": str(self.success_rate),
            "liquidity_headroom": str(self.headroom),
        }


@dataclass
class Route:
    chosen: Candidate | None
    candidates: list[Candidate] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "chosen": self.chosen.rail if self.chosen else None,
            "reason": (f"lowest score {self.chosen.score}" if self.chosen else "no eligible rail"),
            "candidates": [c.to_json() for c in self.candidates],
        }


def _success_rate(conn: Connection, org_id: str, rail: str) -> Decimal:
    rows = (
        conn.execute(
            text(
                "SELECT status FROM attempts WHERE org_id=:o AND rail_id=:r AND status IN "
                "('CONFIRMED','FAILED') "
                "ORDER BY created_at DESC LIMIT :n"
            ),
            {"o": org_id, "r": rail, "n": HISTORY},
        )
        .scalars()
        .all()
    )
    if not rows:
        return Decimal(1)
    return Decimal(sum(1 for s in rows if s == "CONFIRMED")) / Decimal(len(rows))


def _headroom(conn: Connection, org_id: str, rail: Any, amount: Money, day: str) -> Decimal:
    if rail.prefunded_daily_limit_minor is None:
        return Decimal(1)
    used = (
        conn.execute(
            text("SELECT amount_minor FROM counters WHERE org_id=:o AND scope=:s AND period=:p"),
            {"o": org_id, "s": f"prefund:{rail.id}", "p": day},
        ).scalar_one_or_none()
        or 0
    )
    room = int(rail.prefunded_daily_limit_minor) - int(used) - amount.amount_minor
    return max(Decimal(0), Decimal(room) / Decimal(int(rail.prefunded_daily_limit_minor)))


def _norm(v: int, top: int) -> Decimal:
    return Decimal(v) / Decimal(top) if top else Decimal(0)


def route(
    conn: Connection,
    adapters: Mapping[str, RailAdapter],
    *,
    org_id: str,
    payment: Any,
    day: str,
    exclude: set[str] | None = None,
) -> Route:
    amount = Money(int(payment.amount_minor), Currency(payment.currency))
    rails = conn.execute(
        text("SELECT * FROM rails WHERE org_id=:o AND enabled AND currency=:c ORDER BY id"),
        {"o": org_id, "c": payment.currency},
    ).all()
    failed_on = set(
        conn.execute(
            text(
                "SELECT rail_id FROM attempts WHERE org_id=:o AND payment_id=:p AND status='FAILED' "
                "AND failure_class IN ('TECHNICAL_FINAL','REJECTED_BY_RAIL')"
            ),
            {"o": org_id, "p": payment.id},
        )
        .scalars()
        .all()
    )
    dests = (
        {
            r.network: r.address
            for r in conn.execute(
                text(
                    "SELECT network, coalesce(address, account_masked) AS address FROM destinations "
                    "WHERE org_id=:o AND counterparty_id=:c AND verified"
                ),
                {"o": org_id, "c": payment.counterparty_id},
            )
        }
        if payment.counterparty_id
        else {}
    )
    weights = DEFAULT_WEIGHTS
    out: list[Candidate] = []
    for r in rails:
        c = Candidate(
            r.id, False, fee_minor=int(r.est_fee_minor or 0), expected_seconds=int(r.est_seconds or 1)
        )
        out.append(c)
        if r.weights:
            weights = {k: Decimal(str(v)) for k, v in dict(r.weights).items()}
        if r.id == payment.network_constraint:
            c.destination_address = payment.address or getattr(payment, "account_masked", None)
        elif payment.allow_network_switch and r.id in dests:
            c.destination_address = dests[r.id]
        else:
            c.reason = "network constraint"
            continue
        if r.id in failed_on or r.id in (exclude or set()):
            c.reason = "failed this payment"
            continue
        adapter = adapters.get(r.id)
        if adapter is None:
            c.reason = "no adapter configured"
            continue
        el = adapter.eligible(IntentView(payment.id, amount, r.id, c.destination_address))
        if not el.eligible:
            c.reason = el.reason
            continue
        c.headroom = _headroom(conn, org_id, r, amount, day)
        if r.prefunded_daily_limit_minor is not None and c.headroom <= 0:
            c.reason = "PREFUNDED_LIMIT"
            continue
        c.success_rate = _success_rate(conn, org_id, r.id)
        c.eligible = True
    eligible = [c for c in out if c.eligible]
    top_fee = max((c.fee_minor for c in eligible), default=0)
    top_secs = max((c.expected_seconds for c in eligible), default=0)
    for c in eligible:
        c.score = (
            weights.get("cost", Decimal(0)) * _norm(c.fee_minor, top_fee)
            + weights.get("speed", Decimal(0)) * _norm(c.expected_seconds, top_secs)
            + weights.get("success", Decimal(0)) * (1 - c.success_rate)
            + weights.get("liquidity", Decimal(0)) * (1 - c.headroom)
        ).quantize(Decimal("0.0001"))
    chosen = min(eligible, key=lambda c: (c.score, c.rail), default=None)
    return Route(chosen, out)


def store_route(conn: Connection, org_id: str, payment_id: str, r: Route) -> None:
    conn.execute(
        text(
            "UPDATE decisions SET route = CAST(:r AS jsonb) WHERE org_id=:o AND id = (SELECT id FROM "
            "decisions "
            "WHERE org_id=:o AND payment_id=:p ORDER BY decided_at DESC, id DESC LIMIT 1)"
        ),
        {"r": json.dumps(r.to_json()), "o": org_id, "p": payment_id},
    )
