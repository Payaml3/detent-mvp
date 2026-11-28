"""Create a payout intent and decide it synchronously (INT-01, INT-02, POL-02 to POL-04, POL-08, POL-09).

One transaction (spec/01 "Synchronous decision"): idempotency record, intent row (RECEIVED), facts,
policy, counters, decision row, ``transition()``, audit events, stored response. If anything in that
transaction fails, it rolls back and a fresh transaction records the intent with ESCALATE
``SYSTEM_UNAVAILABLE``, routed by the organisation's fail-safe setting. No path turns an error into
EXECUTE (invariant 9).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictStr, field_validator, model_validator
from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.domain.money import Currency, Money, MoneyError
from detent.domain.states import Status
from detent.intents.registry import counterparty_stats
from detent.intents.transition import transition
from detent.intents.users import destination_row, holder_name, user_facts
from detent.mandates.store import add_usage, release_usage
from detent.mandates.store import verify as verify_mandate
from detent.policy.engine import CheckResult, Evaluation, evaluate
from detent.policy.facts import (
    CounterpartyFacts,
    DestinationFacts,
    Facts,
    MandateFacts,
    TravelRuleFacts,
    Unavailable,
    UserFacts,
)
from detent.policy.screening import Screening
from detent.policy.store import ActivePolicy, active_policy
from detent.sandbox import usage
from detent.views.payments import _iso, payment_view
from detent.worker.queue import enqueue

SEND_JOB = "payment.send"

log = logging.getLogger("detent.intents")


# ------------------------------------------------------------------------------------------ request
class AmountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: StrictStr
    currency: Currency

    @model_validator(mode="after")
    def _exact(self) -> AmountIn:
        try:
            m = Money.parse(self.amount, self.currency)
        except MoneyError as exc:
            raise ValueError(str(exc)) from exc
        if m.amount_minor <= 0:
            raise ValueError("amount must be greater than zero")
        return self

    def money(self) -> Money:
        return Money.parse(self.amount, self.currency)


class DestinationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["evm_wallet", "bank_account"]
    network: str = Field(min_length=1, max_length=64)
    address: str | None = Field(default=None, pattern=r"^0x[0-9a-fA-F]{40}$")
    destination_id: str | None = Field(default=None, pattern=r"^dst_")

    @model_validator(mode="after")
    def _identified(self) -> DestinationIn:
        if self.destination_id is None and not (self.kind == "evm_wallet" and self.address):
            raise ValueError("give destination_id, or an address for an evm_wallet")
        return self


class IntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["payout"] = "payout"
    source: Literal["platform", "agent"]
    mandate_id: str | None = Field(default=None, pattern=r"^mnd_")
    counterparty_id: str | None = Field(default=None, pattern=r"^cpt_")
    user_account_ref: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$")
    destination: DestinationIn
    amount: AmountIn
    allow_network_switch: bool = False
    reference: str | None = Field(default=None, max_length=140)
    notes: str | None = Field(default=None, max_length=1000)  # untrusted text: never read by the policy
    travel_rule: dict[str, Any] | None = None

    @field_validator("travel_rule")
    @classmethod
    def _tr_shape(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and not set(v) <= {"originator", "beneficiary"}:
            raise ValueError("travel_rule has only originator and beneficiary")
        return v

    @model_validator(mode="after")
    def _rules(self) -> IntentRequest:
        if self.source == "agent" and not self.mandate_id:
            raise ValueError("an agent intent needs a mandate_id")
        if (self.counterparty_id is None) == (self.user_account_ref is None):
            raise ValueError("give exactly one of counterparty_id or user_account_ref")
        return self


class RequestProblem(Exception):
    """A 422 found after parsing (for example an unknown counterparty). Nothing is created."""

    def __init__(self, code: str, message: str, param: str | None = None, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.param, self.status = code, message, param, status


class IdempotencyConflict(Exception):
    pass


# ------------------------------------------------------------------------------------------ data reads
# Module-level functions so a fault-injection test can replace each one (POL-09).
@dataclass(frozen=True, slots=True)
class OrgRow:
    mode: str
    fail_safe: str
    registered_name: str | None
    registered_account: str | None


def load_org(conn: Connection, org_id: str) -> OrgRow:
    r = conn.execute(
        text(
            "SELECT mode, fail_safe, registered_name, registered_account FROM organisations WHERE org_id=:o"
        ),
        {"o": org_id},
    ).one()
    return OrgRow(r.mode, r.fail_safe, r.registered_name, r.registered_account)


def counterparty_exists(conn: Connection, org_id: str, cpt: str) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM counterparties WHERE org_id=:o AND id=:c"), {"o": org_id, "c": cpt}
        ).first()
        is not None
    )


def mandate_exists(conn: Connection, org_id: str, mnd: str) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM mandates WHERE org_id=:o AND id=:m"), {"o": org_id, "m": mnd}
        ).first()
        is not None
    )


def load_counterparty(conn: Connection, org_id: str, cpt: str) -> CounterpartyFacts:
    r = conn.execute(
        text("SELECT id, name, kyb_status, allowlisted FROM counterparties WHERE org_id=:o AND id=:c"),
        {"o": org_id, "c": cpt},
    ).one()
    st = counterparty_stats(conn, org_id, cpt)
    return CounterpartyFacts(r.id, r.name, r.kyb_status, r.allowlisted, st.payment_count, st.median)


def load_destination(
    conn: Connection, clock: Clock, org_id: str, cpt: str, dest: DestinationIn
) -> DestinationFacts:
    cols = "id, network, address, account_masked, first_seen_at, last_changed_at, last_changed_by"
    if dest.destination_id:
        r = conn.execute(
            text(f"SELECT {cols}, counterparty_id, kind FROM destinations WHERE org_id=:o AND id=:d"),  # noqa: S608 - cols is a constant
            {"o": org_id, "d": dest.destination_id},
        ).one_or_none()
        if r is None or r.counterparty_id != cpt:
            raise RequestProblem(
                "validation_error",
                "destination_id is not a destination of this counterparty",
                "destination.destination_id",
            )
        if (
            r.network != dest.network
            or r.kind != dest.kind
            or (dest.address and (r.address or "").lower() != dest.address.lower())
        ):
            raise RequestProblem(
                "validation_error", "destination does not match the registered destination", "destination"
            )
    else:
        r = conn.execute(
            text(
                f"SELECT {cols} FROM destinations WHERE org_id=:o AND counterparty_id=:c "  # noqa: S608
                "AND network=:n AND lower(address)=lower(:a) ORDER BY first_seen_at LIMIT 1"
            ),
            {"o": org_id, "c": cpt, "n": dest.network, "a": dest.address},
        ).one_or_none()
        if r is None:
            # G-01 (D-23): never trust an unregistered address silently. Record it as a new destination
            # first seen now, so NEW_WALLET escalates.
            now = clock.now()
            dst_id = new_id(Prefix.DST, now)
            conn.execute(
                text(
                    "INSERT INTO destinations (id, org_id, counterparty_id, kind, network, address, "
                    "verified, "
                    "first_seen_at, last_changed_at) VALUES (:id, :o, :c, 'evm_wallet', :n, :a, false, :t, "
                    ":t)"
                ),
                {"id": dst_id, "o": org_id, "c": cpt, "n": dest.network, "a": dest.address, "t": now},
            )
            append(
                conn,
                clock,
                org_id=org_id,
                actor=Actor.system("intents"),
                kind="destination.registered",
                subject_id=dst_id,
                payload={
                    "counterparty_id": cpt,
                    "network": dest.network,
                    "address": dest.address,
                    "verified": False,
                },
            )
            return DestinationFacts(dst_id, False, dest.address, None, now, now, None)
    return DestinationFacts(
        r.id,
        True,
        r.address,
        r.account_masked,
        r.first_seen_at,
        r.last_changed_at,
        r.last_changed_by,
        previous_details(conn, org_id, r.id),
    )


def load_user_destination(conn: Connection, org_id: str, ref: str, dest: DestinationIn) -> DestinationFacts:
    """A user payout goes only to the user's one registered destination (USR-01, G-10)."""
    r = destination_row(conn, org_id, ref)
    if r is None:
        raise RequestProblem(
            "validation_error",
            "this user account has no registered destination; register it with PUT /v1/user_accounts/{ref}",
            "user_account_ref",
        )
    if (
        (dest.destination_id and dest.destination_id != r.id)
        or r.network != dest.network
        or r.kind != dest.kind
        or (dest.address and (r.address or "").lower() != dest.address.lower())
    ):
        raise RequestProblem(
            "validation_error", "destination is not the user's registered destination", "destination"
        )
    return DestinationFacts(
        r.id,
        True,
        r.address,
        r.account_masked,
        r.first_seen_at,
        r.last_changed_at,
        r.last_changed_by,
        previous_details(conn, org_id, r.id),
    )


