"""Deposit intents (LED-03, spec/03 ``/deposit_intents``).

A deposit intent tells the platform's user where to send money and lets Dekernai recognise it:

- on a chain rail, a per-account test address (the same account on the same network always gets the
  same address); on the simulated bank rail, a unique payment reference;
- valid for the organisation's ``deposit_intent_days`` (G-21: 7 by default); a deposit that arrives
  later opens a deposit exception and is never silently credited;
- idempotent like payment intents: the same ``Idempotency-Key`` and body return the same intent; the
  same key with a different body is refused.

Prototype: deposit addresses are derived, test-network only, and Dekernai holds no key for them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.domain.money import Currency, Money, MoneyError
from detent.policy.store import active_policy

_B32 = "ABCDEFGHJKMNPQRSTVWXYZ23456789"


class DepositError(ValueError):
    def __init__(self, code: str, message: str, *, param: str | None = None, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.param, self.status = code, param, status


class AmountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: str
    currency: Currency


class DepositRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_ref: str = Field(pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    currency: Currency
    network: str = Field(min_length=1, max_length=40)
    expected_amount: AmountIn | None = None
    metadata: dict[str, str] | None = None


def deposit_address(org_id: str, account_ref: str, network: str) -> str:
    """The account's test deposit address on a network: derived, stable, no key held."""
    from web3 import Web3

    h = hashlib.sha256(f"detent-deposit:{org_id}:{account_ref}:{network}".encode()).hexdigest()
    return str(Web3.to_checksum_address("0x" + h[:40]))


def _reference(intent_id: str) -> str:
    n = int(hashlib.sha256(intent_id.encode()).hexdigest(), 16)
    chars = []
    for _ in range(10):
        n, r = divmod(n, len(_B32))
        chars.append(_B32[r])
    return "DTN-" + "".join(chars)


