"""The simulated chain rail for sandbox organisations (RAL-11, spec/06).

It stands in for Base Sepolia and Ethereum Sepolia behind the same adapter contract as `EvmAdapter`: the
execution layer assigns a nonce, "signs" the transaction (a deterministic hash) and stores it before
`submit`, and an UNKNOWN attempt is resolved only from what the simulated chain recorded. Nothing leaves
the database, so a sandbox payout settles in about a second and drains no faucet wallet.

The chain is a table (`simchain_transfers`) that only grows. The sandbox test values (SBX-01, spec/06)
apply on the first submission of a transaction:

- an amount ending in `.13`: `timeout_after_forward`. The chain takes the transaction but the answer is
  lost, so the attempt is UNKNOWN; the transaction becomes visible a few seconds later and resolution
  finds it CONFIRMED;
- an amount ending in `.42` on a payment's first attempt: `receipt_status_0`. The transaction is mined
  and reverts, so the attempt FAILS (TECHNICAL_FINAL) and failover may move the payment, under the same
  payment ID, to the other simulated network.

An amount is a test value only when it has nothing past the cents: 10.13 is, 10.1301 is not.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from sqlalchemy import Engine, text

from detent.clock import Clock
from detent.domain.money import Currency, Money
from detent.domain.states import FailureClass
from detent.rails.base import (
    AttemptView,
    Eligibility,
    Health,
    IntentView,
    ObservedTransfer,
    Prepared,
    Quote,
    RailError,
    Resolved,
    StatusResult,
    SubmitResult,
)

SIMULATED_NETWORKS = ("base-sepolia", "eth-sepolia")
TIMEOUT_CENTS, REVERT_CENTS = 13, 42
LATE_SECONDS = 6  # a `.13` transaction becomes visible after the first resolution poll (+5 s)
_RAW_PREFIX = "sim:"


def cents(amount: Money) -> int | None:
    """The two digits after the decimal point when the amount has no smaller digits (10.13 -> 13), else
    None: 10.1301 USDC is not a test value."""
    unit = 10 ** (amount.currency.decimals - 2)
    if amount.amount_minor % unit:
        return None
    return int((amount.amount_minor // unit) % 100)


def sim_address(org_id: str) -> str:
    """The organisation's simulated sending wallet: a fixed address, clearly not a real key's."""
    return "0x" + hashlib.sha256(f"simchain-wallet:{org_id}".encode()).hexdigest()[:40]


class SimChainAdapter:
    def __init__(self, *, rail_id: str, org_id: str, engine: Engine, clock: Clock) -> None:
        if rail_id not in SIMULATED_NETWORKS:
            raise ValueError(f"no simulated chain for {rail_id}")
        self.rail_id = rail_id
        self.org_id = org_id
        self.simulated = True
        self._engine = engine
        self._clock = clock

    # ------------------------------------------------------------------------------ helpers
    @property
    def from_address(self) -> str:
        return sim_address(self.org_id)

    def explorer_url(self, tx_hash: str) -> str | None:
        return None  # a simulated transaction has no public explorer page

    def _row(self, tx_hash: str | None) -> Any:
        if not tx_hash:
            return None
        with self._engine.connect() as conn:
            return conn.execute(
                text(
                    "SELECT tx_hash, seq, nonce, amount_minor, outcome, test_value, visible_at, to_address "
                    "FROM simchain_transfers WHERE org_id=:o AND rail_id=:r AND tx_hash=:h"
                ),
                {"o": self.org_id, "r": self.rail_id, "h": tx_hash.lower()},
            ).one_or_none()

    def _evidence(self, row: Any) -> dict[str, Any]:
        return {
            "tx_hash": row.tx_hash,
            "block": int(row.seq),
            "confirmations": 1,
            "receipt_status": 1 if row.outcome == "confirmed" else 0,
            "simulated": True,
            **({"test_value": row.test_value} if row.test_value else {}),
        }

    # ------------------------------------------------------------------------------ contract
    def eligible(self, intent: IntentView) -> Eligibility:
        if intent.amount.currency is not Currency.USDC:
            return Eligibility(False, "CURRENCY_NOT_SUPPORTED")
        if intent.network != self.rail_id:
            return Eligibility(False, "NETWORK_MISMATCH")
        if not intent.destination_address:
            return Eligibility(False, "NO_DESTINATION_ADDRESS")
        return Eligibility(True)

    def quote(self, intent: IntentView) -> Quote:
        return Quote(fee_minor=0, fee_currency="wei", expected_seconds=1)

    def pending_nonce(self) -> int:
        with self._engine.connect() as conn:
            top = conn.execute(
                text(
                    "SELECT max(nonce) FROM simchain_transfers WHERE org_id=:o AND rail_id=:r "
                    "AND from_address=:a"
                ),
                {"o": self.org_id, "r": self.rail_id, "a": self.from_address},
            ).scalar_one_or_none()
        return 0 if top is None else int(top) + 1

    def prepare(self, attempt: AttemptView, nonce: int) -> Prepared:
        if not attempt.destination_address:
            raise RailError(FailureClass.TECHNICAL_FINAL, "no destination address")
        if attempt.amount.currency is not Currency.USDC:
            raise RailError(FailureClass.TECHNICAL_FINAL, f"{self.rail_id} carries USDC only")
        body = {
            "rail": self.rail_id,
            "from": self.from_address,
            "to": attempt.destination_address.lower(),
            "nonce": nonce,
            "amount_minor": attempt.amount.amount_minor,
            "payment_id": attempt.payment_id,
            "attempt_no": attempt.attempt_no,
        }
        raw = _RAW_PREFIX + json.dumps(body, sort_keys=True, separators=(",", ":"))
        tx_hash = "0x" + hashlib.sha256(raw.encode()).hexdigest()
        return Prepared(nonce=nonce, raw_tx=raw, tx_hash=tx_hash, from_address=self.from_address)

    def submit(self, attempt: AttemptView) -> SubmitResult:
        """Broadcast the stored transaction. The same bytes twice are one transaction (as on a chain)."""
        if not attempt.raw_tx or not attempt.tx_hash or not attempt.raw_tx.startswith(_RAW_PREFIX):
            raise RailError(FailureClass.TECHNICAL_FINAL, "attempt has no simulated signed transaction")
        body = json.loads(attempt.raw_tx[len(_RAW_PREFIX) :])
        now = self._clock.now()
        c = cents(attempt.amount)
        test_value, outcome, visible = None, "confirmed", now
        if c == TIMEOUT_CENTS:
            test_value, visible = "timeout_after_forward", now + timedelta(seconds=LATE_SECONDS)
        elif c == REVERT_CENTS and attempt.attempt_no == 1:
            test_value, outcome = "receipt_status_0", "reverted"
        with self._engine.begin() as conn:
            inserted = conn.execute(
                text(
                    "INSERT INTO simchain_transfers (org_id, rail_id, tx_hash, from_address, to_address, "
                    "nonce, amount_minor, outcome, test_value, attempt_id, submitted_at, visible_at) VALUES "
                    "(:o, :r, :h, :f, :t, :n, :a, :out, :tv, :att, :now, :vis) ON CONFLICT DO NOTHING "
                    "RETURNING seq"
                ),
                {
                    "o": self.org_id,
                    "r": self.rail_id,
                    "h": attempt.tx_hash.lower(),
                    "f": body["from"],
                    "t": body["to"],
                    "n": int(body["nonce"]),
                    "a": int(body["amount_minor"]),
                    "out": outcome,
                    "tv": test_value,
                    "att": attempt.attempt_id,
                    "now": now,
                    "vis": visible,
                },
            ).scalar_one_or_none()
        if inserted is None and self._row(attempt.tx_hash) is None:
            # The nonce is taken by another transaction: the chain refuses this one before accepting it.
            raise RailError(FailureClass.TECHNICAL_RETRYABLE, "simulated chain: nonce already used")
        if inserted is not None and test_value == "timeout_after_forward":
            raise RailError(
                FailureClass.TIMEOUT,
                "simulated timeout after forwarding (test value .13); outcome unknown",
                {"test_value": test_value, "tx_hash": attempt.tx_hash, "simulated": True},
            )
        return SubmitResult(attempt.tx_hash)

    def status(self, attempt: AttemptView) -> StatusResult:
        row = self._row(attempt.tx_hash)
        if row is None:
            return StatusResult("NOT_FOUND")
        if row.visible_at > self._clock.now():
            return StatusResult("PENDING", None, 0, {"tx_hash": row.tx_hash, "simulated": True})
        ev = self._evidence(row)
        if row.outcome == "reverted":
            return StatusResult("FAILED", FailureClass.TECHNICAL_FINAL, 1, ev)
        return StatusResult("CONFIRMED", None, 1, ev)

    def resolve(self, attempt: AttemptView) -> Resolved:
        """EXE-06 on the simulated chain: only what the chain recorded decides. A transaction it never saw
        is broadcast again (the same stored bytes), as on a real chain."""
        st = self.status(attempt)
        if st.state in ("CONFIRMED", "FAILED"):
            return Resolved(st.state, st.evidence, st.failure_class)
        if st.state == "PENDING":
            return Resolved("UNKNOWN", {"note": "transaction known to the chain, not yet visible"})
        return Resolved(
            "UNKNOWN", {"note": "never reached the simulated chain"}, rebroadcast=bool(attempt.raw_tx)
        )

    def health(self) -> Health:
        return Health(True, None, {"simulated": True})

    # ------------------------------------------------------------------------------ watching (LED-04)
    def head_block(self) -> int:
        with self._engine.connect() as conn:
            top = conn.execute(
                text("SELECT max(seq) FROM simchain_transfers WHERE org_id=:o AND rail_id=:r"),
                {"o": self.org_id, "r": self.rail_id},
            ).scalar_one_or_none()
        return int(top or 0)

    def transfers(
        self, from_block: int, to_block: int, *, to_addresses: list[str], from_addresses: list[str]
    ) -> list[ObservedTransfer]:
        """Our simulated wallet's successful outgoing transfers that are visible now. The simulated chain
        has no deposits: inbound transfers need a real test network."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT tx_hash, seq, from_address, to_address, amount_minor, submitted_at "
                    "FROM simchain_transfers WHERE org_id=:o AND rail_id=:r AND seq BETWEEN :a AND :b "
                    "AND outcome='confirmed' AND visible_at <= :now ORDER BY seq"
                ),
                {
                    "o": self.org_id,
                    "r": self.rail_id,
                    "a": from_block,
                    "b": to_block,
                    "now": self._clock.now(),
                },
            ).all()
        return [
            ObservedTransfer(
                external_id=f"{r.tx_hash}:0",
                tx_hash=r.tx_hash,
                log_index=0,
                direction="out",
                from_party=r.from_address,
                to_party=r.to_address,
                amount_minor=int(r.amount_minor),
                block_number=int(r.seq),
                confirmations=1,
                occurred_at=r.submitted_at.isoformat(),
            )
            for r in rows
        ]
