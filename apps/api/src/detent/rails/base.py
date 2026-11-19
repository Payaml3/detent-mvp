"""The rail adapter contract (RAL-01, spec/06).

Every rail implements ``eligible``, ``quote``, ``submit``, ``status`` and ``health``. Errors leave an
adapter only as ``RailError`` with one of the four normalised failure classes. Rule of thumb: if the
request might have reached the rail, it is TIMEOUT, never a failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from detent.domain.money import Money
from detent.domain.states import FailureClass


@dataclass(frozen=True, slots=True)
class IntentView:
    payment_id: str
    amount: Money
    network: str
    destination_address: str | None


@dataclass(frozen=True, slots=True)
class AttemptView:
    attempt_id: str
    payment_id: str
    attempt_no: int
    rail_id: str
    idempotency_key: str
    amount: Money
    destination_address: str | None
    nonce: int | None
    raw_tx: str | None
    tx_hash: str | None


@dataclass(frozen=True, slots=True)
class Eligibility:
    eligible: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Quote:
    fee_minor: int  # in the rail's fee currency (wei of gas for EVM rails)
    fee_currency: str
    expected_seconds: int


@dataclass(frozen=True, slots=True)
class SubmitResult:
    rail_reference: str


@dataclass(frozen=True, slots=True)
class StatusResult:
    state: Literal["CONFIRMED", "PENDING", "FAILED", "NOT_FOUND"]
    failure_class: FailureClass | None = None
    confirmations: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Resolved:
    """What a rail can say about an UNKNOWN attempt. ``rebroadcast`` asks the caller to send the stored
    signed transaction again (it never reached the rail)."""

    state: Literal["CONFIRMED", "FAILED", "UNKNOWN"]
    evidence: dict[str, Any] = field(default_factory=dict)
    failure_class: FailureClass | None = None
    rebroadcast: bool = False


@dataclass(frozen=True, slots=True)
class Health:
    ok: bool
    balance: Money | None
    detail: dict[str, Any] = field(default_factory=dict)


class RailError(Exception):
    def __init__(
        self, failure_class: FailureClass, message: str, evidence: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.evidence = evidence or {"error": message}


class RailAdapter(Protocol):
    rail_id: str

    def eligible(self, intent: IntentView) -> Eligibility: ...
    def quote(self, intent: IntentView) -> Quote: ...
    def submit(self, attempt: AttemptView) -> SubmitResult: ...
    def status(self, attempt: AttemptView) -> StatusResult: ...
    def health(self) -> Health: ...


@dataclass(frozen=True, slots=True)
class Prepared:
    """An EVM transaction signed before broadcast, so its nonce and raw bytes are stored first (EXE-04)."""

    nonce: int
    raw_tx: str
    tx_hash: str
    from_address: str


class NonceRail(RailAdapter, Protocol):
    """Rails that deduplicate by nonce (EVM): the execution layer assigns the nonce and stores the signed
    transaction before ``submit`` broadcasts it."""

    @property
    def from_address(self) -> str: ...
    def pending_nonce(self) -> int: ...
    def prepare(self, attempt: AttemptView, nonce: int) -> Prepared: ...
    def explorer_url(self, tx_hash: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ObservedTransfer:
    """One money movement a watcher saw on a rail (LED-04): a token Transfer log or a bank inbound credit.

    ``external_id`` is unique per rail: ``{tx_hash}:{log_index}`` on a chain, the bank's own ID otherwise.
    """

    external_id: str
    tx_hash: str
    log_index: int
    direction: str  # "in" (to a watched deposit address or reference) or "out" (from our sending wallet)
    from_party: str
    to_party: str
    amount_minor: int
    block_number: int | None
    confirmations: int
    occurred_at: str | None = None
