"""The UNKNOWN resolver (EXE-05, EXE-06, invariant 3).

An UNKNOWN attempt is resolved only by definitive rail evidence:
- CONFIRMED needs receipt status 1 and the rail's confirmation threshold;
- FAILED needs receipt status 0, the nonce consumed by another transaction, or the rail's definitive
  "not found";
- a transaction the node has never seen is re-broadcast: the same signed bytes, never a new one
  (not while the kill switch is engaged; resolving stays read-only then).

Still UNKNOWN after ``execution.unknown_stuck_after`` opens an UNKNOWN_STUCK case owned by the
payments lead, who can keep waiting or approve a cancel-by-replacement. Even then the outcome is read
from the chain: whichever transaction lands decides.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import re
from collections.abc import Mapping
from datetime import timedelta
from statistics import median_low
from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.money import Currency, Money
from detent.domain.roles import Role, allowed
from detent.domain.states import AttemptStatus, FailureClass, Status
from detent.execution.attempts import mark_attempt
from detent.intents.registry import refresh_stats
from detent.intents.transition import transition
from detent.policy.store import active_policy
from detent.rails.base import AttemptView, RailAdapter, RailError

log = logging.getLogger("detent.execution")
ACTOR = Actor.system("resolver")
DEFAULT_STUCK_AFTER = timedelta(minutes=15)
SCHEDULE_SECONDS = (5, 15, 30, 60)  # then every 2 minutes (spec/06)
EVERY_AFTER = 120


def next_poll_delay(step: int) -> timedelta:
    return timedelta(seconds=SCHEDULE_SECONDS[step] if step < len(SCHEDULE_SECONDS) else EVERY_AFTER)


def _duration(value: str | None) -> timedelta:
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", value or "")
    if not m or not any(m.groups()):
        return DEFAULT_STUCK_AFTER
    h, mi, s = (int(x or 0) for x in m.groups())
    return timedelta(hours=h, minutes=mi, seconds=s)


def _load(conn: Connection, org_id: str, payment_id: str, *, lock: bool) -> tuple[Any, Any] | None:
    p = conn.execute(
        text(
            "SELECT p.id, p.status, p.counterparty_id, p.amount_minor, p.currency, p.created_at, "
            "coalesce(d.address, d.account_masked) AS address "
            "FROM payment_intents p LEFT JOIN destinations d ON d.org_id = p.org_id AND d.id = "
            "p.destination_id "
            "WHERE p.org_id=:o AND p.id=:p" + (" FOR UPDATE OF p" if lock else "")
        ),
        {"o": org_id, "p": payment_id},
    ).one_or_none()
    if p is None:
        return None
    a = conn.execute(
        text(
            "SELECT * FROM attempts WHERE org_id=:o AND payment_id=:p AND status='UNKNOWN'"  # noqa: S608
            + (" FOR UPDATE" if lock else "")
        ),
        {"o": org_id, "p": payment_id},
    ).one_or_none()
    return p, a


def _view(p: Any, a: Any) -> AttemptView:
    return AttemptView(
        a.id,
        p.id,
        a.attempt_no,
        a.rail_id,
        a.idempotency_key,
        Money(int(p.amount_minor), Currency(p.currency)),
        p.address,
        a.nonce,
        a.raw_tx,
        a.tx_hash,
    )


def _kill_switch_engaged(conn: Connection, org_id: str) -> bool:
    v = conn.execute(
        text("SELECT engaged FROM kill_switch WHERE org_id=:o"), {"o": org_id}
    ).scalar_one_or_none()
    return v is not False


def resolve_unknown(
    engine: Engine, clock: Clock, adapters: Mapping[str, RailAdapter], *, org_id: str, payment_id: str
) -> Status:
    with engine.connect() as conn:
        loaded = _load(conn, org_id, payment_id, lock=False)
        if loaded is None:
            raise LookupError(payment_id)
        p, a = loaded
        if p.status != Status.UNKNOWN.value or a is None:
            return Status(p.status)
        engaged = _kill_switch_engaged(conn, org_id)
    adapter = adapters.get(a.rail_id)
    if adapter is None or not hasattr(adapter, "resolve"):
        return _maybe_stuck(engine, clock, org_id, payment_id, {"note": "no adapter to ask"})
    view = _view(p, a)
    res = adapter.resolve(view)
    if res.rebroadcast and not engaged:
        try:
            adapter.submit(view)
        except RailError as exc:
            log.warning(
                "re-broadcast got no answer",
                extra={"for_payment": payment_id, "error": exc.failure_class.value},
            )
        with transaction(engine) as conn:
            append(
                conn,
                clock,
                org_id=org_id,
                actor=ACTOR,
                kind="attempt.rebroadcast",
                subject_id=payment_id,
                payload={"attempt_id": a.id, "tx_hash": a.tx_hash, "note": "same signed transaction"},
            )
        res = dataclasses.replace(adapter.resolve(view), rebroadcast=False)
    if res.state == "UNKNOWN":
        return _maybe_stuck(engine, clock, org_id, payment_id, res.evidence)
    with transaction(engine) as conn:
        locked = _load(conn, org_id, payment_id, lock=True)
        assert locked is not None
        p, a = locked
        if p.status != Status.UNKNOWN.value or a is None:
            return Status(p.status)
        evidence = {**res.evidence, "resolved_from": "UNKNOWN"}
        if res.state == "CONFIRMED":
            mark_attempt(
                conn,
                clock,
                org_id=org_id,
                attempt_id=a.id,
                to=AttemptStatus.CONFIRMED,
                evidence=evidence,
                actor=ACTOR,
            )
            transition(
                conn,
                clock,
                org_id=org_id,
                payment_id=payment_id,
                to=Status.CONFIRMED,
                actor=ACTOR,
                reason="rail evidence: confirmed",
            )
            if p.counterparty_id:
                refresh_stats(conn, org_id, p.counterparty_id)
            _close_stuck_case(conn, clock, org_id, payment_id, "resolved: confirmed")
            return Status.CONFIRMED
        mark_attempt(
            conn,
            clock,
            org_id=org_id,
            attempt_id=a.id,
            to=AttemptStatus.FAILED,
            failure_class=res.failure_class or FailureClass.TECHNICAL_FINAL,
            evidence=evidence,
            actor=ACTOR,
        )
        transition(
            conn,
            clock,
            org_id=org_id,
            payment_id=payment_id,
            to=Status.FAILED,
            actor=ACTOR,
            reason=f"rail evidence: {res.failure_class.value if res.failure_class else 'failed'}",
        )
        _close_stuck_case(conn, clock, org_id, payment_id, "resolved: failed")
    from detent.execution.retry import after_failure

    return after_failure(engine, clock, adapters, org_id=org_id, payment_id=payment_id)


def _close_stuck_case(conn: Connection, clock: Clock, org_id: str, payment_id: str, why: str) -> None:
    case = conn.execute(
        text(
            "SELECT id FROM exception_cases WHERE org_id=:o AND payment_id=:p AND type='unknown_stuck' "
            "AND status IN ('OPEN','HELD_OVERDUE') FOR UPDATE"
        ),
        {"o": org_id, "p": payment_id},
    ).scalar_one_or_none()
    if case is None:
        return
    conn.execute(
        text(
            "UPDATE exception_cases SET status='RESOLVED', resolution='superseded', resolution_reason=:r, "
            "resolved_by='system:resolver', resolved_at=:t WHERE org_id=:o AND id=:c"
        ),
        {"r": why, "t": clock.now(), "o": org_id, "c": case},
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=ACTOR,
        kind="case.resolved",
        subject_id=case,
        payload={"payment_id": payment_id, "resolution": "superseded", "reason": why},
    )


def _maybe_stuck(
    engine: Engine, clock: Clock, org_id: str, payment_id: str, evidence: dict[str, Any]
) -> Status:
    from detent.exceptions.cases import open_case

    with transaction(engine) as conn:
        a = conn.execute(
            text("SELECT unknown_at FROM attempts WHERE org_id=:o AND payment_id=:p AND status='UNKNOWN'"),
            {"o": org_id, "p": payment_id},
        ).one_or_none()
        policy = active_policy(conn, org_id)
        after = _duration(policy.rules.execution.unknown_stuck_after if policy.rules.execution else None)
        if a is None or a.unknown_at is None or clock.now() - a.unknown_at < after:
            return Status.UNKNOWN
        open_already = conn.execute(
            text(
                "SELECT 1 FROM exception_cases WHERE org_id=:o AND payment_id=:p AND status IN "
                "('OPEN','HELD_OVERDUE')"
            ),
            {"o": org_id, "p": payment_id},
        ).first()
        if open_already is None:
            open_case(
                conn,
                clock,
                org_id=org_id,
                payment_id=payment_id,
                reasons=["UNKNOWN_STUCK"],
                rules=policy.rules,
                case_type="unknown_stuck",
            )
            append(
                conn,
                clock,
                org_id=org_id,
                actor=ACTOR,
                kind="payment.unknown_stuck",
                subject_id=payment_id,
                payload={"since": a.unknown_at.isoformat(), "evidence": evidence},
            )
    return Status.UNKNOWN


def keep_waiting(
    engine: Engine, clock: Clock, *, org_id: str, case_id: str, actor: Actor, reason: str
) -> None:
    """The first option on an UNKNOWN_STUCK case: record the choice; the resolver keeps polling."""
    with transaction(engine) as conn:
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="case.keep_waiting",
            subject_id=case_id,
            payload={"reason": reason},
        )


def approve_cancel_by_replacement(
    engine: Engine,
    clock: Clock,
    adapters: Mapping[str, RailAdapter],
    *,
    org_id: str,
    case_id: str,
    actor: Actor,
    reason: str,
) -> str:
    """The second option, payments lead only: sign a zero-value self-transfer with the same nonce and a
    higher fee, store it, then broadcast it. The payment stays UNKNOWN until the chain decides."""
    if not allowed("unknown.cancel_by_replacement", Role(actor.role or "admin")):
        raise PermissionError("only the payments lead approves a cancel-by-replacement")
    if not reason.strip():
        raise ValueError("a reason is required")
    with transaction(engine) as conn:
        case = conn.execute(
            text(
                "SELECT id, payment_id, type, status FROM exception_cases WHERE org_id=:o AND id=:c FOR "
                "UPDATE"
            ),
            {"o": org_id, "c": case_id},
        ).one()
        if case.type != "unknown_stuck" or case.status not in ("OPEN", "HELD_OVERDUE"):
            raise ValueError("not an open UNKNOWN_STUCK case")
        loaded = _load(conn, org_id, case.payment_id, lock=True)
        assert loaded is not None
        p, a = loaded
        if a is None:
            raise ValueError("the payment has no UNKNOWN attempt")
        adapter = adapters[a.rail_id]
        view = _view(p, a)
        raw, h = adapter.sign_replacement(view)  # type: ignore[attr-defined]
        conn.execute(
            text("UPDATE attempts SET replacement_tx_hash=:h WHERE org_id=:o AND id=:a"),
            {"h": h, "o": org_id, "a": a.id},
        )
        conn.execute(
            text(
                "UPDATE exception_cases SET status='RESOLVED', resolution='approved', resolution_reason=:r, "
                "resolved_by=:by, resolved_at=:t WHERE org_id=:o AND id=:c"
            ),
            {"r": reason.strip(), "by": actor.id, "t": clock.now(), "o": org_id, "c": case_id},
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="attempt.replacement_approved",
            subject_id=p.id,
            payload={
                "case_id": case_id,
                "attempt_id": a.id,
                "nonce": a.nonce,
                "replacement_tx_hash": h,
                "reason": reason.strip(),
            },
        )
    try:
        adapter.broadcast_raw(raw, h, view.attempt_id)  # type: ignore[attr-defined]
    except RailError as exc:
        log.warning(
            "replacement broadcast got no answer",
            extra={"case_id": case_id, "error": exc.failure_class.value},
        )
    return str(h)


def resolution_times(engine: Engine, org_id: str) -> dict[str, int]:
    """EXE-06: seconds from UNKNOWN to a definitive answer, for the results report."""
    with engine.connect() as conn:
        secs = [
            int(r.s)
            for r in conn.execute(
                text(
                    "SELECT extract(epoch FROM resolved_at - unknown_at) AS s FROM attempts WHERE org_id=:o "
                    "AND unknown_at IS NOT NULL AND resolved_at IS NOT NULL ORDER BY s"
                ),
                {"o": org_id},
            )
        ]
    if not secs:
        return {"count": 0, "median_seconds": 0, "p95_seconds": 0}
    p95 = secs[max(0, math.ceil(0.95 * len(secs)) - 1)]
    return {"count": len(secs), "median_seconds": int(median_low(secs)), "p95_seconds": p95}
