"""Adapter for the simulated instant bank rail (RAL-04 behind the RAL-01 contract).

The rail deduplicates by ``Idempotency-Key``: the payment ID on its first rail, ``{payment_id}:{rail}``
after a failover (spec/06). Errors are normalised: a refused connection or a 503 means the rail never
took the payment (TECHNICAL_RETRYABLE); no answer, or any other 5xx, is TIMEOUT; a 422 rejection is
REJECTED_BY_RAIL; a technical failure the rail reports is TECHNICAL_FINAL.
"""

from __future__ import annotations

from typing import Any

import requests

from detent.domain.money import Currency
from detent.domain.states import FailureClass
from detent.rails.base import (
    AttemptView,
    Eligibility,
    Health,
    IntentView,
    ObservedTransfer,
    Quote,
    RailError,
    Resolved,
    StatusResult,
    SubmitResult,
)
from detent.rails.evm import classify


class BankAdapter:
    def __init__(
        self,
        *,
        rail_id: str,
        base_url: str,
        scheme: str,
        currency: str,
        per_payment_limit_minor: int | None,
        fee_flat_minor: int = 0,
        fee_bps: int = 0,
        timeout_seconds: float = 10.0,
        expected_seconds: int = 5,
        receiving_account: str | None = None,
    ) -> None:
        self.rail_id = rail_id
        self.receiving_account = receiving_account
        self.scheme = scheme
        self.currency = Currency(currency)
        self.per_payment_limit_minor = per_payment_limit_minor
        self.fee_flat_minor = fee_flat_minor
        self.fee_bps = fee_bps
        self.expected_seconds = expected_seconds
        self._url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._http = requests.Session()

    def eligible(self, intent: IntentView) -> Eligibility:
        if intent.amount.currency is not self.currency:
            return Eligibility(False, "CURRENCY_NOT_SUPPORTED")
        if intent.network != self.rail_id:
            return Eligibility(False, "NETWORK_MISMATCH")
        if not intent.destination_address:
            return Eligibility(False, "NO_DESTINATION_ACCOUNT")
        if (
            self.per_payment_limit_minor is not None
            and intent.amount.amount_minor > self.per_payment_limit_minor
        ):
            return Eligibility(False, "PER_PAYMENT_LIMIT")
        if not self.health().ok:
            return Eligibility(False, "RAIL_UNAVAILABLE")
        return Eligibility(True)

    def quote(self, intent: IntentView) -> Quote:
        fee = self.fee_flat_minor + intent.amount.amount_minor * self.fee_bps // 10_000
        return Quote(fee_minor=fee, fee_currency=self.currency.value, expected_seconds=self.expected_seconds)

    def submit(self, attempt: AttemptView) -> SubmitResult:
        body: dict[str, Any] = {
            "scheme": self.scheme,
            "amount_minor": attempt.amount.amount_minor,
            "currency": attempt.amount.currency.value,
            "account": attempt.destination_address or "",
            "reference": attempt.payment_id,
        }
        if self.receiving_account:
            body["debtor"] = self.receiving_account  # the organisation's account at the simulated bank
        try:
            r = self._http.post(
                f"{self._url}/payments",
                json=body,
                timeout=self._timeout,
                headers={
                    "Idempotency-Key": attempt.idempotency_key,
                    "X-Dekernai-Attempt": attempt.attempt_id,
                },
            )
        except requests.exceptions.RequestException as exc:
            raise RailError(classify(exc), f"bank: {type(exc).__name__}") from exc
        if r.status_code == 503:
            raise RailError(
                FailureClass.TECHNICAL_RETRYABLE, "bank: 503 before acceptance", {"body": r.text[:200]}
            )
        if r.status_code >= 500:
            raise RailError(FailureClass.TIMEOUT, f"bank: HTTP {r.status_code}; outcome unknown")
        if r.status_code == 422:
            raise RailError(FailureClass.REJECTED_BY_RAIL, "bank rejected the payment", {"bank": r.json()})
        if r.status_code == 409:
            raise RailError(
                FailureClass.TECHNICAL_FINAL, "bank: idempotency key reused with a different body"
            )
        if r.status_code not in (200, 201):
            raise RailError(FailureClass.TECHNICAL_FINAL, f"bank: HTTP {r.status_code}")
        return SubmitResult(attempt.idempotency_key)

    def status(self, attempt: AttemptView) -> StatusResult:
        try:
            r = self._http.get(f"{self._url}/payments/{attempt.idempotency_key}", timeout=self._timeout)
        except requests.exceptions.RequestException as exc:
            raise RailError(classify(exc), f"bank status: {type(exc).__name__}") from exc
        if r.status_code == 404:
            return StatusResult("NOT_FOUND")
        if r.status_code >= 400:
            raise RailError(FailureClass.TIMEOUT, f"bank status: HTTP {r.status_code}")
        p = r.json()
        ev = {
            "bank_key": p["key"],
            "bank_status": p["status"],
            "reason": p.get("reason"),
            "fee_minor": p.get("fee_minor"),
        }
        if p["status"] == "SETTLED":
            return StatusResult("CONFIRMED", None, 1, ev)
        if p["status"] == "REJECTED":
            return StatusResult("FAILED", FailureClass.REJECTED_BY_RAIL, 0, ev)
        if p["status"] == "FAILED":
            return StatusResult("FAILED", FailureClass.TECHNICAL_FINAL, 0, ev)
        return StatusResult("PENDING", None, 0, ev)

    def resolve(self, attempt: AttemptView) -> Resolved:
        """Bank side of EXE-06: status by idempotency key. A key the rail never saw is sent again with the
        same key, which the rail deduplicates."""
        try:
            st = self.status(attempt)
        except RailError:
            return Resolved("UNKNOWN", {"note": "rail did not answer"})
        if st.state in ("CONFIRMED", "FAILED"):
            return Resolved(st.state, st.evidence, st.failure_class)
        if st.state == "NOT_FOUND":
            return Resolved("UNKNOWN", {"note": "the rail never saw this key"}, rebroadcast=True)
        return Resolved("UNKNOWN", st.evidence)

    def health(self) -> Health:
        try:
            ok = self._http.get(f"{self._url}/healthz", timeout=self._timeout).status_code == 200
        except requests.exceptions.RequestException as exc:
            return Health(False, None, {"error": type(exc).__name__})
        return Health(ok, None, {"scheme": self.scheme})

    # ------------------------------------------------------------------------------ watching (LED-04)
    def _acct(self) -> dict[str, str]:
        """The organisation's receiving account at the simulated bank (one per organisation)."""
        return {"account": self.receiving_account} if self.receiving_account else {}

    def inbound(self, after: int) -> tuple[list[ObservedTransfer], int]:
        """Inbound credits after the cursor; returns them and the new cursor."""
        r = self._http.get(
            f"{self._url}/inbound",
            params={"scheme": self.scheme, "after": str(after), **self._acct()},
            timeout=self._timeout,
        )
        r.raise_for_status()
        rows = r.json()["data"]
        out = [
            ObservedTransfer(
                external_id=str(x["id"]),
                tx_hash=str(x["id"]),
                log_index=0,
                direction="in",
                from_party=str(x["payer"]),
                to_party=str(x["reference"]),
                amount_minor=int(x["amount_minor"]),
                block_number=None,
                confirmations=1,  # a bank credit is final when the bank reports it
                occurred_at=str(x["received_at"]),
            )
            for x in rows
        ]
        return out, max([after, *(int(x["seq"]) for x in rows)])

    def statement(self, day: str, fmt: str = "json") -> Any:
        """The day's statement for this scheme (LED-07): JSON or CSV text."""
        r = self._http.get(
            f"{self._url}/statements/{day}",
            params={"scheme": self.scheme, "format": fmt, **self._acct()},
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.text if fmt == "csv" else r.json()