def _scopes(cpt: str | None, currency: Currency) -> list[str]:
    # Fixed order: platform row first, then counterparty, so concurrent decisions never deadlock. A user
    # payout counts against the platform cap only (spec/04 User payouts).
    out = [f"platform:{currency.value}"]
    if cpt is not None:
        out.append(f"counterparty:{cpt}:{currency.value}")
    return out


def read_counters(
    conn: Connection, org_id: str, cpt: str | None, currency: Currency, day: str
) -> tuple[Money, Money]:
    """Lock and read today's cap counters (confirmed plus in-flight). Concurrent decisions queue here."""
    used = []
    for scope in _scopes(cpt, currency):
        conn.execute(
            text(
                "INSERT INTO counters (org_id, scope, period, currency) VALUES (:o, :s, :p, :c) "
                "ON CONFLICT (org_id, scope, period) DO NOTHING"
            ),
            {"o": org_id, "s": scope, "p": day, "c": currency.value},
        )
        v = conn.execute(
            text("SELECT amount_minor FROM counters WHERE org_id=:o AND scope=:s AND period=:p FOR UPDATE"),
            {"o": org_id, "s": scope, "p": day},
        ).scalar_one()
        used.append(Money(int(v), currency))
    return used[0], used[1] if len(used) > 1 else Money(0, currency)


