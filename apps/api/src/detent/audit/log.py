"""Append-only, hash-chained audit log (invariant 12).

``append`` must be called inside the same transaction as the change it describes. It locks the
organisation's chain head, so appends serialise per organisation and ``seq`` has no gaps.

Hash: ``sha256(canonical_json({org_id, seq, at, actor, actor_role, kind, subject_id, payload,
prev_hash}))``. Payloads hold JSON-native values only; floats are rejected (invariant 15).
AUD-01 (M1) builds the console view and the ``detent audit verify`` command on ``verify_chain``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, insert, select, text, update

from detent.clock import Clock
from detent.db.tables import audit_events, audit_heads
from detent.domain.ids import Prefix, new_id

GENESIS_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class Actor:
    """Who did something: a user ID with a role, or a system component such as ``system:worker``."""

    id: str
    role: str | None = None

    @classmethod
    def system(cls, component: str) -> Actor:
        return cls(id=f"system:{component}", role=None)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    org_id: str
    seq: int
    at: datetime
    actor: str
    actor_role: str | None
    kind: str
    subject_id: str | None
    payload: dict[str, Any]
    prev_hash: str
    hash: str


def _check_json(value: Any, path: str = "payload") -> None:
    if isinstance(value, float):
        raise TypeError(f"{path}: floats are not allowed in audit payloads; use strings or minor units")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError(f"{path}: keys must be strings")
            _check_json(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _check_json(v, f"{path}[{i}]")
    elif value is not None and not isinstance(value, str | int | bool):
        raise TypeError(f"{path}: {type(value).__name__} is not JSON-native")


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="microseconds")


def compute_hash(
    *,
    org_id: str,
    seq: int,
    at: datetime,
    actor: str,
    actor_role: str | None,
    kind: str,
    subject_id: str | None,
    payload: dict[str, Any],
    prev_hash: str,
) -> str:
    body = {
        "org_id": org_id,
        "seq": seq,
        "at": _iso(at),
        "actor": actor,
        "actor_role": actor_role,
        "kind": kind,
        "subject_id": subject_id,
        "payload": payload,
        "prev_hash": prev_hash,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def append(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    actor: Actor,
    kind: str,
    subject_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    payload = payload or {}
    _check_json(payload)
    conn.execute(
        text(
            "INSERT INTO audit_heads (org_id, seq, hash) VALUES (:org_id, 0, :genesis) "
            "ON CONFLICT (org_id) DO NOTHING"
        ),
        {"org_id": org_id, "genesis": GENESIS_HASH},
    )
    head = conn.execute(
        select(audit_heads.c.seq, audit_heads.c.hash).where(audit_heads.c.org_id == org_id).with_for_update()
    ).one()
    seq = int(head.seq) + 1
    at = clock.now()
    h = compute_hash(
        org_id=org_id,
        seq=seq,
        at=at,
        actor=actor.id,
        actor_role=actor.role,
        kind=kind,
        subject_id=subject_id,
        payload=payload,
        prev_hash=head.hash,
    )
    event_id = new_id(Prefix.EVT, at)
    conn.execute(
        insert(audit_events).values(
            id=event_id,
            org_id=org_id,
            seq=seq,
            at=at,
            actor=actor.id,
            actor_role=actor.role,
            kind=kind,
            subject_id=subject_id,
            payload=payload,
            prev_hash=head.hash,
            hash=h,
        )
    )
    conn.execute(update(audit_heads).where(audit_heads.c.org_id == org_id).values(seq=seq, hash=h))
    # WHK-01: the webhook events this change produces, in the same transaction and under the same
    # organisation lock, so an event exists exactly when its change committed.
    from detent.webhooks.events import from_audit  # deferred: the webhooks read domain views

    from_audit(conn, clock, org_id=org_id, kind=kind, subject_id=subject_id, payload=payload)
    return AuditEvent(
        event_id, org_id, seq, at, actor.id, actor.role, kind, subject_id, payload, head.hash, h
    )


@dataclass(frozen=True, slots=True)
class ChainStatus:
    ok: bool
    events: int
    first_bad_seq: int | None = None
    problem: str | None = None


def verify_chain(conn: Connection, org_id: str) -> ChainStatus:
    rows = conn.execute(
        select(audit_events).where(audit_events.c.org_id == org_id).order_by(audit_events.c.seq)
    ).all()
    prev = GENESIS_HASH
    for i, r in enumerate(rows, start=1):
        if r.seq != i:
            return ChainStatus(False, len(rows), r.seq, f"gap: expected seq {i}")
        if r.prev_hash != prev:
            return ChainStatus(False, len(rows), r.seq, "prev_hash does not match the previous event")
        expected = compute_hash(
            org_id=r.org_id,
            seq=r.seq,
            at=r.at,
            actor=r.actor,
            actor_role=r.actor_role,
            kind=r.kind,
            subject_id=r.subject_id,
            payload=r.payload,
            prev_hash=r.prev_hash,
        )
        if expected != r.hash:
            return ChainStatus(False, len(rows), r.seq, "hash does not match the event contents")
        prev = r.hash
    head = conn.execute(select(audit_heads).where(audit_heads.c.org_id == org_id)).one_or_none()
    if rows and (head is None or head.seq != len(rows) or head.hash != prev):
        return ChainStatus(False, len(rows), None, "chain head does not match the last event")
    return ChainStatus(True, len(rows))
