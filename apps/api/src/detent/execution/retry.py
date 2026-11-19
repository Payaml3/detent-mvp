"""What follows a definitive failure: deterministic retry, failover, or FAILED_FINAL (EXE-07, RAL-07).

- Only TECHNICAL_RETRYABLE retries, on the same rail, up to ``retry.max_attempts`` with the configured
  backoff. Every retry keeps the payment ID and is audited with the rule that allowed it.
- TECHNICAL_FINAL (or retries exhausted) may fail over to another rail, only if the intent allows a
  network switch and another rail is eligible. The payment ID stays; ``attempt_no`` increments.
- REJECTED_BY_RAIL never retries and never fails over. A BLOCK never gets here.
- Otherwise FAILED_FINAL, and the payment's amount stops counting against the caps.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from sqlalchemy import Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.states import FailureClass, Status
from detent.intents.service import SEND_JOB, release_counters
from detent.intents.transition import transition
from detent.policy.store import active_policy
from detent.rails.base import RailAdapter
from detent.routing.engine import route
from detent.worker.queue import enqueue

ACTOR = Actor.system("execution")


def after_failure(
    engine: Engine, clock: Clock, adapters: Mapping[str, RailAdapter], *, org_id: str, payment_id: str
) -> Status:
    with transaction(engine) as conn:
        p = conn.execute(
            text(
                "SELECT p.*, d.address, d.account_masked FROM payment_intents p LEFT JOIN destinations d "
                "ON d.org_id = p.org_id "
                "AND d.id = p.destination_id WHERE p.org_id=:o AND p.id=:p FOR UPDATE OF p"
            ),
            {"o": org_id, "p": payment_id},
        ).one()
        if p.status != Status.FAILED.value:
            return Status(p.status)
        attempts = conn.execute(
            text(
                "SELECT attempt_no, rail_id, failure_class FROM attempts WHERE org_id=:o AND payment_id=:p "
                "ORDER BY attempt_no"
            ),
            {"o": org_id, "p": payment_id},
        ).all()
        last = attempts[-1]
        fc = FailureClass(last.failure_class)
        rules = active_policy(conn, org_id).rules
        retry = rules.retry
        on_rail = sum(1 for a in attempts if a.rail_id == last.rail_id)
        n = len(attempts)

        if (
            fc is FailureClass.TECHNICAL_RETRYABLE
            and retry
            and fc.value in retry.retryable
            and on_rail < retry.max_attempts
        ):
            backoff = (
                retry.backoff_seconds[min(on_rail - 1, len(retry.backoff_seconds) - 1)]
                if retry.backoff_seconds
                else 0
            )
            rule = {
                "rule": "retry",
                "failure_class": fc.value,
                "attempt": on_rail,
                "max_attempts": retry.max_attempts,
                "backoff_seconds": backoff,
                "rail": last.rail_id,
            }
            transition(
                conn,
                clock,
                org_id=org_id,
                payment_id=payment_id,
                to=Status.READY,
                actor=ACTOR,
                reason=f"retry {on_rail + 1} of {retry.max_attempts} on {last.rail_id} after {fc.value}",
            )
            append(
                conn,
                clock,
                org_id=org_id,
                actor=ACTOR,
                kind="payment.retry_scheduled",
                subject_id=payment_id,
                payload=rule,
            )
            enqueue(
                conn,
                clock,
                org_id=org_id,
                kind=SEND_JOB,
                payment_id=payment_id,
                dedupe_key=f"{payment_id}:{n + 1}",
                payload={"payment_id": payment_id},
                run_at=clock.now() + timedelta(seconds=backoff),
            )
            return Status.READY

        can_failover = fc is FailureClass.TECHNICAL_FINAL or (
            fc is FailureClass.TECHNICAL_RETRYABLE and retry is not None and on_rail >= retry.max_attempts
        )
        if can_failover and p.allow_network_switch:
            r = route(
                conn,
                adapters,
                org_id=org_id,
                payment=p,
                day=clock.now().date().isoformat(),
                exclude={last.rail_id},
            )
            if r.chosen is not None and r.chosen.rail != last.rail_id:
                transition(
                    conn,
                    clock,
                    org_id=org_id,
                    payment_id=payment_id,
                    to=Status.READY,
                    actor=ACTOR,
                    reason=f"failover from {last.rail_id} to {r.chosen.rail} after {fc.value}",
                )
                append(
                    conn,
                    clock,
                    org_id=org_id,
                    actor=ACTOR,
                    kind="payment.failover_scheduled",
                    subject_id=payment_id,
                    payload={
                        "rule": "failover",
                        "from": last.rail_id,
                        "to": r.chosen.rail,
                        "failure_class": fc.value,
                        "allow_network_switch": True,
                        "route": r.to_json(),
                    },
                )
                enqueue(
                    conn,
                    clock,
                    org_id=org_id,
                    kind=SEND_JOB,
                    payment_id=payment_id,
                    dedupe_key=f"{payment_id}:{n + 1}",
                    payload={"payment_id": payment_id},
                )
                return Status.READY

        why = {
            FailureClass.REJECTED_BY_RAIL: "rejected by the rail: never retried or re-routed",
            FailureClass.TECHNICAL_FINAL: "technical failure and no failover allowed or available",
            FailureClass.TECHNICAL_RETRYABLE: "retries exhausted and no failover allowed or available",
        }.get(fc, fc.value)
        transition(
            conn, clock, org_id=org_id, payment_id=payment_id, to=Status.FAILED_FINAL, actor=ACTOR, reason=why
        )
        release_counters(conn, org_id, payment_id)
        return Status.FAILED_FINAL