def add_to_counters(
    conn: Connection, org_id: str, cpt: str | None, amount: Money, day: str, payment_id: str
) -> None:
    """The payment becomes in flight: its amount counts against today's caps until it is released."""
    for scope in _scopes(cpt, amount.currency):
        conn.execute(
            text(
                "UPDATE counters SET amount_minor = amount_minor + :a, count = count + 1 "
                "WHERE org_id=:o AND scope=:s AND period=:p"
            ),
            {"a": amount.amount_minor, "o": org_id, "s": scope, "p": day},
        )
    mnd = conn.execute(
        text("UPDATE payment_intents SET counted_on=:d WHERE org_id=:o AND id=:p RETURNING mandate_id"),
        {"d": day, "o": org_id, "p": payment_id},
    ).scalar_one()
    if mnd:
        add_usage(conn, org_id, mnd, amount)  # the mandate's total counts in-flight payments too (D-29)


def release_counters(conn: Connection, org_id: str, payment_id: str) -> None:
    """Spec/04: an amount stops counting when its payment is BLOCKED, REJECTED, CANCELLED or FAILED_FINAL.
    Only a payment that was counted is released, on the day it was counted."""
    p = conn.execute(
        text(
            "SELECT counterparty_id, amount_minor, currency, counted_on, mandate_id FROM payment_intents "
            "WHERE org_id=:o AND id=:p FOR UPDATE"
        ),
        {"o": org_id, "p": payment_id},
    ).one()
    if p.counted_on is None:
        return
    amount = Money(int(p.amount_minor), Currency(p.currency))
    for scope in _scopes(p.counterparty_id, amount.currency):
        conn.execute(
            text(
                "UPDATE counters SET amount_minor = greatest(amount_minor - :a, 0), count = greatest(count "
                "- 1, 0) "
                "WHERE org_id=:o AND scope=:s AND period=:p"
            ),
            {"a": amount.amount_minor, "o": org_id, "s": scope, "p": p.counted_on},
        )
    conn.execute(
        text("UPDATE payment_intents SET counted_on=NULL WHERE org_id=:o AND id=:p"),
        {"o": org_id, "p": payment_id},
    )
    if p.mandate_id:
        release_usage(conn, org_id, p.mandate_id, amount)


def find_recent_block(
    conn: Connection,
    org_id: str,
    cpt: str | None,
    address: str | None,
    since: datetime,
    user_ref: str | None = None,
) -> str | None:
    """D-10: a block on the same counterparty, user account or destination address, whatever the amount."""
    return conn.execute(
        text(
            "SELECT p.id FROM payment_intents p LEFT JOIN destinations d "
            "ON d.org_id = p.org_id AND d.id = p.destination_id "
            "WHERE p.org_id=:o AND p.status='BLOCKED' AND p.updated_at >= :since "
            "AND (p.counterparty_id=:c OR p.user_account_ref=:u "
            "OR (CAST(:a AS text) IS NOT NULL AND lower(d.address)=lower(CAST(:a AS text)))) "
            "ORDER BY p.updated_at DESC LIMIT 1"
        ),
        {"o": org_id, "since": since, "c": cpt, "u": user_ref, "a": address},
    ).scalar_one_or_none()


def load_travel_rule(
    org: OrgRow,
    beneficiary_name: str | None,
    dest: DestinationFacts,
    supplied: dict[str, Any] | None,
    source: str,
) -> TravelRuleFacts:
    return TravelRuleFacts(
        originator={"name": org.registered_name, "account": org.registered_account},
        beneficiary={"name": beneficiary_name, "account": dest.address or dest.account_masked},
        supplied=supplied if source == "platform" else None,
    )


