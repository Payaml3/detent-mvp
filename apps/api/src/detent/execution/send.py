"""Send a READY payment exactly once (EXE-02, EXE-03, EXE-04).

Step 1, in one transaction under the payment's row lock:
  - nothing happens unless the payment is READY and not waiting for a Send click;
  - the policy re-runs first if the decision is older than the configured age or the active rule
    version changed;
  - pre-send checks: kill switch off, mandate valid, the rail can carry it and the wallet covers the
    amount plus gas, the rail's daily pre-funded limit has room, the wallet's nonce is trusted;
    any failure moves the payment to HELD with the reason, and nothing is sent;
  - an attempt is created, the nonce assigned and the signed transaction stored, and the payment
    moves to SUBMITTED. Then the transaction commits.
Step 2, outside the lock: broadcast the stored transaction.
Step 3: record what the rail said. A broadcast that may have reached the rail but gave no answer is
UNKNOWN, never FAILED, and nothing is resent (invariant 3).

Parallel triggers for one payment serialise on the row lock; the loser sees SUBMITTED and does
nothing. The partial unique indexes on attempts back this up.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from pydantic import SecretStr
from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.money import Currency, Money
from detent.domain.states import AttemptStatus, FailureClass, Status
from detent.execution import nonces
from detent.execution.attempts import create_attempt, mark_attempt
from detent.intents.registry import refresh_stats
from detent.intents.service import reevaluate, release_counters
from detent.intents.transition import transition
from detent.mandates.store import verify as verify_mandate
from detent.policy.facts import Unavailable
from detent.policy.screening import Screening
from detent.policy.store import active_policy
from detent.rails.base import AttemptView, NonceRail, RailAdapter, RailError
from detent.routing.engine import route, store_route
from detent.worker.queue import enqueue

RESOLVE_JOB = "payment.resolve_unknown"

log = logging.getLogger("detent.execution")
ACTOR = Actor.system("execution")
DEFAULT_MAX_DECISION_AGE = 300


class _Hold(Exception):
    def __init__(self, reason: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def _hold(conn: Connection, clock: Clock, org_id: str, pid: str, h: _Hold) -> Status:
    transition(conn, clock, org_id=org_id, payment_id=pid, to=Status.HELD, actor=ACTOR, reason=h.reason)
    conn.execute(
        text("UPDATE payment_intents SET held_reason=:r WHERE org_id=:o AND id=:p"),
        {"r": h.reason, "o": org_id, "p": pid},
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=ACTOR,
        kind="payment.held",
        subject_id=pid,
        payload={"reason": h.reason, **h.detail},
    )
    return Status.HELD


def _prefund_scope(rail_id: str) -> str:
    return f"prefund:{rail_id}"


def _check_prefund(conn: Connection, org_id: str, rail_id: str, amount: Money, day: str) -> None:
    limit = conn.execute(
        text("SELECT prefunded_daily_limit_minor FROM rails WHERE org_id=:o AND id=:r"),
        {"o": org_id, "r": rail_id},
    ).scalar_one_or_none()
    if limit is None:
        return
    conn.execute(
        text(
            "INSERT INTO counters (org_id, scope, period, currency) VALUES (:o, :s, :p, :c) "
            "ON CONFLICT (org_id, scope, period) DO NOTHING"
        ),
        {"o": org_id, "s": _prefund_scope(rail_id), "p": day, "c": amount.currency.value},
    )
    used = conn.execute(
        text("SELECT amount_minor FROM counters WHERE org_id=:o AND scope=:s AND period=:p FOR UPDATE"),
        {"o": org_id, "s": _prefund_scope(rail_id), "p": day},
    ).scalar_one()
    if int(used) + amount.amount_minor > int(limit):
        raise _Hold(
            "PREFUNDED_LIMIT",
            {"used": str(used), "this_payment": str(amount.amount_minor), "limit": str(limit)},
        )
    conn.execute(
        text(
            "UPDATE counters SET amount_minor = amount_minor + :a, count = count + 1 "
            "WHERE org_id=:o AND scope=:s AND period=:p"
        ),
        {"a": amount.amount_minor, "o": org_id, "s": _prefund_scope(rail_id), "p": day},
    )


def _maybe_rerun(
    conn: Connection, clock: Clock, org_id: str, p: Any, screening: Screening, mandate_key: SecretStr | None
) -> str | None:
    """Re-run the policy when the decision is stale or the rule version changed. Returns a non-EXECUTE
    outcome, or None to carry on."""
    last = conn.execute(
        text(
            "SELECT decided_at, policy_version_id FROM decisions WHERE org_id=:o AND payment_id=:p "
            "ORDER BY decided_at DESC, id DESC LIMIT 1"
        ),
        {"o": org_id, "p": p.id},
    ).one()
    policy = active_policy(conn, org_id)
    max_age = (
        policy.rules.execution.max_decision_age_seconds
        if policy.rules.execution
        else DEFAULT_MAX_DECISION_AGE
    )
    reasons = []
    if clock.now() - last.decided_at > timedelta(seconds=max_age):
        reasons.append("decision_stale")
    if last.policy_version_id != policy.id:
        reasons.append("rule_version_changed")
    if not reasons:
        return None
    result, _ = reevaluate(
        conn,
        clock,
        org_id=org_id,
        payment_id=p.id,
        screening=screening,
        reason=",".join(reasons),
        mandate_key=mandate_key,
    )
    return None if result.outcome == "EXECUTE" else result.outcome


def _free_nonce(conn: Connection, org_id: str, pid: str, rail_id: str, address: str) -> int | None:
    """EXE-07: a retry after TECHNICAL_RETRYABLE reuses the nonce of the transaction that never reached the
    chain, so the wallet has no gap. Any other nonce comes from the nonce manager."""
    return conn.execute(
        text(
            "SELECT a.nonce FROM attempts a WHERE a.org_id=:o AND a.payment_id=:p AND a.rail_id=:r "
            "AND a.from_address=:f AND a.status='FAILED' AND a.failure_class='TECHNICAL_RETRYABLE' "
            "AND a.nonce IS NOT NULL AND NOT EXISTS (SELECT 1 FROM attempts b WHERE b.org_id=a.org_id "
            "AND b.rail_id=a.rail_id AND b.from_address=a.from_address AND b.nonce=a.nonce AND b.id<>a.id "
            "AND NOT (b.status='FAILED' AND b.failure_class='TECHNICAL_RETRYABLE')) "
            "ORDER BY a.attempt_no DESC LIMIT 1"
        ),
        {"o": org_id, "p": pid, "r": rail_id, "f": address.lower()},
    ).scalar_one_or_none()


def _prepare(  # noqa: PLR0912, PLR0915 - the pre-send checks in the order EXE-03 lists them
    conn: Connection,
    clock: Clock,
    adapters: Mapping[str, RailAdapter],
    org_id: str,
    pid: str,
    screening: Screening,
    mandate_key: SecretStr | None = None,
) -> tuple[Status, AttemptView | None]:
    p = conn.execute(
        text(
            "SELECT p.id, p.status, p.awaiting_send_click, p.source, p.counterparty_id, p.amount_minor, "
            "p.mandate_id, p.counted_on, "
            "p.currency, "
            "p.network_constraint, p.allow_network_switch, p.created_at, d.address, d.account_masked "
            "FROM payment_intents p "
            "LEFT JOIN destinations d "
            "ON d.org_id = p.org_id AND d.id = p.destination_id WHERE p.org_id=:o AND p.id=:p FOR UPDATE OF p"
        ),
        {"o": org_id, "p": pid},
    ).one()
    status = Status(p.status)
    if status is not Status.READY or p.awaiting_send_click:
        return status, None  # already sent, held, blocked or waiting for a person: nothing to do
    amount = Money(int(p.amount_minor), Currency(p.currency))
    try:
        rerun = _maybe_rerun(conn, clock, org_id, p, screening, mandate_key)
        if rerun == "BLOCK":
            transition(
                conn,
                clock,
                org_id=org_id,
                payment_id=pid,
                to=Status.BLOCKED,
                actor=ACTOR,
                reason="pre-send policy re-check BLOCK",
            )
            release_counters(conn, org_id, pid)
            return Status.BLOCKED, None
        if rerun is not None:
            raise _Hold("POLICY_RECHECK_ESCALATE")
        engaged = conn.execute(
            text("SELECT engaged FROM kill_switch WHERE org_id=:o FOR SHARE"), {"o": org_id}
        ).scalar_one_or_none()
        if engaged is not False:  # engaged, or no row at all: fail closed
            raise _Hold("KILL_SWITCH_ENGAGED")
        if p.source == "agent":
            # MND-02/MND-03: the mandate is checked again inside the lock before every send.
            m = verify_mandate(
                conn,
                org_id=org_id,
                mandate_id=p.mandate_id,
                key=mandate_key,
                now=clock.now(),
                payee=p.counterparty_id,
                amount=amount,
                network=p.network_constraint,
                already_counted=p.counted_on is not None,
            )
            if isinstance(m, Unavailable):
                raise _Hold("MANDATE_UNVERIFIABLE", {"dependency": m.dependency, "error": m.error})
            if not m.valid:
                transition(
                    conn,
                    clock,
                    org_id=org_id,
                    payment_id=pid,
                    to=Status.BLOCKED,
                    actor=ACTOR,
                    reason=f"pre-send mandate re-check: {m.reason}",
                )
                release_counters(conn, org_id, pid)
                return Status.BLOCKED, None
        rt = route(conn, adapters, org_id=org_id, payment=p, day=clock.now().date().isoformat())
        store_route(conn, org_id, pid, rt)
        if rt.chosen is None:
            raise _Hold("NO_RAIL_AVAILABLE", {"route": rt.to_json()})
        rail_id = rt.chosen.rail
        adapter = adapters[rail_id]
        dest_address = rt.chosen.destination_address
        # Reservations (pre-funded room, attempt, nonce) roll back together if anything below holds.
        with conn.begin_nested():
            _check_prefund(conn, org_id, rail_id, amount, clock.now().date().isoformat())
            att = create_attempt(conn, clock, org_id=org_id, payment_id=pid, rail_id=rail_id)
            view = AttemptView(
                attempt_id=att.id,
                payment_id=pid,
                attempt_no=att.attempt_no,
                rail_id=rail_id,
                idempotency_key=att.idempotency_key,
                amount=amount,
                destination_address=dest_address,
                nonce=None,
                raw_tx=None,
                tx_hash=None,
            )
            evidence: dict[str, Any] = {"rail": rail_id}
            if hasattr(adapter, "prepare"):
                nr: NonceRail = adapter  # type: ignore[assignment]
                try:
                    nonce = _free_nonce(conn, org_id, pid, rail_id, nr.from_address)
                    if nonce is None:
                        nonce = nonces.assign(conn, org_id, nr)
                except nonces.WalletRefused as exc:
                    raise _Hold("NONCE_MISMATCH", {"detail": str(exc)}) from exc
                try:
                    prep = nr.prepare(view, nonce)
                except RailError as exc:
                    raise _Hold("RAIL_PREPARE_FAILED", {"failure_class": exc.failure_class.value}) from exc
                conn.execute(
                    text(
                        "UPDATE attempts SET nonce=:n, raw_tx=:raw, tx_hash=:h, from_address=:f, "
                        "explorer_url=:x "
                        "WHERE org_id=:o AND id=:a"
                    ),
                    {
                        "n": prep.nonce,
                        "raw": prep.raw_tx,
                        "h": prep.tx_hash,
                        "f": prep.from_address.lower(),
                        "x": nr.explorer_url(prep.tx_hash),
                        "o": org_id,
                        "a": att.id,
                    },
                )
                view = dataclasses.replace(view, nonce=prep.nonce, raw_tx=prep.raw_tx, tx_hash=prep.tx_hash)
                evidence.update(nonce=prep.nonce, tx_hash=prep.tx_hash, from_address=prep.from_address)
    except _Hold as h:
        return _hold(conn, clock, org_id, pid, h), None
    append(
        conn,
        clock,
        org_id=org_id,
        actor=ACTOR,
        kind="attempt.created",
        subject_id=pid,
        payload={"attempt_id": att.id, "attempt_no": att.attempt_no, **evidence},
    )
    mark_attempt(conn, clock, org_id=org_id, attempt_id=att.id, to=AttemptStatus.SUBMITTED)
    transition(
        conn,
        clock,
        org_id=org_id,
        payment_id=pid,
        to=Status.SUBMITTED,
        actor=ACTOR,
        reason="attempt submitted",
    )
    return Status.SUBMITTED, view


def _record_failure(conn: Connection, clock: Clock, org_id: str, view: AttemptView, exc: RailError) -> Status:
    if exc.failure_class is FailureClass.TIMEOUT:
        mark_attempt(
            conn,
            clock,
            org_id=org_id,
            attempt_id=view.attempt_id,
            to=AttemptStatus.UNKNOWN,
            evidence=exc.evidence,
        )
        transition(
            conn,
            clock,
            org_id=org_id,
            payment_id=view.payment_id,
            to=Status.UNKNOWN,
            actor=ACTOR,
            reason="no answer from the rail; outcome unknown",
        )
        conn.execute(
            text("UPDATE attempts SET unknown_at=:t WHERE org_id=:o AND id=:a"),
            {"t": clock.now(), "o": org_id, "a": view.attempt_id},
        )
        enqueue(
            conn,
            clock,
            org_id=org_id,
            kind=RESOLVE_JOB,
            payment_id=view.payment_id,
            dedupe_key=f"{view.attempt_id}:0",
            payload={"payment_id": view.payment_id, "step": 0},
            run_at=clock.now() + timedelta(seconds=5),
            max_attempts=3,
        )
        return Status.UNKNOWN
    mark_attempt(
        conn,
        clock,
        org_id=org_id,
        attempt_id=view.attempt_id,
        to=AttemptStatus.FAILED,
        failure_class=exc.failure_class,
        evidence=exc.evidence,
    )
    transition(
        conn,
        clock,
        org_id=org_id,
        payment_id=view.payment_id,
        to=Status.FAILED,
        actor=ACTOR,
        reason=exc.failure_class.value,
    )
    # Retries and failover (EXE-05, RAL-07) decide what follows FAILED; it stays FAILED until then.
    return Status.FAILED


def apply_rail_status(
    engine: Engine, clock: Clock, adapter: RailAdapter, org_id: str, view: AttemptView
) -> Status:
    """Read the rail's answer for a submitted attempt and record it. PENDING changes nothing."""
    st = adapter.status(view)
    with transaction(engine) as conn:
        cur = conn.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p FOR UPDATE"),
            {"o": org_id, "p": view.payment_id},
        ).scalar_one()
        if cur not in (Status.SUBMITTED.value, Status.UNKNOWN.value):
            return Status(cur)
        if st.state == "CONFIRMED":
            mark_attempt(
                conn,
                clock,
                org_id=org_id,
                attempt_id=view.attempt_id,
                to=AttemptStatus.CONFIRMED,
                evidence=st.evidence,
            )
            transition(
                conn,
                clock,
                org_id=org_id,
                payment_id=view.payment_id,
                to=Status.CONFIRMED,
                actor=ACTOR,
                reason="rail confirmed",
            )
            cpt = conn.execute(
                text("SELECT counterparty_id FROM payment_intents WHERE org_id=:o AND id=:p"),
                {"o": org_id, "p": view.payment_id},
            ).scalar_one()
            if cpt:
                refresh_stats(conn, org_id, cpt)
            return Status.CONFIRMED
        if st.state == "FAILED" and st.failure_class is not None:
            return _record_failure(
                conn, clock, org_id, view, RailError(st.failure_class, "rail reported failure", st.evidence)
            )
        return Status(cur)


