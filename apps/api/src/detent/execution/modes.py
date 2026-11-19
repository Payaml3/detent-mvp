"""Shadow, Assist and Auto (EXE-09).

- Shadow: decisions are recorded and nothing is sent.
- Assist: an EXECUTE decision waits for a person to click Send.
- Auto: an EXECUTE decision is sent by the worker.

A mode change is proposed by one of the payments lead and the compliance lead and approved by the
other (C-09), and both steps are audited. The mode is read again inside the send lock (G-16), so a
payment that became READY under Auto waits for a click if the mode is now Assist, and nothing is sent
in Shadow. Who may click Send (G-09, Proposed): the roles that may approve an exception, never the
person who initiated the payment.

"Orchestrate" is not a separate mode: it means routing is choosing between two or more connected rails.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.domain.roles import Role, allowed, mode_change_approved
from detent.domain.states import Status
from detent.worker.queue import enqueue

MODES = ("shadow", "assist", "auto")


class ModeError(Exception):
    status = 409
    code = "conflict"

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code


def _role(actor: Actor) -> Role:
    try:
        return Role(actor.role or "")
    except ValueError:
        raise ModeError(f"{actor.id} has no console role", status=403, code="insufficient_role") from None


def current_mode(conn: Connection, org_id: str, *, lock: bool = False) -> str:
    sql = (
        "SELECT mode FROM organisations WHERE org_id=:o FOR SHARE"
        if lock
        else "SELECT mode FROM organisations WHERE org_id=:o"
    )
    return str(conn.execute(text(sql), {"o": org_id}).scalar_one())


def propose_mode_change(
    engine: Engine, clock: Clock, *, org_id: str, actor: Actor, to_mode: str, reason: str
) -> str:
    role = _role(actor)
    if not allowed("org.change_mode.propose", role):
        raise ModeError(f"{role.value} may not propose a mode change", status=403, code="insufficient_role")
    if to_mode not in MODES:
        raise ModeError(f"unknown mode {to_mode!r}", status=422, code="invalid_mode")
    if not reason.strip():
        raise ModeError("a reason is required", status=422, code="reason_required")
    with transaction(engine) as conn:
        mode = str(
            conn.execute(
                text("SELECT mode FROM organisations WHERE org_id=:o FOR UPDATE"), {"o": org_id}
            ).scalar_one()
        )
        if mode == to_mode:
            raise ModeError(f"the mode is already {mode}")
        pending = conn.execute(
            text("SELECT to_mode FROM mode_changes WHERE org_id=:o AND status='proposed'"), {"o": org_id}
        ).scalar_one_or_none()
        if pending:
            raise ModeError(f"a change to {pending} is already waiting for approval")
        now = clock.now()
        ch = new_id(Prefix.MCH, now)
        conn.execute(
            text(
                "INSERT INTO mode_changes (id, org_id, from_mode, to_mode, reason, proposed_by, "
                "proposed_role, "
                "status, created_at) VALUES (:id, :o, :f, :t, :r, :p, :pr, 'proposed', :now)"
            ),
            {
                "id": ch,
                "o": org_id,
                "f": mode,
                "t": to_mode,
                "r": reason.strip(),
                "p": actor.id,
                "pr": role.value,
                "now": now,
            },
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="org.mode_change_proposed",
            subject_id=ch,
            payload={"from": mode, "to": to_mode, "reason": reason.strip()},
        )
    return ch


def approve_mode_change(engine: Engine, clock: Clock, *, org_id: str, change_id: str, actor: Actor) -> str:
    role = _role(actor)
    with transaction(engine) as conn:
        ch = conn.execute(
            text("SELECT * FROM mode_changes WHERE org_id=:o AND id=:i FOR UPDATE"),
            {"o": org_id, "i": change_id},
        ).one_or_none()
        if ch is None:
            raise ModeError(f"no mode change {change_id}", status=404, code="not_found")
        if ch.status != "proposed":
            raise ModeError(f"mode change {change_id} is {ch.status}")
        if not mode_change_approved(
            proposer=(ch.proposed_by, Role(ch.proposed_role)), approver=(actor.id, role)
        ):
            raise ModeError(
                "a mode change needs both the payments lead and the compliance lead, as two different people",
                status=403,
                code="insufficient_role",
            )
        mode = str(
            conn.execute(
                text("SELECT mode FROM organisations WHERE org_id=:o FOR UPDATE"), {"o": org_id}
            ).scalar_one()
        )
        if mode != ch.from_mode:
            raise ModeError(f"the mode changed to {mode} after this was proposed; propose again")
        now = clock.now()
        conn.execute(text("UPDATE organisations SET mode=:m WHERE org_id=:o"), {"m": ch.to_mode, "o": org_id})
        conn.execute(
            text(
                "UPDATE mode_changes SET status='applied', approved_by=:a, approved_role=:r, decided_at=:t "
                "WHERE org_id=:o AND id=:i"
            ),
            {"a": actor.id, "r": role.value, "t": now, "o": org_id, "i": change_id},
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="org.mode_changed",
            subject_id=org_id,
            payload={
                "from": ch.from_mode,
                "to": ch.to_mode,
                "proposed_by": ch.proposed_by,
                "approved_by": actor.id,
                "reason": ch.reason,
                "change_id": change_id,
            },
        )
        return str(ch.to_mode)


def withdraw_mode_change(engine: Engine, clock: Clock, *, org_id: str, change_id: str, actor: Actor) -> None:
    role = _role(actor)
    if not allowed("org.change_mode.propose", role):
        raise ModeError(f"{role.value} may not withdraw a mode change", status=403, code="insufficient_role")
    with transaction(engine) as conn:
        n = conn.execute(
            text(
                "UPDATE mode_changes SET status='withdrawn', decided_at=:t WHERE org_id=:o AND id=:i "
                "AND status='proposed' RETURNING id"
            ),
            {"t": clock.now(), "o": org_id, "i": change_id},
        ).scalar_one_or_none()
        if n is None:
            raise ModeError(f"no open mode change {change_id}", status=404, code="not_found")
        append(
            conn, clock, org_id=org_id, actor=actor, kind="org.mode_change_withdrawn", subject_id=change_id
        )


def pending_mode_change(conn: Connection, org_id: str) -> Any:
    return conn.execute(
        text("SELECT * FROM mode_changes WHERE org_id=:o AND status='proposed'"), {"o": org_id}
    ).one_or_none()


def hold_for_click(conn: Connection, clock: Clock, org_id: str, payment_id: str, mode: str) -> None:
    """G-16: called by the send path, under the payment's row lock, when the mode forbids sending now."""
    conn.execute(
        text("UPDATE payment_intents SET awaiting_send_click=true, updated_at=:t WHERE org_id=:o AND id=:p"),
        {"t": clock.now(), "o": org_id, "p": payment_id},
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=Actor.system("execution"),
        kind="payment.awaiting_send_click",
        subject_id=payment_id,
        payload={"mode": mode, "reason": "the mode is read at send time (G-16)"},
    )