def _try(dependency: str, fn: Any, *a: Any) -> Any:
    try:
        return fn(*a)
    except Exception as exc:  # fail closed: the check that needs it returns SYSTEM_UNAVAILABLE
        log.warning(
            "dependency failed during decision", extra={"dependency": dependency, "error": type(exc).__name__}
        )
        return Unavailable(dependency, type(exc).__name__)


# ------------------------------------------------------------------------------------------ views
# The read-only views live in detent.views.payments (shared with webhook events, WHK-01).


def request_hash(endpoint: str, req: IntentRequest) -> str:
    body = json.dumps(
        {"endpoint": endpoint, "body": req.model_dump(mode="json")}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(body.encode()).hexdigest()


def _jsonable(v: Any) -> Any:
    if isinstance(v, Money):
        return v.to_api()
    if isinstance(v, datetime):
        return _iso(v)
    if hasattr(v, "__dataclass_fields__"):
        return {k: _jsonable(getattr(v, k)) for k in v.__dataclass_fields__}
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_jsonable(x) for x in v]
    return v


def _status_for(
    outcome: str, *, decision_only: bool, mode: str, fail_safe: str, system_unavailable: bool
) -> Status:
    if outcome == "BLOCK":
        return Status.BLOCKED
    if decision_only or mode == "shadow":
        return Status.SHADOWED  # decided beside the platform; never executes (D-24)
    if outcome == "EXECUTE":
        return Status.READY
    if system_unavailable and fail_safe == "hold":
        return Status.HELD  # D-09
    return Status.ESCALATED


@dataclass
class _Ctx:
    org_id: str
    actor: Actor
    key: str
    req: IntentRequest
    decision_only: bool
    endpoint: str
    rhash: str
    mandate_key: SecretStr | None = None


def _claim_idempotency(conn: Connection, clock: Clock, c: _Ctx) -> tuple[int, dict[str, Any]] | None:
    """Keys are per organisation. A parallel duplicate waits on the unique index, then replays."""
    inserted = conn.execute(
        text(
            "INSERT INTO idempotency_records (org_id, key, request_hash, response, created_at) "
            "VALUES (:o, :k, :h, '{}'::jsonb, :t) ON CONFLICT (org_id, key) DO NOTHING RETURNING key"
        ),
        {"o": c.org_id, "k": c.key, "h": c.rhash, "t": clock.now()},
    ).scalar_one_or_none()
    if inserted is not None:
        return None
    rec = conn.execute(
        text("SELECT request_hash, response FROM idempotency_records WHERE org_id=:o AND key=:k"),
        {"o": c.org_id, "k": c.key},
    ).one()
    if rec.request_hash != c.rhash:
        raise IdempotencyConflict(c.key)
    return int(rec.response["status_code"]), rec.response["body"]


def _validate_refs(conn: Connection, c: _Ctx) -> str | None:
    """The counterparty ID, or None for a user payout (whose account must be registered)."""
    req = c.req
    if req.user_account_ref is not None:
        if req.source == "agent":
            raise RequestProblem(
                "validation_error",
                "an agent intent pays a counterparty, not a user account",
                "user_account_ref",
            )
        if user_facts(conn, c.org_id, req.user_account_ref) is None:
            raise RequestProblem(
                "validation_error",
                "unknown user account; register it with PUT /v1/user_accounts/{ref}",
                "user_account_ref",
            )
        return None
    assert req.counterparty_id is not None
    if not counterparty_exists(conn, c.org_id, req.counterparty_id):
        raise RequestProblem("validation_error", "unknown counterparty", "counterparty_id")
    if req.source == "agent" and req.mandate_id and not mandate_exists(conn, c.org_id, req.mandate_id):
        raise RequestProblem("mandate_invalid", "unknown mandate", "mandate_id")
    return req.counterparty_id


def _mandate_allows_switch(conn: Connection, org_id: str, req: IntentRequest) -> bool:
    """RAL-07: an agent intent may switch networks when its signed mandate says so
    (``scope.allow_network_switch``); routing still keeps the switch inside the mandate's networks."""
    if req.source != "agent" or not req.mandate_id:
        return False
    v = conn.execute(
        text("SELECT payload->'scope'->>'allow_network_switch' FROM mandates WHERE org_id=:o AND id=:m"),
        {"o": org_id, "m": req.mandate_id},
    ).scalar_one_or_none()
    return v == "true"


