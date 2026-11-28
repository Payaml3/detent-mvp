"""Mode gates (SHD-03, founder D-41): evidence and sign-off for each move from Shadow to Assist to Auto.

- ``measure`` reads the last 30 days of shadow rows (every import; when a platform reference appears in more
  than one import, the newest import's row counts) and compares DekernAI's decisions with the platform's own.
- The gate passes when agreement is at least the organisation's ``gate_agreement_bp`` (9500, D-41) and there
  are zero unsafe approvals (DekernAI would execute, the platform rejected). It is frozen when it is created.
- The payments lead and the compliance lead each sign it, as two different people, and only a passed gate can
  be signed. A move upward (shadow to assist or auto, assist to auto) names the gate it relies on; for a
  production organisation (DSH-13) the signed, passed gate is required; a sandbox one may name one. The
  applied mode change is linked to it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.domain.roles import Role
from detent.shadow.report import agreement

WINDOW = timedelta(days=30)
RANK = {"shadow": 0, "assist": 1, "auto": 2}


class GateError(Exception):
    def __init__(self, message: str, *, status: int = 409, code: str = "conflict") -> None:
        super().__init__(message)
        self.status, self.code = status, code


def is_upward(from_mode: str, to_mode: str) -> bool:
    return RANK.get(to_mode, -1) > RANK.get(from_mode, 99)


def measure(conn: Connection, org_id: str, end: datetime) -> dict[str, Any]:
    start = end - WINDOW
    rows = conn.execute(
        text(
            "SELECT DISTINCT ON (coalesce(r.platform_ref, r.id)) r.* FROM shadow_rows r "
            "JOIN shadow_imports i ON i.org_id = r.org_id AND i.id = r.import_id "
            "WHERE r.org_id=:o AND r.occurred_at >= :s AND r.occurred_at < :e "
            "ORDER BY coalesce(r.platform_ref, r.id), i.created_at DESC, i.id DESC"
        ),
        {"o": org_id, "s": start, "e": end},
    ).all()
    threshold = int(
        conn.execute(
            text("SELECT gate_agreement_bp FROM organisations WHERE org_id=:o"), {"o": org_id}
        ).scalar_one()
    )
    agr = agreement(list(rows))
    passed = bool(agr["compared"]) and (agr["rate_bp"] or 0) >= threshold and not agr["unsafe"]
    return {
        "period_from": start,
        "period_to": end,
        "compared": agr["compared"],
        "agreed": agr["agreed"],
        "rate_bp": agr["rate_bp"],
        "rate": agr["rate"],
        "unsafe": [{"ref": r.platform_ref, "row_id": r.id} for r in agr["unsafe"]],
        "disagreements": len(agr["disagreements"]),
        "threshold_bp": threshold,
        "passed": passed,
    }


def create_gate(engine: Engine, clock: Clock, *, org_id: str, actor: Actor, to_mode: str) -> str:
    with transaction(engine) as conn:
        mode = str(
            conn.execute(text("SELECT mode FROM organisations WHERE org_id=:o"), {"o": org_id}).scalar_one()
        )
        if not is_upward(mode, to_mode):
            raise GateError(f"a gate is for a move up from {mode}; {to_mode} is not one", status=422)
        now = clock.now()
        m = measure(conn, org_id, now)
        gid = new_id(Prefix.MGT, now)
        conn.execute(
            text(
                "INSERT INTO mode_gates (id, org_id, from_mode, to_mode, period_from, period_to, "
                "compared, agreed, "
                "unsafe_approvals, threshold_bp, passed, report, created_by, created_at) VALUES "
                "(:id, :o, :f, :t, "
                ":pf, :pt, :c, :a, :u, :th, :p, CAST(:r AS jsonb), :by, :now)"
            ),
            {
                "id": gid,
                "o": org_id,
                "f": mode,
                "t": to_mode,
                "pf": m["period_from"],
                "pt": m["period_to"],
                "c": m["compared"],
                "a": m["agreed"],
                "u": len(m["unsafe"]),
                "th": m["threshold_bp"],
                "p": m["passed"],
                "r": json.dumps({k: v for k, v in m.items() if k not in ("period_from", "period_to")}),
                "by": actor.id,
                "now": now,
            },
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="mode_gate.created",
            subject_id=gid,
            payload={
                "from": mode,
                "to": to_mode,
                "compared": m["compared"],
                "agreed": m["agreed"],
                "unsafe_approvals": len(m["unsafe"]),
                "threshold_bp": m["threshold_bp"],
                "passed": m["passed"],
            },
        )
    return gid


def sign_gate(engine: Engine, clock: Clock, *, org_id: str, gate_id: str, actor: Actor) -> None:
    with transaction(engine) as conn:
        g = conn.execute(
            text("SELECT * FROM mode_gates WHERE org_id=:o AND id=:g FOR UPDATE"), {"o": org_id, "g": gate_id}
        ).one_or_none()
        if g is None:
            raise GateError(f"no gate {gate_id}", status=404, code="not_found")
        if not g.passed:
            raise GateError("this gate did not pass, so it can't be signed")
        if actor.role == Role.PAYMENTS_LEAD.value:
            col, other = "payments_lead", g.compliance_lead_id
        elif actor.role == Role.COMPLIANCE_LEAD.value:
            col, other = "compliance_lead", g.payments_lead_id
        else:
            raise GateError("only the payments lead and the compliance lead sign a gate", status=403)
        if getattr(g, f"{col}_id") is not None:
            raise GateError(f"the {col.replace('_', ' ')} has already signed")
        if other == actor.id:
            raise GateError("the two sign-offs must be by two different people", status=403)
        sql = {
            "payments_lead": (
                "UPDATE mode_gates SET payments_lead_id=:a, payments_lead_at=:t WHERE org_id=:o AND id=:g"
            ),
            "compliance_lead": (
                "UPDATE mode_gates SET compliance_lead_id=:a, compliance_lead_at=:t WHERE org_id=:o AND id=:g"
            ),
        }[col]
        conn.execute(text(sql), {"a": actor.id, "t": clock.now(), "o": org_id, "g": gate_id})
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="mode_gate.signed",
            subject_id=gate_id,
            payload={"as": col},
        )


def check_gate_for_change(
    conn: Connection, org_id: str, *, from_mode: str, to_mode: str, gate_id: str | None
) -> str | None:
    """Called when a mode change is proposed. Returns the gate to link, or raises."""
    if not is_upward(from_mode, to_mode):
        return None
    production = conn.execute(
        text("SELECT production FROM organisations WHERE org_id=:o"), {"o": org_id}
    ).scalar_one()
    if gate_id is None:
        if production:
            raise GateError(
                "a production organisation moves up only on a signed mode gate (SHD-03)", status=422
            )
        return None
    g = conn.execute(
        text("SELECT * FROM mode_gates WHERE org_id=:o AND id=:g"), {"o": org_id, "g": gate_id}
    ).one_or_none()
    if g is None:
        raise GateError(f"no gate {gate_id}", status=404, code="not_found")
    if (g.from_mode, g.to_mode) != (from_mode, to_mode):
        raise GateError(f"gate {gate_id} is for {g.from_mode} to {g.to_mode}", status=422)
    if not (g.passed and g.payments_lead_id and g.compliance_lead_id):
        raise GateError(f"gate {gate_id} is not passed and signed by both leads", status=422)
    if g.mode_change_id is not None:
        raise GateError(f"gate {gate_id} was already used for a mode change")
    return str(g.id)


def link_gate(conn: Connection, org_id: str, gate_id: str, change_id: str) -> None:
    conn.execute(
        text("UPDATE mode_gates SET mode_change_id=:c WHERE org_id=:o AND id=:g AND mode_change_id IS NULL"),
        {"c": change_id, "o": org_id, "g": gate_id},
    )


def list_gates(conn: Connection, org_id: str) -> list[Any]:
    return list(
        conn.execute(
            text("SELECT * FROM mode_gates WHERE org_id=:o ORDER BY created_at DESC, id DESC LIMIT 20"),
            {"o": org_id},
        ).all()
    )
