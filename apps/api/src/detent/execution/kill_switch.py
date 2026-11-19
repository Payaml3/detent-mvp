"""The kill switch (EXE-08, invariant 10, G-15/D-28).

- Engaging (payments lead or on-call) stops new submissions: READY payments are held, and the flag is
  checked inside the lock before every send. UNKNOWN attempts keep resolving, read-only.
- Releasing needs the payments lead, even when on-call engaged it.
- On release, every payment the switch held re-runs the rules with the active version (D-28): EXECUTE
  resumes sending, ESCALATE goes to the exceptions queue, BLOCK stays blocked. Each re-run is audited.
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.roles import Role, allowed
from detent.domain.states import Status
from detent.intents.transition import transition
from detent.policy.screening import MockScreening, Screening
from detent.worker.queue import enqueue

REASON = "KILL_SWITCH_ENGAGED"


def _role(actor: Actor) -> Role:
    try:
        return Role(actor.role or "")
    except ValueError:
        raise PermissionError(f"{actor.id} has no console role") from None


def is_engaged(engine: Engine, org_id: str) -> bool:
    with engine.connect() as conn:
        v = conn.execute(
            text("SELECT engaged FROM kill_switch WHERE org_id=:o"), {"o": org_id}
        ).scalar_one_or_none()
    return v is not False


def engage(engine: Engine, clock: Clock, *, org_id: str, actor: Actor) -> list[str]:
    if not allowed("kill_switch.engage", _role(actor)):
        raise PermissionError(f"{actor.role} may not engage the kill switch")
    held: list[str] = []
    with transaction(engine) as conn:
        conn.execute(
            text("UPDATE kill_switch SET engaged=true, engaged_by=:a, engaged_at=:t WHERE org_id=:o"),
            {"a": actor.id, "t": clock.now(), "o": org_id},
        )
        ready = (
            conn.execute(
                text(
                    "SELECT id FROM payment_intents WHERE org_id=:o AND status='READY' ORDER BY created_at "
                    "FOR UPDATE"
                ),
                {"o": org_id},
            )
            .scalars()
            .all()
        )
        for pid in ready:
            transition(conn, clock, org_id=org_id, payment_id=pid, to=Status.HELD, actor=actor, reason=REASON)
            conn.execute(
                text("UPDATE payment_intents SET held_reason=:r WHERE org_id=:o AND id=:p"),
                {"r": REASON, "o": org_id, "p": pid},
            )
            held.append(pid)
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="kill_switch.engaged",
            subject_id=org_id,
            payload={"held": held},
        )
    return held


def release(
    engine: Engine, clock: Clock, *, org_id: str, actor: Actor, screening: Screening | None = None
) -> dict[str, list[str]]:
    from detent.exceptions.cases import open_case
    from detent.intents.service import SEND_JOB, reevaluate, release_counters

    if not allowed("kill_switch.release", _role(actor)):
        raise PermissionError("only the payments lead releases the kill switch")
    with transaction(engine) as conn:
        conn.execute(
            text("UPDATE kill_switch SET engaged=false, released_by=:a, released_at=:t WHERE org_id=:o"),
            {"a": actor.id, "t": clock.now(), "o": org_id},
        )
        held = (
            conn.execute(
                text(
                    "SELECT id FROM payment_intents WHERE org_id=:o AND status='HELD' AND held_reason=:r "
                    "ORDER BY created_at"
                ),
                {"o": org_id, "r": REASON},
            )
            .scalars()
            .all()
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="kill_switch.released",
            subject_id=org_id,
            payload={"held_payments": list(held)},
        )
    out: dict[str, list[str]] = {"READY": [], "ESCALATED": [], "BLOCKED": []}
    scr = screening or MockScreening.from_fixture()
    for pid in held:
        with transaction(engine) as conn:
            cur = conn.execute(
                text("SELECT status, held_reason FROM payment_intents WHERE org_id=:o AND id=:p FOR UPDATE"),
                {"o": org_id, "p": pid},
            ).one()
            if cur.status != Status.HELD.value or cur.held_reason != REASON:
                continue
            approved = conn.execute(
                text(
                    "SELECT approved_reasons FROM decisions WHERE org_id=:o AND payment_id=:p "
                    "ORDER BY decided_at DESC, id DESC LIMIT 1"
                ),
                {"o": org_id, "p": pid},
            ).scalar_one()
            result, policy = reevaluate(
                conn,
                clock,
                org_id=org_id,
                payment_id=pid,
                screening=scr,
                reason="kill switch released",
                approved_reasons=list(approved) or None,
            )
            conn.execute(
                text("UPDATE payment_intents SET held_reason=NULL WHERE org_id=:o AND id=:p"),
                {"o": org_id, "p": pid},
            )
            if result.outcome == "EXECUTE":
                transition(
                    conn,
                    clock,
                    org_id=org_id,
                    payment_id=pid,
                    to=Status.READY,
                    actor=actor,
                    reason="kill switch released; policy re-run EXECUTE",
                )
                enqueue(
                    conn,
                    clock,
                    org_id=org_id,
                    kind=SEND_JOB,
                    payment_id=pid,
                    dedupe_key=f"{pid}:release:{clock.now().timestamp()}",
                    payload={"payment_id": pid},
                )
                out["READY"].append(pid)
            elif result.outcome == "BLOCK":
                transition(
                    conn,
                    clock,
                    org_id=org_id,
                    payment_id=pid,
                    to=Status.BLOCKED,
                    actor=actor,
                    reason="kill switch released; policy re-run BLOCK",
                )
                release_counters(conn, org_id, pid)
                out["BLOCKED"].append(pid)
            else:
                transition(
                    conn,
                    clock,
                    org_id=org_id,
                    payment_id=pid,
                    to=Status.ESCALATED,
                    actor=actor,
                    reason="kill switch released; policy re-run ESCALATE",
                )
                release_counters(conn, org_id, pid)
                open_case(
                    conn, clock, org_id=org_id, payment_id=pid, reasons=result.reasons, rules=policy.rules
                )
                out["ESCALATED"].append(pid)
    return out
