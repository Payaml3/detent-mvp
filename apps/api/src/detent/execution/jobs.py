"""Worker jobs for orchestration: send a READY payment, poll a submitted one, reconcile nonces at startup.

Sending needs transactions of its own (the signed transaction must be stored before it is broadcast),
so these handlers use the engine and keep the job's own transaction for marking the job done.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import Engine, text

from detent.clock import Clock
from detent.domain.money import Currency, Money
from detent.domain.states import Status
from detent.execution import nonces
from detent.execution.send import apply_rail_status, recover_interrupted_send, send_payment
from detent.intents.service import SEND_JOB
from detent.policy.screening import MockScreening
from detent.rails.base import AttemptView, RailAdapter
from detent.rails.registry import build_adapters
from detent.settings import Settings
from detent.worker.queue import enqueue
from detent.worker.registry import JobContext, handler

log = logging.getLogger("detent.execution")
CONFIRM_JOB = "payment.confirm"


class StillPending(RuntimeError):
    """Raised by the confirmation poller so the queue retries the job with backoff."""


def _adapters(ctx: JobContext) -> dict[str, RailAdapter]:
    assert ctx.engine is not None
    assert ctx.settings is not None
    return build_adapters(ctx.settings, ctx.engine, ctx.job.org_id)


@handler(SEND_JOB)
def send_job(ctx: JobContext) -> None:
    assert ctx.engine is not None
    pid = str(ctx.job.payload["payment_id"])
    if (
        ctx.job.attempts > 1
        and recover_interrupted_send(ctx.engine, ctx.clock, org_id=ctx.job.org_id, payment_id=pid) is not None
    ):
        return  # the worker died mid-send last time: UNKNOWN now, and the resolver takes it from here
    st = send_payment(
        ctx.engine,
        ctx.clock,
        _adapters(ctx),
        org_id=ctx.job.org_id,
        payment_id=pid,
        screening=MockScreening.from_fixture(),
        mandate_key=ctx.settings.mandate_signing_key_demo if ctx.settings else None,
    )
    if st is Status.SUBMITTED:
        enqueue(
            ctx.conn,
            ctx.clock,
            org_id=ctx.job.org_id,
            kind=CONFIRM_JOB,
            payment_id=pid,
            dedupe_key=pid,
            payload={"payment_id": pid},
            run_at=ctx.clock.now() + timedelta(seconds=5),
            max_attempts=20,
        )


@handler(CONFIRM_JOB)
def confirm_job(ctx: JobContext) -> None:
    """Poll the rail for a SUBMITTED attempt. UNKNOWN attempts belong to the resolver (EXE-06)."""
    assert ctx.engine is not None
    pid = str(ctx.job.payload["payment_id"])
    org = ctx.job.org_id
    with ctx.engine.connect() as conn:
        a = conn.execute(
            text(
                "SELECT a.id, a.attempt_no, a.rail_id, a.idempotency_key, a.nonce, a.raw_tx, a.tx_hash, "
                "p.amount_minor, p.currency, d.address FROM attempts a JOIN payment_intents p "
                "ON p.org_id = a.org_id AND p.id = a.payment_id LEFT JOIN destinations d "
                "ON d.org_id = p.org_id AND d.id = p.destination_id "
                "WHERE a.org_id=:o AND a.payment_id=:p AND a.status='SUBMITTED' AND p.status='SUBMITTED'"
            ),
            {"o": org, "p": pid},
        ).one_or_none()
    if a is None:
        return
    adapter = _adapters(ctx).get(a.rail_id)
    if adapter is None:
        raise StillPending(f"no adapter for {a.rail_id}")
    view = AttemptView(
        a.id,
        pid,
        a.attempt_no,
        a.rail_id,
        a.idempotency_key,
        Money(int(a.amount_minor), Currency(a.currency)),
        a.address,
        a.nonce,
        a.raw_tx,
        a.tx_hash,
    )
    st = apply_rail_status(ctx.engine, ctx.clock, adapter, org, view)
    if st is Status.SUBMITTED:
        raise StillPending(pid)
    if st is Status.FAILED:
        from detent.execution.retry import after_failure

        after_failure(ctx.engine, ctx.clock, _adapters(ctx), org_id=org, payment_id=pid)


def reconcile_all(engine: Engine, clock: Clock, settings: Settings) -> list[nonces.NonceProblem]:
    """Worker startup: every organisation with a used wallet is checked against the chain."""
    with engine.connect() as conn:
        orgs = (
            conn.execute(
                text("SELECT DISTINCT org_id FROM wallet_nonces").execution_options(
                    cross_org="worker startup: nonce reconciliation covers every organisation"
                )
            )
            .scalars()
            .all()
        )
    problems: list[nonces.NonceProblem] = []
    for org in orgs:
        try:
            problems += nonces.reconcile(engine, clock, org, build_adapters(settings, engine, org))
        except Exception:
            log.exception("nonce reconciliation failed", extra={"org_id": org})
    for p in problems:
        log.error(
            "wallet refused: stored nonce disagrees with the chain",
            extra={"rail": p.rail_id, "address": p.address, "stored": p.stored, "chain": p.chain},
        )
    return problems


@handler("payment.resolve_unknown")
def resolve_job(ctx: JobContext) -> None:
    """EXE-06: poll an UNKNOWN payment on the spec/06 schedule (+5 s, +15 s, +30 s, +60 s, then every 2 "
    "min)."""
    from detent.execution.resolver import next_poll_delay, resolve_unknown

    assert ctx.engine is not None
    pid = str(ctx.job.payload["payment_id"])
    step = int(ctx.job.payload.get("step", 0))
    st = resolve_unknown(ctx.engine, ctx.clock, _adapters(ctx), org_id=ctx.job.org_id, payment_id=pid)
    if st is Status.UNKNOWN:
        enqueue(
            ctx.conn,
            ctx.clock,
            org_id=ctx.job.org_id,
            kind="payment.resolve_unknown",
            payment_id=pid,
            dedupe_key=f"{pid}:resolve:{step + 1}",
            payload={"payment_id": pid, "step": step + 1},
            run_at=ctx.clock.now() + next_poll_delay(step + 1),
            max_attempts=3,
        )