def send_payment(  # noqa: PLR0911 - each return is a distinct outcome
    engine: Engine,
    clock: Clock,
    adapters: Mapping[str, RailAdapter],
    *,
    org_id: str,
    payment_id: str,
    screening: Screening,
    mandate_key: SecretStr | None = None,
) -> Status:
    try:
        with transaction(engine) as conn:
            status, view = _prepare(conn, clock, adapters, org_id, payment_id, screening, mandate_key)
    except Exception as exc:
        # Fail closed: an unexpected error before anything was broadcast holds the payment.
        log.exception("pre-send failed; holding the payment", extra={"for_payment": payment_id})
        with transaction(engine) as conn:
            cur = conn.execute(
                text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p FOR UPDATE"),
                {"o": org_id, "p": payment_id},
            ).scalar_one()
            if cur != Status.READY.value:
                return Status(cur)
            return _hold(
                conn, clock, org_id, payment_id, _Hold("PRESEND_ERROR", {"error": type(exc).__name__})
            )
    if view is None:
        return status
    adapter = adapters[view.rail_id]
    try:
        adapter.submit(view)
    except RailError as exc:
        with transaction(engine) as conn:
            st = _record_failure(conn, clock, org_id, view, exc)
        return _follow_up(engine, clock, adapters, org_id, payment_id, st)
    except Exception as exc:  # an unclassified error after we tried to send: it may have reached the rail
        with transaction(engine) as conn:
            return _record_failure(
                conn, clock, org_id, view, RailError(FailureClass.TIMEOUT, type(exc).__name__)
            )
    with transaction(engine) as conn:
        append(
            conn,
            clock,
            org_id=org_id,
            actor=ACTOR,
            kind="rail.submitted",
            subject_id=payment_id,
            payload={"attempt_id": view.attempt_id, "rail": view.rail_id, "tx_hash": view.tx_hash},
        )
    try:
        st = apply_rail_status(engine, clock, adapter, org_id, view)
    except RailError:
        return Status.SUBMITTED  # the confirmation poller asks again
    return _follow_up(engine, clock, adapters, org_id, payment_id, st)


def _follow_up(
    engine: Engine,
    clock: Clock,
    adapters: Mapping[str, RailAdapter],
    org_id: str,
    payment_id: str,
    st: Status,
) -> Status:
    """A definitive failure goes straight to the retry and failover rules (EXE-07, RAL-07)."""
    if st is not Status.FAILED:
        return st
    from detent.execution.retry import after_failure

    return after_failure(engine, clock, adapters, org_id=org_id, payment_id=payment_id)