def confirm_send(engine: Engine, clock: Clock, *, org_id: str, payment_id: str, actor: Actor) -> None:
    """Assist mode: a person clicks Send. The send itself runs in the worker, with every pre-send check."""
    from detent.intents.service import SEND_JOB

    role = _role(actor)
    if not allowed("exception.approve", role):
        raise ModeError(f"{role.value} may not click Send", status=403, code="insufficient_role")
    with transaction(engine) as conn:
        p = conn.execute(
            text(
                "SELECT status, awaiting_send_click, initiated_by FROM payment_intents WHERE "
                "org_id=:o AND id=:p "
                "FOR UPDATE"
            ),
            {"o": org_id, "p": payment_id},
        ).one_or_none()
        if p is None:
            raise ModeError(f"no payment {payment_id}", status=404, code="not_found")
        if p.status != Status.READY.value or not p.awaiting_send_click:
            raise ModeError(f"payment {payment_id} is {p.status} and not waiting for a Send click")
        if p.initiated_by == actor.id:
            raise ModeError(
                "the person who initiated the payment cannot click Send",
                status=403,
                code="self_approval_forbidden",
            )
        mode = current_mode(conn, org_id, lock=True)
        if mode == "shadow":
            raise ModeError("the mode is shadow: nothing is sent", code="shadow_mode")
        now = clock.now()
        conn.execute(
            text(
                "UPDATE payment_intents SET awaiting_send_click=false, send_confirmed_by=:a, updated_at=:t "
                "WHERE org_id=:o AND id=:p"
            ),
            {"a": actor.id, "t": now, "o": org_id, "p": payment_id},
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="payment.send_confirmed",
            subject_id=payment_id,
            payload={"mode": mode},
        )
        enqueue(
            conn,
            clock,
            org_id=org_id,
            kind=SEND_JOB,
            payment_id=payment_id,
            dedupe_key=f"{payment_id}:click:{now.timestamp()}",
            payload={"payment_id": payment_id},
        )


def orchestrate_status(conn: Connection, org_id: str) -> dict[str, Any]:
    n = int(
        conn.execute(
            text("SELECT count(*) FROM rails WHERE org_id=:o AND enabled"), {"o": org_id}
        ).scalar_one()
    )
    return {"enabled": n >= 2, "rails": n}