def _insert_intent(conn: Connection, clock: Clock, c: _Ctx, cpt: str | None, dest_id: str | None) -> str:
    now = clock.now()
    pid = new_id(Prefix.PAY, now)
    amount = c.req.amount.money()
    conn.execute(
        text(
            "INSERT INTO payment_intents (id, org_id, source, mandate_id, counterparty_id, user_account_ref, "
            "destination_id, "
            "amount_minor, currency, network_constraint, allow_network_switch, reference, notes, "
            "travel_rule, "
            "status, idempotency_key, request_hash, initiated_by, created_at, updated_at) VALUES (:id, :o, "
            ":src, "
            ":m, :c, :u, :d, :a, :cur, :net, :sw, :ref, :notes, CAST(:tr AS jsonb), 'RECEIVED', :k, :h, :by, "
            ":t, :t)"
        ),
        {
            "id": pid,
            "o": c.org_id,
            "src": c.req.source,
            "m": c.req.mandate_id,
            "c": cpt,
            "u": c.req.user_account_ref,
            "d": dest_id,
            "a": amount.amount_minor,
            "cur": amount.currency.value,
            "net": c.req.destination.network,
            "sw": c.req.allow_network_switch or _mandate_allows_switch(conn, c.org_id, c.req),
            "ref": c.req.reference,
            "notes": c.req.notes,
            "tr": json.dumps(c.req.travel_rule) if c.req.travel_rule is not None else None,
            "k": c.key,
            "h": c.rhash,
            "by": c.actor.id,
            "t": now,
        },
    )
    append(
        conn,
        clock,
        org_id=c.org_id,
        actor=c.actor,
        kind="payment.received",
        subject_id=pid,
        payload={
            "amount": amount.to_api(),
            "source": c.req.source,
            "counterparty_id": cpt,
            "user_account_ref": c.req.user_account_ref,
            "destination_id": dest_id,
            "network": c.req.destination.network,
            "decision_only": c.decision_only,
            "idempotency_key": c.key,
        },
    )
    return pid


def _record(
    conn: Connection,
    clock: Clock,
    c: _Ctx,
    pid: str,
    policy: ActivePolicy,
    outcome: str,
    checks: list[dict[str, Any]],
    snapshot: dict[str, Any],
    status: Status,
    awaiting: bool,
) -> tuple[int, dict[str, Any]]:
    now = clock.now()
    dec_id = new_id(Prefix.DEC, now)
    conn.execute(
        text(
            "INSERT INTO decisions (id, org_id, payment_id, outcome, policy_version_id, policy_hash, "
            "inputs_snapshot, checks, decided_at, actor) VALUES (:id, :o, :p, :out, :pv, :ph, "
            "CAST(:snap AS jsonb), CAST(:checks AS jsonb), :t, :a)"
        ),
        {
            "id": dec_id,
            "o": c.org_id,
            "p": pid,
            "out": outcome,
            "pv": policy.id,
            "ph": policy.rules.content_hash,
            "snap": json.dumps(snapshot),
            "checks": json.dumps(checks),
            "t": now,
            "a": "system:policy",
        },
    )
    append(
        conn,
        clock,
        org_id=c.org_id,
        actor=Actor.system("policy"),
        kind="decision.made",
        subject_id=pid,
        payload={
            "decision_id": dec_id,
            "outcome": outcome,
            "policy_version": policy.version,
            "policy_hash": policy.rules.content_hash,
            "checks": checks,
        },
    )
    if status is Status.READY and not awaiting:
        # Orchestration picks it up: the worker sends it (EXE-03 onwards). One job per payment.
        enqueue(
            conn,
            clock,
            org_id=c.org_id,
            kind=SEND_JOB,
            payment_id=pid,
            dedupe_key=pid,
            payload={"payment_id": pid},
        )
    transition(
        conn,
        clock,
        org_id=c.org_id,
        payment_id=pid,
        to=status,
        actor=Actor.system("policy"),
        reason=f"decision {outcome}",
        awaiting_send_click=awaiting,
    )
    if status is Status.ESCALATED:
        from detent.exceptions.cases import open_case

        reasons = [
            ch["reason"] for ch in checks if ch.get("result") in ("ESCALATE", "BLOCK") and ch.get("reason")
        ]
        open_case(conn, clock, org_id=c.org_id, payment_id=pid, reasons=reasons, rules=policy.rules)
    view = payment_view(conn, c.org_id, pid, any_generation=True)  # just written: never hidden
    assert view is not None
    if c.decision_only:
        code, body = 200, {**view["decision"], "payment_id": pid, "executed": False}
    else:
        code, body = 201, view
    conn.execute(
        text("UPDATE idempotency_records SET response=CAST(:r AS jsonb) WHERE org_id=:o AND key=:k"),
        {"r": json.dumps({"status_code": code, "body": body}), "o": c.org_id, "k": c.key},
    )
    return code, body