def _hash(req: DepositRequest) -> str:
    return hashlib.sha256(json.dumps(req.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


def view(conn: Connection, org_id: str, deposit_id: str) -> dict[str, Any] | None:
    d = conn.execute(
        text(
            "SELECT d.*, r.kind AS rail_kind, r.chain_id FROM deposit_intents d LEFT JOIN rails r "
            "ON r.org_id = d.org_id AND r.id = d.rail_id WHERE d.org_id=:o AND d.id=:i"
        ),
        {"o": org_id, "i": deposit_id},
    ).one_or_none()
    if d is None:
        return None
    cur = Currency(d.currency)
    if d.deposit_address:
        instructions: dict[str, Any] = {
            "kind": "evm_address",
            "network": d.network,
            "chain_id": d.chain_id,
            "token": cur.value,
            "address": d.deposit_address,
            "note": "Test network only. A per-account prototype address; Dekernai holds no key for it.",
        }
    else:
        instructions = {
            "kind": "bank_reference",
            "network": d.network,
            "reference": d.reference,
            "note": "Simulated bank rail. Pay with exactly this reference.",
        }
    credits = conn.execute(
        text(
            "SELECT id, inbound_transfer_id, amount_minor, currency, created_at FROM credits "
            "WHERE org_id=:o AND deposit_intent_id=:i ORDER BY created_at, id"
        ),
        {"o": org_id, "i": deposit_id},
    ).all()
    return {
        "id": d.id,
        "object": "deposit_intent",
        "account_ref": d.account_ref,
        "currency": cur.value,
        "network": d.network,
        "expected_amount": Money(int(d.expected_amount_minor), cur).to_api()
        if d.expected_amount_minor
        else None,
        "status": d.status,
        "instructions": instructions,
        "expires_at": d.expires_at.isoformat().replace("+00:00", "Z") if d.expires_at else None,
        "created_at": d.created_at.isoformat().replace("+00:00", "Z"),
        "credits": [
            {
                "id": c.id,
                "inbound_transfer_id": c.inbound_transfer_id,
                "amount": Money(int(c.amount_minor), Currency(c.currency)).to_api(),
                "created_at": c.created_at.isoformat().replace("+00:00", "Z"),
            }
            for c in credits
        ],
    }


def create_deposit_intent(
    engine: Engine, clock: Clock, *, org_id: str, actor_id: str, idempotency_key: str, request: DepositRequest
) -> tuple[int, dict[str, Any]]:
    """Returns (201, intent) the first time, (200, the same intent) on a replay of the same request."""
    rh = _hash(request)
    with transaction(engine) as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"{org_id}:dep:{idempotency_key}"}
        )
        prior = conn.execute(
            text("SELECT id, request_hash FROM deposit_intents WHERE org_id=:o AND idempotency_key=:k"),
            {"o": org_id, "k": idempotency_key},
        ).one_or_none()
        if prior is not None:
            if prior.request_hash != rh:
                raise DepositError(
                    "idempotency_key_reused",
                    "This Idempotency-Key was used with a different request.",
                    status=409,
                )
            return 200, view(conn, org_id, prior.id) or {}
        rail = conn.execute(
            text(
                "SELECT id, kind, currency FROM rails WHERE org_id=:o AND network=:n AND enabled "
                "ORDER BY id LIMIT 1"
            ),
            {"o": org_id, "n": request.network},
        ).one_or_none()
        if rail is None:
            raise DepositError(
                "unsupported_network", f"No connected rail for {request.network}.", param="network"
            )
        if Currency(rail.currency) is not request.currency:
            raise DepositError(
                "currency_network_mismatch",
                f"{request.network} carries {rail.currency}, not {request.currency.value}.",
                param="currency",
            )
        rules = active_policy(conn, org_id).rules
        if request.network not in rules.checks.allowed_networks.get(request.currency, []):
            raise DepositError(
                "network_not_allowed",
                f"Your rules don't allow {request.network} for {request.currency.value}.",
                param="network",
            )
        expected = None
        if request.expected_amount is not None:
            if request.expected_amount.currency is not request.currency:
                raise DepositError(
                    "currency_mismatch", "expected_amount currency differs.", param="expected_amount"
                )
            try:
                expected = Money.parse(request.expected_amount.amount, request.currency).amount_minor
            except (MoneyError, ValueError) as exc:
                raise DepositError("invalid_amount", str(exc), param="expected_amount") from exc
            if expected <= 0:
                raise DepositError(
                    "invalid_amount", "expected_amount must be positive.", param="expected_amount"
                )
        days = int(
            conn.execute(
                text("SELECT deposit_intent_days FROM organisations WHERE org_id=:o"), {"o": org_id}
            ).scalar_one()
        )
        now = clock.now()
        dep_id = new_id(Prefix.DEP, now)
        address = (
            deposit_address(org_id, request.account_ref, request.network) if rail.kind == "evm" else None
        )
        reference = _reference(dep_id) if rail.kind == "banksim" else None
        conn.execute(
            text(
                "INSERT INTO deposit_intents (id, org_id, account_ref, currency, network, "
                "expected_amount_minor, "
                "deposit_address, reference, status, idempotency_key, request_hash, created_at, "
                "expires_at, rail_id) "
                "VALUES (:id, :o, :a, :c, :n, :e, :addr, :ref, 'OPEN', :k, :h, :t, :x, :r)"
            ),
            {
                "id": dep_id,
                "o": org_id,
                "a": request.account_ref,
                "c": request.currency.value,
                "n": request.network,
                "e": expected,
                "addr": address,
                "ref": reference,
                "k": idempotency_key,
                "h": rh,
                "t": now,
                "x": now + timedelta(days=days),
                "r": rail.id,
            },
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=Actor(actor_id),
            kind="deposit.intent_created",
            subject_id=dep_id,
            payload={
                "account_ref": request.account_ref,
                "network": request.network,
                "expected_minor": expected,
            },
        )
        return 201, view(conn, org_id, dep_id) or {}
