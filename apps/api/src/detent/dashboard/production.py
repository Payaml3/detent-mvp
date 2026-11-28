"""Enable production mode (DSH-13).

The switch is offered only when the integration is verified (DSH-12) and the active rule version was
attested by the client's compliance lead when it was activated (POL-07: the sign-off of rule set v1).
Production starts in Shadow mode (founder, 2026-11-26); moves to Assist and Auto follow the mode gates
(SHD-03). In the prototype the switch is shown as not available: the account owner's request is recorded
and audited, nothing about the organisation changes, and no ``sk_live_`` key is ever issued (invariant 14).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, text

from detent.audit.log import append
from detent.clock import Clock
from detent.dashboard import verification
from detent.dashboard.access import AccessError, Member, _require
from detent.domain.ids import Prefix, new_id


def readiness(conn: Connection, org_id: str) -> dict[str, Any]:
    last = verification.latest(conn, org_id)
    pol = conn.execute(
        text("SELECT version, attested_by FROM policy_versions WHERE org_id=:o AND status='active'"),
        {"o": org_id},
    ).one_or_none()
    request = conn.execute(
        text("SELECT * FROM production_requests WHERE org_id=:o"), {"o": org_id}
    ).one_or_none()
    verified = last is not None and last.status == "verified"
    signed = pol is not None and pol.attested_by is not None
    return {
        "verified": verified,
        "verification_id": last.id if verified else None,
        "rules_signed": signed,
        "policy_version": pol.version if pol else None,
        "ready": verified and signed,
        "request": request,
    }


def request_production(conn: Connection, clock: Clock, *, by: Member) -> str:
    _require(by, "production.request")
    r = readiness(conn, by.org_id)
    if r["request"] is not None:
        raise AccessError("already_requested", "Production mode was already requested.", status=409)
    if not r["ready"]:
        raise AccessError(
            "not_ready",
            "Production needs a verified integration and a rule set signed off by your compliance lead.",
            status=409,
        )
    now = clock.now()
    rid = new_id(Prefix.PRQ, now)
    conn.execute(
        text(
            "INSERT INTO production_requests (id, org_id, requested_by, requested_at, policy_version, "
            "verification_id) VALUES (:id, :o, :by, :t, :pv, :v)"
        ),
        {
            "id": rid,
            "o": by.org_id,
            "by": by.id,
            "t": now,
            "pv": r["policy_version"],
            "v": r["verification_id"],
        },
    )
    append(
        conn,
        clock,
        org_id=by.org_id,
        actor=by.actor,
        kind="production.requested",
        subject_id=rid,
        payload={
            "policy_version": r["policy_version"],
            "verification_id": r["verification_id"],
            "starts_in": "shadow",
            "available_in_prototype": False,
        },
    )
    return rid