def build_facts(
    conn: Connection,
    clock: Clock,
    org_id: str,
    org: OrgRow,
    rules: Any,
    *,
    source: str,
    amount: Money,
    network: str,
    cp: CounterpartyFacts | None,
    dest: DestinationFacts,
    supplied_travel_rule: dict[str, Any] | None,
    screening: Screening,
    already_counted: Money | None,
    mandate_id: str | None = None,
    mandate_key: SecretStr | None = None,
    user: UserFacts | None = None,
    user_name: str | None = None,
) -> Facts:
    """Gather the typed facts for one evaluation. ``already_counted`` is this payment's own amount when a
    re-run happens while it is in flight, so it is not counted against the cap twice. A user payout passes
    ``user`` (and the platform's ``user_name`` for screening and the travel rule) instead of ``cp``."""
    now = clock.now()
    day = now.date().isoformat()  # UTC calendar day (G-14)
    cpt = cp.id if cp is not None else None
    payee_name = cp.name if cp is not None else user_name
    counters = _try("counters", read_counters, conn, org_id, cpt, amount.currency, day)
    if isinstance(counters, tuple):
        used_p, used_c = counters
        if already_counted is not None:
            used_p, used_c = used_p - already_counted, used_c - already_counted
    else:
        used_p = used_c = counters
    recent_block = None
    if rules.checks.resubmission_after_block is not None:
        since = now - timedelta(hours=rules.checks.resubmission_after_block.window_hours)
        recent_block = find_recent_block(
            conn, org_id, cpt, dest.address, since, user_ref=user.ref if user is not None else None
        )
    mandate: MandateFacts | Unavailable | None = None
    if source == "agent" and cpt is not None:
        mandate = (
            _try(
                "mandate",
                lambda: verify_mandate(
                    conn,
                    org_id=org_id,
                    mandate_id=mandate_id,
                    key=mandate_key,
                    now=now,
                    payee=cpt,
                    amount=amount,
                    network=network,
                    already_counted=already_counted is not None,
                ),
            )
            if mandate_id
            else None
        )
    return Facts(
        now=now,
        source=source,  # type: ignore[arg-type]
        amount=amount,
        network=network,
        counterparty=cp,
        destination=dest,
        screening=_try("screening", lambda: screening.check(address=dest.address, name=payee_name)),
        travel_rule=load_travel_rule(org, payee_name, dest, supplied_travel_rule, source),
        used_today_platform=used_p,
        used_today_counterparty=used_c,
        recent_block_id=recent_block,
        mandate=mandate,
        user=user,
    )


def previous_details(conn: Connection, org_id: str, destination_id: str | None) -> str | None:
    """The address or account before the destination's last change, from its audit event."""
    if destination_id is None:
        return None
    old = conn.execute(
        text(
            "SELECT payload->'old' FROM audit_events WHERE org_id=:o AND subject_id=:d AND "
            "kind='destination.changed' "
            "ORDER BY seq DESC LIMIT 1"
        ),
        {"o": org_id, "d": destination_id},
    ).scalar_one_or_none()
    return (old.get("address") or old.get("account_masked")) if old else None


def load_destination_by_id(conn: Connection, org_id: str, destination_id: str) -> DestinationFacts:
    r = conn.execute(
        text(
            "SELECT id, address, account_masked, first_seen_at, last_changed_at, last_changed_by, verified "
            "FROM destinations WHERE org_id=:o AND id=:d"
        ),
        {"o": org_id, "d": destination_id},
    ).one()
    return DestinationFacts(
        r.id,
        True,
        r.address,
        r.account_masked,
        r.first_seen_at,
        r.last_changed_at,
        r.last_changed_by,
        previous_details(conn, org_id, r.id),
    )


# Facts that must be unchanged for an approval to cover the reasons it saw (spec/04, D-01).
_APPROVAL_BASIS = (
    ("amount",),
    ("network",),
    ("destination", "id"),
    ("destination", "address"),
    ("destination", "account_masked"),
    ("destination", "last_changed_at"),
    ("counterparty", "id"),
    ("counterparty", "kyb_status"),
    ("counterparty", "allowlisted"),
    ("user", "ref"),
    ("user", "verified"),
)
# A system failure is never something a person can approve away (fail closed).
_NEVER_APPROVABLE = {"SYSTEM_UNAVAILABLE"}


