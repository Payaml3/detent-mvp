"""End users of the platform and their one payout destination (USR-01, G-10, spec/04 User payouts).

The platform registers each end-user account by its own reference (``user_account_ref``) with:
- one payout destination. Registering a different one replaces it in place (same ``dst_`` ID), records
  ``destination.changed`` with the old and new details, and so the next payout escalates CHANGED_DETAILS;
- a typed ``user_verified`` flag, the result of the platform's own KYC, stored with who set it and when.

A user payout may only go to the registered destination. Every change is audited in the same transaction.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.policy.facts import UserFacts

REF_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$"


class UserDestinationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["evm_wallet", "bank_account"]
    network: str = Field(min_length=1, max_length=64)
    address: str | None = Field(default=None, pattern=r"^0x[0-9a-fA-F]{40}$")
    account_masked: str | None = Field(default=None, min_length=4, max_length=64)

    @model_validator(mode="after")
    def _shape(self) -> UserDestinationIn:
        if self.kind == "evm_wallet" and (not self.address or self.account_masked):
            raise ValueError("an evm_wallet takes an address only")
        if self.kind == "bank_account" and (self.address or not self.account_masked):
            raise ValueError("a bank_account takes account_masked only")
        return self


class UserAccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_verified: StrictBool
    holder_name: str | None = Field(default=None, min_length=1, max_length=140)
    destination: UserDestinationIn


class UserAccountError(Exception):
    def __init__(self, message: str, *, status: int = 422, code: str = "validation_error") -> None:
        super().__init__(message)
        self.status, self.code = status, code


_USER_SQL = (
    "SELECT ref, holder_name, user_verified, verified_set_by, verified_set_at, created_at "
    "FROM user_accounts WHERE org_id=:o AND ref=:r"
)
_DEST_SQL = (
    "SELECT id, kind, network, address, account_masked, first_seen_at, last_changed_at, "
    "last_changed_by FROM destinations WHERE org_id=:o AND user_account_ref=:r"
)


def _row(conn: Connection, org_id: str, ref: str, *, lock: bool = False) -> Any:
    sql = _USER_SQL + " FOR UPDATE" if lock else _USER_SQL
    return conn.execute(text(sql), {"o": org_id, "r": ref}).one_or_none()


def destination_row(conn: Connection, org_id: str, ref: str, *, lock: bool = False) -> Any:
    sql = _DEST_SQL + " FOR UPDATE" if lock else _DEST_SQL
    return conn.execute(text(sql), {"o": org_id, "r": ref}).one_or_none()


def user_facts(conn: Connection, org_id: str, ref: str) -> UserFacts | None:
    r = _row(conn, org_id, ref)
    if r is None:
        return None
    return UserFacts(r.ref, bool(r.user_verified), r.verified_set_by, r.verified_set_at)


def holder_name(conn: Connection, org_id: str, ref: str) -> str | None:
    r = _row(conn, org_id, ref)
    return None if r is None else r.holder_name


def view(conn: Connection, org_id: str, ref: str) -> dict[str, Any] | None:
    r = _row(conn, org_id, ref)
    if r is None:
        return None
    d = destination_row(conn, org_id, ref)
    return {
        "object": "user_account",
        "user_account_ref": r.ref,
        "holder_name": r.holder_name,
        "user_verified": bool(r.user_verified),
        "verified_set_by": r.verified_set_by,
        "verified_set_at": r.verified_set_at.isoformat(),
        "created_at": r.created_at.isoformat(),
        "destination": None
        if d is None
        else {
            "id": d.id,
            "kind": d.kind,
            "network": d.network,
            "address": d.address,
            "account_masked": d.account_masked,
            "first_seen_at": d.first_seen_at.isoformat(),
            "last_changed_at": d.last_changed_at.isoformat(),
        },
    }


def _details(d: Any) -> dict[str, Any]:
    return {"kind": d.kind, "network": d.network, "address": d.address, "account_masked": d.account_masked}


def register(
    conn: Connection, clock: Clock, *, org_id: str, ref: str, body: UserAccountIn, actor: Actor
) -> dict[str, Any]:
    """Create or update a user account and its one destination, in the caller's transaction."""
    now = clock.now()
    existing = _row(conn, org_id, ref, lock=True)
    if existing is None:
        conn.execute(
            text(
                "INSERT INTO user_accounts (org_id, ref, holder_name, user_verified, verified_set_by, "
                "verified_set_at, created_at) VALUES (:o, :r, :n, :v, :by, :t, :t)"
            ),
            {"o": org_id, "r": ref, "n": body.holder_name, "v": body.user_verified, "by": actor.id, "t": now},
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="user_account.registered",
            subject_id=ref,
            payload={"user_verified": body.user_verified, "holder_name_set": body.holder_name is not None},
        )
    else:
        if bool(existing.user_verified) != body.user_verified:
            conn.execute(
                text(
                    "UPDATE user_accounts SET user_verified=:v, verified_set_by=:by, verified_set_at=:t "
                    "WHERE org_id=:o AND ref=:r"
                ),
                {"v": body.user_verified, "by": actor.id, "t": now, "o": org_id, "r": ref},
            )
            append(
                conn,
                clock,
                org_id=org_id,
                actor=actor,
                kind="user_account.verification_changed",
                subject_id=ref,
                payload={"from": bool(existing.user_verified), "to": body.user_verified},
            )
        if body.holder_name is not None and body.holder_name != existing.holder_name:
            conn.execute(
                text("UPDATE user_accounts SET holder_name=:n WHERE org_id=:o AND ref=:r"),
                {"n": body.holder_name, "o": org_id, "r": ref},
            )
            append(
                conn,
                clock,
                org_id=org_id,
                actor=actor,
                kind="user_account.holder_name_changed",
                subject_id=ref,
                payload={},
            )
    new = body.destination
    d = destination_row(conn, org_id, ref, lock=True)
    if d is None:
        dst = new_id(Prefix.DST, now)
        conn.execute(
            text(
                "INSERT INTO destinations (id, org_id, user_account_ref, kind, network, address, "
                "account_masked, verified, first_seen_at, last_changed_at, last_changed_by) "
                "VALUES (:id, :o, :r, :k, :n, :a, :m, true, :t, :t, :by)"
            ),
            {
                "id": dst, "o": org_id, "r": ref, "k": new.kind, "n": new.network, "a": new.address,
                "m": new.account_masked, "t": now, "by": actor.id,
            },
        )  # fmt: skip
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="destination.registered",
            subject_id=dst,
            payload={"user_account_ref": ref, **new.model_dump()},
        )
    elif _details(d) != new.model_dump():
        # G-10: one destination per user. A different one replaces it; the change is the fact that makes
        # the next payout escalate CHANGED_DETAILS.
        conn.execute(
            text(
                "UPDATE destinations SET kind=:k, network=:n, address=:a, account_masked=:m, "
                "last_changed_at=:t, last_changed_by=:by WHERE org_id=:o AND id=:d"
            ),
            {
                "k": new.kind, "n": new.network, "a": new.address, "m": new.account_masked, "t": now,
                "by": actor.id, "o": org_id, "d": d.id,
            },
        )  # fmt: skip
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="destination.changed",
            subject_id=d.id,
            payload={"user_account_ref": ref, "old": _details(d), "new": new.model_dump()},
        )
    out = view(conn, org_id, ref)
    assert out is not None
    return out


def register_user(
    engine: Engine, clock: Clock, *, org_id: str, ref: str, body: UserAccountIn, actor: Actor
) -> dict[str, Any]:
    with transaction(engine) as conn:
        return register(conn, clock, org_id=org_id, ref=ref, body=body, actor=actor)
