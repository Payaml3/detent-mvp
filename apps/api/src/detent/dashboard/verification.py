"""DSH-12: the integration checklist, filled from sandbox evidence, and the request to verify it.

Each item is read from what the organisation's own sandbox recorded, never from what someone ticks: the test
values of spec/06 (on the simulated chain and in the policy), a signed webhook its endpoint acknowledged with
a 2xx, an idempotent retry of `POST /v1/payment_intents`, and an UNKNOWN payment resolved without a resend.
Evidence counts across data generations (SBX-04): a reset hides old payments from the screens, but what the
integration has shown it can handle stays shown.

The account owner (or an admin) requests verification once every item passes; a DekernAI admin verifies it or
returns it with a note. The checklist is stored with the request, so the admin decides on what the owner saw.
A decided request is final (a trigger refuses changes); after a return the owner opens a new one.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from detent.audit.log import append
from detent.clock import Clock
from detent.dashboard.access import AccessError, Member, _require, _require_staff, load_org
from detent.domain.ids import Prefix, new_id


@dataclass(frozen=True, slots=True)
class Item:
    key: str
    label: str
    how: str
    done: bool


def _decided(*reasons: str) -> Callable[[Connection, str], bool]:
    def check(conn: Connection, org_id: str) -> bool:
        return (
            conn.execute(
                text(
                    "SELECT 1 FROM decisions d, jsonb_array_elements(d.checks) c WHERE d.org_id=:o "
                    "AND c->>'reason' = ANY(:r) LIMIT 1"
                ),
                {"o": org_id, "r": list(reasons)},
            ).first()
            is not None
        )

    return check


def _sim(test_value: str, attempt_status: str) -> Callable[[Connection, str], bool]:
    def check(conn: Connection, org_id: str) -> bool:
        return (
            conn.execute(
                text(
                    "SELECT 1 FROM simchain_transfers s JOIN attempts a ON a.org_id = s.org_id "
                    "AND a.id = s.attempt_id WHERE s.org_id=:o AND s.test_value=:tv AND a.status=:st LIMIT 1"
                ),
                {"o": org_id, "tv": test_value, "st": attempt_status},
            ).first()
            is not None
        )

    return check


def _webhook_acknowledged(conn: Connection, org_id: str) -> bool:
    return (
        conn.execute(
            text(
                "SELECT 1 FROM webhook_deliveries d JOIN webhook_events e ON e.org_id = d.org_id "
                "AND e.id = d.event_id WHERE d.org_id=:o AND NOT e.test "
                "AND d.status_code BETWEEN 200 AND 299 LIMIT 1"
            ),
            {"o": org_id},
        ).first()
        is not None
    )


def _idempotent_retry(conn: Connection, org_id: str) -> bool:
    return (
        conn.execute(
            text(
                "SELECT 1 FROM request_logs WHERE org_id=:o AND method='POST' AND path='/v1/payment_intents' "
                "AND idempotency_key IS NOT NULL AND status BETWEEN 200 AND 299 "
                "GROUP BY idempotency_key HAVING count(*) >= 2 LIMIT 1"
            ),
            {"o": org_id},
        ).first()
        is not None
    )


def _unknown_resolved_once(conn: Connection, org_id: str) -> bool:
    """A payment that was UNKNOWN, is now CONFIRMED and has only ever had one attempt: nothing was resent."""
    return (
        conn.execute(
            text(
                "SELECT 1 FROM payment_intents p WHERE p.org_id=:o AND p.status='CONFIRMED' "
                "AND (SELECT count(*) FROM attempts a WHERE a.org_id = p.org_id AND a.payment_id = p.id) = 1 "
                "AND EXISTS (SELECT 1 FROM audit_events e WHERE e.org_id = p.org_id AND e.subject_id = p.id "
                "AND e.kind = 'payment.status_changed' AND e.payload->>'to' = 'UNKNOWN') LIMIT 1"
            ),
            {"o": org_id},
        ).first()
        is not None
    )


_ITEMS: tuple[tuple[str, str, str, Callable[[Connection, str], bool]], ...] = (
    ("timeout", "Test value .13: a timeout became UNKNOWN, then CONFIRMED",
     "Send a payout of an amount ending in .13 on the simulated chain.",
     _sim("timeout_after_forward", "CONFIRMED")),
    ("revert", "Test value .42: a reverted transaction failed on its first rail",
     "Send a payout of an amount ending in .42 on the simulated chain.",
     _sim("receipt_status_0", "FAILED")),
    ("screening", "Flagged address: the screening hit blocked the payout",
     "Pay the fixture payee whose wallet is on the screening list (cpt_flagged).",
     _decided("SCREENING_HIT")),
    ("allowlist", "Payee off the allowlist: the payout was escalated",
     "Pay a payee that is not on the allowlist, or a first payment to a new payee.",
     _decided("NOT_ALLOWLISTED", "FIRST_PAYMENT")),
    ("mandate", "Mandate limit: an agent payout over the per-payment limit was blocked",
     "Submit an agent payout above its mandate's per-payment limit.",
     _decided("MANDATE_AMOUNT_EXCEEDED")),
    ("webhook", "A signed webhook was received and acknowledged",
     "Answer a real (not test) event with a 2xx from your endpoint after checking its signature.",
     _webhook_acknowledged),
    ("idempotency", "An idempotent retry was used",
     "Send the same POST /v1/payment_intents twice with the same Idempotency-Key.",
     _idempotent_retry),
    ("unknown", "An UNKNOWN payout was resolved without a resend",
     "Follow a .13 payout until it is CONFIRMED; it must keep a single attempt.",
     _unknown_resolved_once),
)  # fmt: skip


def checklist(conn: Connection, org_id: str) -> list[Item]:
    return [Item(key, label, how, check(conn, org_id)) for key, label, how, check in _ITEMS]


def _snapshot(items: list[Item]) -> list[dict[str, Any]]:
    return [{"key": i.key, "label": i.label, "done": i.done} for i in items]


def latest(conn: Connection, org_id: str) -> Any:
    return conn.execute(
        text(
            "SELECT id, requested_by, requested_at, checklist, status, decided_by, decided_at, note "
            "FROM verification_requests WHERE org_id=:o "
            # The open request, else the verified one, else the newest returned one. At most one is open and
            # nothing follows a verification, so this is the latest even when IDs share an instant (a frozen
            # clock), where they don't sort by time.
            "ORDER BY CASE status WHEN 'requested' THEN 0 WHEN 'verified' THEN 1 ELSE 2 END, "
            "requested_at DESC, id DESC LIMIT 1"
        ),
        {"o": org_id},
    ).one_or_none()


def request_verification(conn: Connection, clock: Clock, *, by: Member) -> str:
    _require(by, "verification.request")
    load_org(conn, by.org_id, lock=True)  # one request at a time per organisation
    last = latest(conn, by.org_id)
    if last is not None and last.status == "requested":
        raise AccessError("already_requested", "Verification is already requested.", status=409)
    if last is not None and last.status == "verified":
        raise AccessError("already_verified", "The integration is already verified.", status=409)
    items = checklist(conn, by.org_id)
    open_items = [i.label for i in items if not i.done]
    if open_items:
        raise AccessError(
            "checklist_incomplete",
            f"{len(open_items)} checklist item(s) have no sandbox evidence yet.",
            status=409,
        )
    now = clock.now()
    rid = new_id(Prefix.VER, now)
    conn.execute(
        text(
            "INSERT INTO verification_requests (id, org_id, requested_by, requested_at, checklist) "
            "VALUES (:id, :o, :b, :now, CAST(:c AS jsonb))"
        ),
        {"id": rid, "o": by.org_id, "b": by.id, "now": now, "c": json.dumps(_snapshot(items))},
    )
    append(
        conn,
        clock,
        org_id=by.org_id,
        actor=by.actor,
        kind="verification.requested",
        subject_id=rid,
        payload={"checklist": [i.key for i in items]},
    )
    return rid


def decide(
    conn: Connection, clock: Clock, *, staff: Member, org_id: str, request_id: str, outcome: str, note: str
) -> None:
    """A DekernAI admin verifies the integration, or returns the request with a note. Audited in the
    organisation's own log."""
    _require_staff(staff)
    if outcome not in ("verified", "returned"):
        raise AccessError("validation_error", "Verify the integration or return it.")
    note = note.strip()[:1000]
    if outcome == "returned" and len(note) < 3:
        raise AccessError("validation_error", "Say what is missing when you return a request.")
    row = conn.execute(
        text("SELECT status FROM verification_requests WHERE org_id=:o AND id=:i FOR UPDATE"),
        {"o": org_id, "i": request_id},
    ).scalar_one_or_none()
    if row is None:
        raise AccessError("not_found", "No such verification request.", status=404)
    if row != "requested":
        raise AccessError("already_decided", "This request is already decided.", status=409)
    conn.execute(
        text(
            "UPDATE verification_requests SET status=:s, decided_by=:b, decided_at=:now, note=:n "
            "WHERE org_id=:o AND id=:i"
        ),
        {"s": outcome, "b": staff.id, "now": clock.now(), "n": note or None, "o": org_id, "i": request_id},
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=staff.actor,
        kind=f"verification.{outcome}",
        subject_id=request_id,
        payload={"note": note},
    )


def open_requests(conn: Connection) -> list[Any]:
    """Every organisation's requests waiting for a DekernAI admin, oldest first (admin screen)."""
    return list(
        conn.execute(
            text(
                "SELECT v.id, v.org_id, o.name, v.requested_by, v.requested_at, v.checklist "
                "FROM verification_requests v JOIN organisations o ON o.id = v.org_id "
                "WHERE v.status = 'requested' ORDER BY v.requested_at, v.id"
            ).execution_options(cross_org="DSH-12: the DekernAI admin's queue of verification requests"),
        ).all()
    )