def _basis(facts: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in _APPROVAL_BASIS:
        v: Any = facts
        for k in path:
            v = v.get(k) if isinstance(v, dict) else None
        out[".".join(path)] = v
    return out


def approval_covers(
    result: Evaluation, approved: list[str], before: dict[str, Any] | None, now: dict[str, Any]
) -> tuple[bool, list[str]]:
    """D-01: EXECUTE only if every remaining ESCALATE reason was approved and the facts behind it are
    unchanged. Returns (covered, what changed)."""
    if result.outcome != "ESCALATE":
        return False, []
    remaining = set(result.reasons)
    if not remaining <= set(approved) or remaining & _NEVER_APPROVABLE:
        return False, []
    if before is None:
        return False, ["no escalation snapshot"]
    b, n = _basis(before), _basis(now)
    changed = sorted(k for k in b if b[k] != n[k])
    return not changed, changed


def reevaluate(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    payment_id: str,
    screening: Screening,
    reason: str,
    approved_reasons: list[str] | None = None,
    mandate_key: SecretStr | None = None,
) -> tuple[Evaluation, ActivePolicy]:
    """Re-run every check with the active rule version on an existing payment (EXE-03, EXC-04; spec/04).

    With ``approved_reasons`` (an approval), the outcome is EXECUTE only when the approval covers every
    remaining ESCALATE reason and the facts behind them are unchanged (D-01); any BLOCK still blocks.
    Records a new decision and its audit event in the caller's transaction. Any error is the caller's
    to handle as a hold (fail closed)."""
    before = conn.execute(
        text(
            "SELECT inputs_snapshot FROM decisions WHERE org_id=:o AND payment_id=:p "
            "ORDER BY decided_at DESC, id DESC LIMIT 1"
        ),
        {"o": org_id, "p": payment_id},
    ).scalar_one_or_none()
    p = conn.execute(
        text(
            "SELECT source, counterparty_id, user_account_ref, destination_id, amount_minor, currency, "
            "network_constraint, travel_rule, status, counted_on, mandate_id FROM payment_intents "
            "WHERE org_id=:o AND id=:p"
        ),
        {"o": org_id, "p": payment_id},
    ).one()
    org = load_org(conn, org_id)
    policy = active_policy(conn, org_id)
    amount = Money(int(p.amount_minor), Currency(p.currency))
    cp = load_counterparty(conn, org_id, p.counterparty_id) if p.counterparty_id else None
    user = user_facts(conn, org_id, p.user_account_ref) if p.user_account_ref else None
    if p.user_account_ref and user is None:
        raise LookupError(f"user account {p.user_account_ref} is missing")  # fail closed: the caller holds
    dest = load_destination_by_id(conn, org_id, p.destination_id)
    in_flight = p.counted_on is not None  # its own amount is already in today's counters
    facts = build_facts(
        conn,
        clock,
        org_id,
        org,
        policy.rules,
        source=p.source,
        amount=amount,
        network=p.network_constraint,
        cp=cp,
        dest=dest,
        supplied_travel_rule=p.travel_rule,
        screening=screening,
        already_counted=amount if in_flight else None,
        mandate_id=p.mandate_id,
        mandate_key=mandate_key,
        user=user,
        user_name=holder_name(conn, org_id, p.user_account_ref) if p.user_account_ref else None,
    )
    result = evaluate(facts, policy.rules)
    facts_json = _jsonable(facts)
    changed: list[str] = []
    if approved_reasons is not None:
        covered, changed = approval_covers(
            result, approved_reasons, (before or {}).get("facts") if before else None, facts_json
        )
        if covered:
            result = Evaluation("EXECUTE", result.checks)
    now = clock.now()
    dec_id = new_id(Prefix.DEC, now)
    checks = [ch.to_json() for ch in result.checks]
    conn.execute(
        text(
            "INSERT INTO decisions (id, org_id, payment_id, outcome, policy_version_id, policy_hash, "
            "inputs_snapshot, checks, approved_reasons, decided_at, actor) VALUES (:id, :o, :p, :out, :pv, "
            ":ph, CAST(:snap AS jsonb), CAST(:checks AS jsonb), :appr, :t, 'system:policy')"
        ),
        {
            "id": dec_id,
            "o": org_id,
            "p": payment_id,
            "out": result.outcome,
            "pv": policy.id,
            "ph": policy.rules.content_hash,
            "snap": json.dumps(
                {
                    "facts": facts_json,
                    "rule_version": policy.version,
                    "profile": facts.profile,
                    "rerun_reason": reason,
                    "changed": changed,
                }
            ),
            "checks": json.dumps(checks),
            "appr": list(approved_reasons or []),
            "t": now,
        },
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=Actor.system("policy"),
        kind="decision.made",
        subject_id=payment_id,
        payload={
            "decision_id": dec_id,
            "outcome": result.outcome,
            "policy_version": policy.version,
            "policy_hash": policy.rules.content_hash,
            "checks": checks,
            "rerun_reason": reason,
            "approved_reasons": list(approved_reasons or []),
            "changed_since_escalation": changed,
        },
    )
    return result, policy


def _decide(conn: Connection, clock: Clock, c: _Ctx, screening: Screening) -> tuple[int, dict[str, Any]]:
    replay = _claim_idempotency(conn, clock, c)
    if replay:
        return replay
    cpt = _validate_refs(conn, c)
    usage.consume(conn, clock, c.org_id, "payments_decided")  # SBX-02, LED-08; rolls back with the decision
    org = load_org(conn, c.org_id)
    policy = active_policy(conn, c.org_id)
    rules = policy.rules
    ref = c.req.user_account_ref
    if cpt is None:
        assert ref is not None
        dest = load_user_destination(conn, c.org_id, ref, c.req.destination)
    else:
        dest = load_destination(conn, clock, c.org_id, cpt, c.req.destination)
    pid = _insert_intent(conn, clock, c, cpt, dest.id)
    cp = load_counterparty(conn, c.org_id, cpt) if cpt is not None else None
    now = clock.now()
    amount = c.req.amount.money()
    day = now.date().isoformat()  # UTC calendar day (G-14)
    facts = build_facts(
        conn,
        clock,
        c.org_id,
        org,
        rules,
        source=c.req.source,
        amount=amount,
        network=c.req.destination.network,
        cp=cp,
        dest=dest,
        supplied_travel_rule=c.req.travel_rule,
        screening=screening,
        already_counted=None,
        mandate_id=c.req.mandate_id,
        mandate_key=c.mandate_key,
        user=user_facts(conn, c.org_id, ref) if ref else None,
        user_name=holder_name(conn, c.org_id, ref) if ref else None,
    )
    result: Evaluation = evaluate(facts, rules)
    status = _status_for(
        result.outcome,
        decision_only=c.decision_only,
        mode=org.mode,
        fail_safe=org.fail_safe,
        system_unavailable=result.system_unavailable,
    )
    if status is Status.READY:
        add_to_counters(conn, c.org_id, cpt, amount, day, pid)  # in flight from now (spec/04 Counters)
    return _record(
        conn,
        clock,
        c,
        pid,
        policy,
        result.outcome,
        [ch.to_json() for ch in result.checks],
        {"facts": _jsonable(facts), "rule_version": policy.version, "profile": facts.profile},
        status,
        status is Status.READY and org.mode == "assist",
    )


def _decide_failed(conn: Connection, clock: Clock, c: _Ctx, error: str) -> tuple[int, dict[str, Any]]:
    """Fresh transaction after a failure: record the intent as ESCALATE SYSTEM_UNAVAILABLE."""
    replay = _claim_idempotency(conn, clock, c)
    if replay:
        return replay
    cpt = _validate_refs(conn, c)
    usage.count(conn, clock, c.org_id, "payments_decided")  # already passed the quota in _decide
    org = load_org(conn, c.org_id)
    policy = active_policy(conn, c.org_id)
    pid = _insert_intent(conn, clock, c, cpt, None)
    check = CheckResult(
        "system", "ESCALATE", "SYSTEM_UNAVAILABLE", {"dependency": "decision", "error": error}
    )
    status = (
        Status.HELD
        if org.fail_safe == "hold" and not c.decision_only
        else (Status.SHADOWED if c.decision_only or org.mode == "shadow" else Status.ESCALATED)
    )
    return _record(
        conn, clock, c, pid, policy, "ESCALATE", [check.to_json()], {"error": error}, status, False
    )


def submit_intent(
    engine: Engine,
    clock: Clock,
    *,
    org_id: str,
    actor_id: str,
    idempotency_key: str,
    request: IntentRequest,
    decision_only: bool,
    screening: Screening,
    actor_role: str | None = None,
    mandate_key: SecretStr | None = None,
) -> tuple[int, dict[str, Any]]:
    endpoint = "decisions" if decision_only else "payment_intents"
    c = _Ctx(
        org_id,
        Actor(actor_id, actor_role),
        idempotency_key,
        request,
        decision_only,
        endpoint,
        request_hash(endpoint, request),
        mandate_key,
    )
    try:
        with transaction(engine) as conn:
            return _decide(conn, clock, c, screening)
    except (RequestProblem, IdempotencyConflict, usage.QuotaExceeded):
        raise
    except Exception as exc:
        log.exception("decision failed; recording it fail-closed", extra={"error": type(exc).__name__})
        with transaction(engine) as conn:
            return _decide_failed(conn, clock, c, type(exc).__name__)
