"""KYB-gated organisations, invites, sign-up and team roles (DSH-01, DSH-02, DSH-03, DSH-11; spec/08).

- There is no public sign-up. A DekernAI admin (a member of the operator organisation with the admin role)
  creates a client organisation after KYB, or an evaluation organisation with an expiry, and invites its
  account owner. Every later member is invited by an account owner or admin.
- An invite is single-use and expires after `INVITE_DAYS` (7). Following its link proves the address
  (email verification); the person then sets a password (argon2id) and lands in the dashboard.
- An organisation that has an account owner always keeps one: a database trigger refuses the change, and
  team changes lock the organisation row first, so two owners can't demote each other at once.
- Expired and suspended organisations are locked: the API answers 403 and the dashboard is read-only.

Every change writes an audit event in the organisation it concerns (invariant 12).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.dashboard.email import send_email
from detent.dashboard.passwords import check_new_password, hash_password, verify_password
from detent.domain.ids import Prefix, new_id
from detent.domain.roles import MEMBER_ROLES, Role, allowed
from detent.settings import Settings

OPERATOR_ORG = "org_detent"  # DekernAI's own organisation; its admins are the DekernAI admins
STAFF_ROLE = Role.ADMIN
OrgKind = Literal["client", "evaluation"]
OrgStatus = Literal["active", "expired", "suspended"]
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,63}$")
_LOGIN = {"cross_org": "dashboard login: the email names the organisation"}
_TOKEN = {"cross_org": "invite link: the token names the organisation"}


class AccessError(ValueError):
    """A refused request, with a message fit to show the person."""

    def __init__(self, code: str, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.status = code, status


@dataclass(frozen=True, slots=True)
class Member:
    id: str
    org_id: str
    email: str
    display_name: str
    role: Role

    @property
    def actor(self) -> Actor:
        return Actor(self.id, self.role.value)

    @property
    def is_staff(self) -> bool:
        return self.org_id == OPERATOR_ORG and self.role == STAFF_ROLE


@dataclass(frozen=True, slots=True)
class InviteView:
    id: str
    org_id: str
    org_name: str
    email: str
    role: Role
    state: Literal["open", "expired", "used", "revoked"]


def normalise_email(email: str) -> str:
    e = email.strip()
    if not _EMAIL.match(e):
        raise AccessError("invalid_email", "Enter a valid email address.")
    return e


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invite_link(settings: Settings, token: str) -> str:
    return f"{settings.dashboard_url.rstrip('/')}/dashboard/invite/{token}"


# ------------------------------------------------------------------------------------------ status
def org_status(row: Any, now: datetime) -> OrgStatus:
    if row.suspended_at is not None:
        return "suspended"
    if row.expires_at is not None and row.expires_at <= now:
        return "expired"
    return "active"


def load_org(conn: Connection, org_id: str, *, lock: bool = False) -> Any:
    row = conn.execute(
        text(
            "SELECT id, name, kind, kyb_reference, kyb_approved_on, expires_at, suspended_at, "  # noqa: S608
            "suspended_reason, created_at, created_by FROM organisations WHERE org_id=:o"
            + (" FOR UPDATE" if lock else "")
        ),
        {"o": org_id},
    ).one_or_none()
    if row is None:
        raise AccessError("not_found", "No such organisation.", status=404)
    return row


# ------------------------------------------------------------------------------------------ organisations
def create_organisation(
    conn: Connection,
    clock: Clock,
    settings: Settings,
    *,
    staff: Member,
    kind: OrgKind,
    name: str,
    owner_email: str,
    kyb_reference: str | None = None,
    kyb_approved_on: date | None = None,
    expires_in_days: int | None = None,
) -> tuple[str, str]:
    """DSH-01. Returns the new organisation's ID and the owner's invite token (shown to the admin once)."""
    _require_staff(staff)
    name = name.strip()
    if not 2 <= len(name) <= 120:
        raise AccessError("validation_error", "The organisation name needs 2 to 120 characters.")
    owner_email = normalise_email(owner_email)
    now = clock.now()
    expires_at: datetime | None = None
    if kind == "client":
        kyb_reference = (kyb_reference or "").strip()
        if not kyb_reference or kyb_approved_on is None:
            raise AccessError(
                "kyb_required", "A client organisation needs the KYB approval reference and date."
            )
        if len(kyb_reference) > 100:
            raise AccessError("validation_error", "The KYB reference is longer than 100 characters.")
        if kyb_approved_on > now.date():
            raise AccessError("validation_error", "The KYB approval date can't be in the future.")
    elif kind == "evaluation":
        kyb_reference, kyb_approved_on = None, None
        days = settings.evaluation_days if expires_in_days is None else expires_in_days
        if not 1 <= days <= 365:
            raise AccessError("validation_error", "An evaluation lasts 1 to 365 days.")
        expires_at = now + timedelta(days=days)
    else:
        raise AccessError("validation_error", "The kind is client or evaluation.")
    org_id = new_id(Prefix.ORG, now)
    conn.execute(
        text(
            "INSERT INTO organisations (id, name, mode, fail_safe, kind, kyb_reference, kyb_approved_on, "
            "expires_at, created_by, created_at, daily_payment_quota, daily_investigation_quota) "
            "VALUES (:id, :n, 'shadow', 'manual_queue', :k, :ref, :on, :exp, :by, :now, :qp, :qi)"
        ),
        {
            "id": org_id,
            "n": name,
            "k": kind,
            "ref": kyb_reference,
            "on": kyb_approved_on,
            "exp": expires_at,
            "by": staff.id,
            "now": now,
            "qp": settings.sandbox_daily_payments,  # SBX-02
            "qi": settings.sandbox_daily_investigations,
        },
    )
    conn.execute(text("INSERT INTO kill_switch (org_id, engaged) VALUES (:o, false)"), {"o": org_id})
    conn.execute(text("INSERT INTO demo_clock (org_id, offset_seconds) VALUES (:o, 0)"), {"o": org_id})
    seeded = seed_sandbox_data(conn, clock, settings, org_id)
    append(
        conn,
        clock,
        org_id=org_id,
        actor=staff.actor,
        kind="organisation.created",
        subject_id=org_id,
        payload={
            "kind": kind,
            "name": name,
            "kyb_reference": kyb_reference,
            "kyb_approved_on": kyb_approved_on.isoformat() if kyb_approved_on else None,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "created_by_org": staff.org_id,
            "seeded": seeded,
        },
    )
    token = invite(conn, clock, settings, org_id=org_id, email=owner_email, role=Role.ACCOUNT_OWNER, by=staff)
    return org_id, token


def seed_sandbox_data(conn: Connection, clock: Clock, settings: Settings, org_id: str) -> dict[str, int]:
    """G-18: a new organisation starts with the fictional counterparties, the simulated rails and the default
    rule set (version 1), so every test value works from the first call."""
    from detent.intents.registry import seed_registry
    from detent.policy.schema import load_ruleset
    from detent.policy.store import install_ruleset
    from detent.rails.registry import seed_rails
    from detent.seed import POLICY

    counterparties = seed_registry(conn, clock, org_id)
    rails = seed_rails(conn, org_id, settings)
    install_ruleset(conn, clock, org_id, load_ruleset(POLICY.read_text()), proposed_by="system:seed")
    return {"counterparties": len(counterparties), "rails": len(rails), "policy_versions": 1}


def extend(conn: Connection, clock: Clock, *, staff: Member, org_id: str, days: int) -> datetime:
    """DSH-03: an admin extends an evaluation, counting from today or from the current expiry if later."""
    _require_staff(staff)
    if not 1 <= days <= 365:
        raise AccessError("validation_error", "Extend by 1 to 365 days.")
    org = load_org(conn, org_id, lock=True)
    if org.kind != "evaluation":
        raise AccessError("not_an_evaluation", "Only an evaluation organisation has an expiry.", status=409)
    now = clock.now()
    new_expiry: datetime = max(now, org.expires_at) + timedelta(days=days)
    conn.execute(
        text("UPDATE organisations SET expires_at=:e WHERE org_id=:o"), {"e": new_expiry, "o": org_id}
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=staff.actor,
        kind="organisation.extended",
        subject_id=org_id,
        payload={"from": org.expires_at.isoformat(), "to": new_expiry.isoformat(), "days": days},
    )
    return new_expiry


def suspend(conn: Connection, clock: Clock, *, staff: Member, org_id: str, reason: str) -> None:
    """DSH-03: suspend a client (or evaluation) organisation; the reason is audited."""
    _require_staff(staff)
    reason = reason.strip()
    if not 3 <= len(reason) <= 500:
        raise AccessError("validation_error", "Give a reason of 3 to 500 characters.")
    if org_id == OPERATOR_ORG:
        raise AccessError("validation_error", "The operator organisation can't be suspended.", status=409)
    org = load_org(conn, org_id, lock=True)
    if org.suspended_at is not None:
        raise AccessError("already_suspended", "The organisation is already suspended.", status=409)
    conn.execute(
        text("UPDATE organisations SET suspended_at=:now, suspended_reason=:r WHERE org_id=:o"),
        {"now": clock.now(), "r": reason, "o": org_id},
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=staff.actor,
        kind="organisation.suspended",
        subject_id=org_id,
        payload={"reason": reason},
    )


def unsuspend(conn: Connection, clock: Clock, *, staff: Member, org_id: str, reason: str) -> None:
    _require_staff(staff)
    reason = reason.strip()
    if not 3 <= len(reason) <= 500:
        raise AccessError("validation_error", "Give a reason of 3 to 500 characters.")
    org = load_org(conn, org_id, lock=True)
    if org.suspended_at is None:
        raise AccessError("not_suspended", "The organisation is not suspended.", status=409)
    conn.execute(
        text("UPDATE organisations SET suspended_at=NULL, suspended_reason=NULL WHERE org_id=:o"),
        {"o": org_id},
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=staff.actor,
        kind="organisation.unsuspended",
        subject_id=org_id,
        payload={"reason": reason, "suspended_reason": org.suspended_reason},
    )


def list_organisations(conn: Connection) -> list[Any]:
    return list(
        conn.execute(
            text(
                "SELECT o.id, o.name, o.kind, o.kyb_reference, o.kyb_approved_on, o.expires_at, "
                "o.suspended_at, "
                "o.created_at, (SELECT count(*) FROM users u WHERE u.org_id = o.org_id AND "
                "u.removed_at IS NULL "
                "AND u.password_hash IS NOT NULL) AS members FROM organisations o "
                "WHERE o.kind IN ('client', 'evaluation') ORDER BY o.created_at DESC, o.id"
            ).execution_options(cross_org="DekernAI admin: the list of client and evaluation organisations")
        ).all()
    )


# ------------------------------------------------------------------------------------------ invites
def invite(
    conn: Connection, clock: Clock, settings: Settings, *, org_id: str, email: str, role: Role, by: Member
) -> str:
    """DSH-01, DSH-11. Returns the token (the email carries the link). A new invite to the same address
    replaces the open one."""
    if role not in MEMBER_ROLES:
        raise AccessError("invalid_role", "Choose one of the listed roles.")
    if not by.is_staff:
        _require_member_of(by, org_id)
        _require(by, "team.manage")
        if role == Role.ACCOUNT_OWNER:
            _require(by, "team.grant_account_owner")
    email = normalise_email(email)
    org = load_org(conn, org_id, lock=True)
    _require_unlocked(org, clock.now())
    taken = conn.execute(
        text(
            "SELECT org_id FROM users WHERE lower(email)=lower(:e) AND password_hash IS NOT NULL "
            "AND removed_at IS NULL"
        ).execution_options(**_LOGIN),
        {"e": email},
    ).scalar_one_or_none()
    if taken == org_id:
        raise AccessError("already_a_member", "That person is already a member.", status=409)
    if taken is not None:
        raise AccessError(
            "email_in_use",
            "That address already signs in to another organisation; use another one.",
            status=409,
        )
    now = clock.now()
    replaced = conn.execute(
        text(
            "UPDATE invites SET revoked_at=:now WHERE org_id=:o AND lower(email)=lower(:e) AND "
            "used_at IS NULL "
            "AND revoked_at IS NULL RETURNING id"
        ),
        {"now": now, "o": org_id, "e": email},
    ).scalar_one_or_none()
    token = secrets.token_urlsafe(32)
    iid = new_id(Prefix.INV, now)
    expires = now + timedelta(days=settings.invite_days)
    conn.execute(
        text(
            "INSERT INTO invites (id, org_id, email, role, token_hash, invited_by, expires_at, created_at) "
            "VALUES (:id, :o, :e, :r, :h, :by, :exp, :now)"
        ),
        {
            "id": iid,
            "o": org_id,
            "e": email,
            "r": role.value,
            "h": _token_hash(token),
            "by": by.id,
            "exp": expires,
            "now": now,
        },
    )
    link = invite_link(settings, token)
    body = (
        f"You're invited to join {org.name} as {role.value.replace('_', ' ')} in the {settings.brand_name} "
        f"agentic payment controls sandbox (prototype, test networks only).\n\n"
        f"Open this link within {settings.invite_days} days to confirm your email and set a "
        f"password:\n{link}\n\n"
        "The link works once. If you didn't expect this, ignore it."
    )
    send_email(
        conn,
        clock,
        org_id=org_id,
        to=email,
        template="invite.account_owner" if role == Role.ACCOUNT_OWNER else "invite.member",
        body=body,
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=by.actor,
        kind="invite.sent",
        subject_id=iid,
        payload={
            "email": email,
            "role": role.value,
            "expires_at": expires.isoformat(),
            "replaced": replaced,
            "by_org": by.org_id,
        },
    )
    return token


def find_invite(conn: Connection, clock: Clock, token: str) -> InviteView | None:
    row = conn.execute(
        text(
            "SELECT i.id, i.org_id, o.name AS org_name, i.email, i.role, i.expires_at, i.used_at, "
            "i.revoked_at "
            "FROM invites i JOIN organisations o ON o.id = i.org_id WHERE i.token_hash=:h"
        ).execution_options(**_TOKEN),
        {"h": _token_hash(token)},
    ).one_or_none()
    if row is None:
        return None
    return InviteView(
        row.id, row.org_id, row.org_name, row.email, Role(row.role), _invite_state(row, clock.now())
    )


def _invite_state(row: Any, now: datetime) -> Literal["open", "expired", "used", "revoked"]:
    if row.used_at is not None:
        return "used"
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at <= now:
        return "expired"
    return "open"


def accept_invite(conn: Connection, clock: Clock, *, token: str, display_name: str, password: str) -> Member:
    """DSH-02. Following the link verified the address; this sets the password and creates the member."""
    found = find_invite(conn, clock, token)
    if found is None:
        raise AccessError("invite_invalid", "This invite link is not valid.", status=404)
    row = conn.execute(
        text(
            "SELECT id, org_id, email, role, expires_at, used_at, revoked_at FROM invites "
            "WHERE org_id=:o AND id=:i FOR UPDATE"
        ),
        {"o": found.org_id, "i": found.id},
    ).one()
    now = clock.now()
    state = _invite_state(row, now)
    if state != "open":
        raise AccessError(f"invite_{state}", _INVITE_MESSAGES[state], status=410)
    org = load_org(conn, row.org_id, lock=True)
    _require_unlocked(org, now)
    display_name = display_name.strip()
    if not 1 <= len(display_name) <= 80:
        raise AccessError("validation_error", "Enter your name (up to 80 characters).")
    try:
        check_new_password(password, email=row.email)
    except ValueError as exc:
        raise AccessError("weak_password", str(exc)) from exc
    role = Role(row.role)
    existing = conn.execute(
        text("SELECT id, removed_at, password_hash FROM users WHERE org_id=:o AND lower(email)=lower(:e)"),
        {"o": row.org_id, "e": row.email},
    ).one_or_none()
    pw_hash = hash_password(password)
    try:
        with conn.begin_nested():
            if existing is None:
                uid = new_id(Prefix.USR, now)
                conn.execute(
                    text(
                        "INSERT INTO users (id, org_id, email, display_name, role, password_hash, "
                        "email_verified_at, "
                        "password_changed_at, created_at) VALUES (:id, :o, :e, :n, :r, :h, :now, :now, :now)"
                    ),
                    {
                        "id": uid,
                        "o": row.org_id,
                        "e": row.email,
                        "n": display_name,
                        "r": role.value,
                        "h": pw_hash,
                        "now": now,
                    },
                )
            elif existing.removed_at is not None or existing.password_hash is None:
                uid = existing.id  # a removed member invited back, or a seeded user claiming a login
                conn.execute(
                    text(
                        "UPDATE users SET display_name=:n, role=:r, password_hash=:h, "
                        "email_verified_at=:now, "
                        "password_changed_at=:now, removed_at=NULL, removed_by=NULL WHERE org_id=:o "
                        "AND id=:id"
                    ),
                    {
                        "n": display_name,
                        "r": role.value,
                        "h": pw_hash,
                        "now": now,
                        "o": row.org_id,
                        "id": uid,
                    },
                )
            else:
                raise AccessError("already_a_member", "You're already a member; sign in instead.", status=409)
    except IntegrityError as exc:
        raise AccessError(
            "email_in_use", "That address already signs in to another organisation.", status=409
        ) from exc
    conn.execute(
        text("UPDATE invites SET used_at=:now, accepted_user_id=:u WHERE org_id=:o AND id=:i"),
        {"now": now, "u": uid, "o": row.org_id, "i": row.id},
    )
    member = Member(uid, row.org_id, row.email, display_name, role)
    append(
        conn,
        clock,
        org_id=row.org_id,
        actor=member.actor,
        kind="invite.accepted",
        subject_id=row.id,
        payload={"user_id": uid, "email": row.email, "role": role.value, "email_verified": True},
    )
    return member


_INVITE_MESSAGES = {
    "expired": "This invite has expired. Ask for a new one.",
    "used": "This invite has already been used. Sign in instead.",
    "revoked": "This invite was replaced or withdrawn. Use the newest email, or ask for a new invite.",
}


def revoke_invite(conn: Connection, clock: Clock, *, by: Member, org_id: str, invite_id: str) -> None:
    if not by.is_staff:
        _require_member_of(by, org_id)
        _require(by, "team.manage")
    load_org(conn, org_id, lock=True)
    done = conn.execute(
        text(
            "UPDATE invites SET revoked_at=:now WHERE org_id=:o AND id=:i AND used_at IS NULL AND "
            "revoked_at IS NULL "
            "RETURNING email, role"
        ),
        {"now": clock.now(), "o": org_id, "i": invite_id},
    ).one_or_none()
    if done is None:
        raise AccessError("not_found", "No open invite with that ID.", status=404)
    append(
        conn,
        clock,
        org_id=org_id,
        actor=by.actor,
        kind="invite.revoked",
        subject_id=invite_id,
        payload={"email": done.email, "role": done.role},
    )


def list_invites(conn: Connection, clock: Clock, org_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, email, role, expires_at, used_at, revoked_at, created_at FROM invites WHERE "
            "org_id=:o "
            "ORDER BY created_at DESC, id LIMIT 100"
        ),
        {"o": org_id},
    ).all()
    now = clock.now()
    return [
        {
            "id": r.id,
            "email": r.email,
            "role": r.role,
            "expires_at": r.expires_at,
            "created_at": r.created_at,
            "state": _invite_state(r, now),
        }
        for r in rows
    ]


# ------------------------------------------------------------------------------------------ team
def list_members(conn: Connection, org_id: str) -> list[Any]:
    return list(
        conn.execute(
            text(
                "SELECT id, email, display_name, role, created_at, email_verified_at FROM users "
                "WHERE org_id=:o "
                "AND removed_at IS NULL AND password_hash IS NOT NULL ORDER BY created_at, id"
            ),
            {"o": org_id},
        ).all()
    )


def change_role(conn: Connection, clock: Clock, *, by: Member, org_id: str, user_id: str, role: Role) -> None:
    """DSH-11. Owners and admins change roles; only an account owner grants or takes away that role."""
    if role not in MEMBER_ROLES:
        raise AccessError("invalid_role", "Choose one of the listed roles.")
    _require_member_of(by, org_id)
    _require(by, "team.manage")
    org = load_org(conn, org_id, lock=True)
    _require_unlocked(org, clock.now())
    target = _active_member(conn, org_id, user_id, lock=True)
    old = Role(target.role)
    if old == role:
        return
    if Role.ACCOUNT_OWNER in (old, role):
        _require(by, "team.grant_account_owner")
    _guarded_update(
        conn,
        "UPDATE users SET role=:r WHERE org_id=:o AND id=:u",
        {"r": role.value, "o": org_id, "u": user_id},
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=by.actor,
        kind="member.role_changed",
        subject_id=user_id,
        payload={"from": old.value, "to": role.value},
    )


def remove_member(conn: Connection, clock: Clock, *, by: Member, org_id: str, user_id: str) -> int:
    """DSH-11. The member can no longer sign in, and API keys issued to them are revoked at once.
    Returns the number of keys revoked."""
    _require_member_of(by, org_id)
    _require(by, "team.manage")
    org = load_org(conn, org_id, lock=True)
    _require_unlocked(org, clock.now())
    target = _active_member(conn, org_id, user_id, lock=True)
    if Role(target.role) == Role.ACCOUNT_OWNER:
        _require(by, "team.grant_account_owner")
    now = clock.now()
    _guarded_update(
        conn,
        "UPDATE users SET removed_at=:now, removed_by=:by WHERE org_id=:o AND id=:u",
        {"now": now, "by": by.id, "o": org_id, "u": user_id},
    )
    keys = (
        conn.execute(
            text(
                "UPDATE api_keys SET revoked_at=:now WHERE org_id=:o AND user_id=:u AND revoked_at "
                "IS NULL RETURNING id"
            ),
            {"now": now, "o": org_id, "u": user_id},
        )
        .scalars()
        .all()
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=by.actor,
        kind="member.removed",
        subject_id=user_id,
        payload={"email": target.email, "role": target.role, "keys_revoked": sorted(keys)},
    )
    return len(keys)


def _guarded_update(conn: Connection, sql: str, params: dict[str, Any]) -> None:
    try:
        with conn.begin_nested():
            conn.execute(text(sql), params)
    except IntegrityError as exc:
        if "account owner" in str(exc.orig):
            raise AccessError(
                "last_account_owner", "The organisation must keep at least one account owner.", status=409
            ) from exc
        raise


def _active_member(conn: Connection, org_id: str, user_id: str, *, lock: bool = False) -> Any:
    row = conn.execute(
        text(
            "SELECT id, email, role FROM users WHERE org_id=:o AND id=:u AND removed_at IS NULL "  # noqa: S608
            "AND password_hash IS NOT NULL" + (" FOR UPDATE" if lock else "")
        ),
        {"o": org_id, "u": user_id},
    ).one_or_none()
    if row is None:
        raise AccessError("not_found", "No such member.", status=404)
    return row


# ------------------------------------------------------------------------------------------ sign-in
def authenticate(conn: Connection, email: str, password: str) -> Member | None:
    """DSH-02. The same time is spent whether or not the email exists."""
    row = conn.execute(
        text(
            "SELECT id, org_id, email, display_name, role, password_hash FROM users WHERE "
            "lower(email)=lower(:e) "
            "AND password_hash IS NOT NULL AND removed_at IS NULL"
        ).execution_options(**_LOGIN),
        {"e": email.strip()},
    ).one_or_none()
    if not verify_password(row.password_hash if row else None, password) or row is None:
        return None
    return Member(row.id, row.org_id, row.email, row.display_name, Role(row.role))


def load_member(conn: Connection, org_id: str, user_id: str) -> Member | None:
    row = conn.execute(
        text(
            "SELECT id, org_id, email, display_name, role FROM users WHERE org_id=:o AND id=:u "
            "AND removed_at IS NULL AND password_hash IS NOT NULL"
        ),
        {"o": org_id, "u": user_id},
    ).one_or_none()
    return None if row is None else Member(row.id, row.org_id, row.email, row.display_name, Role(row.role))


def create_staff(conn: Connection, clock: Clock, *, email: str, display_name: str, password: str) -> Member:
    """`detent staff add`: a DekernAI admin (an admin of the operator organisation). Command line only."""
    email = normalise_email(email)
    try:
        check_new_password(password, email=email)
    except ValueError as exc:
        raise AccessError("weak_password", str(exc)) from exc
    now = clock.now()
    conn.execute(
        text(
            "INSERT INTO organisations (id, name, mode, fail_safe, kind, created_at) VALUES (:o, "
            "'DekernAI operator (internal)', 'shadow', 'manual_queue', 'demo', :now) ON CONFLICT "
            "(id) DO NOTHING"
        ),
        {"o": OPERATOR_ORG, "now": now},
    )
    uid = new_id(Prefix.USR, now)
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    "INSERT INTO users (id, org_id, email, display_name, role, password_hash, "
                    "email_verified_at, "
                    "password_changed_at, created_at) VALUES (:id, :o, :e, :n, 'admin', :h, :now, :now, :now)"
                ),
                {
                    "id": uid,
                    "o": OPERATOR_ORG,
                    "e": email,
                    "n": display_name.strip() or email,
                    "h": hash_password(password),
                    "now": now,
                },
            )
    except IntegrityError as exc:
        raise AccessError("email_in_use", "That address already has a login.", status=409) from exc
    member = Member(uid, OPERATOR_ORG, email, display_name.strip() or email, STAFF_ROLE)
    append(
        conn,
        clock,
        org_id=OPERATOR_ORG,
        actor=Actor.system("cli"),
        kind="staff.created",
        subject_id=uid,
        payload={"email": email},
    )
    return member


# ------------------------------------------------------------------------------------------ checks
def _require(member: Member, action: str) -> None:
    if not allowed(action, member.role):
        raise AccessError("forbidden", "Your role can't do that.", status=403)


def _require_member_of(member: Member, org_id: str) -> None:
    if member.org_id != org_id:
        raise AccessError("not_found", "No such organisation.", status=404)


def _require_staff(member: Member) -> None:
    if not member.is_staff:
        raise AccessError("forbidden", "Only a DekernAI admin can do that.", status=403)


def _require_unlocked(org: Any, now: datetime) -> None:
    status = org_status(org, now)
    if status != "active":
        raise AccessError(f"organisation_{status}", LOCKED_MESSAGES[status], status=403)


LOCKED_MESSAGES = {
    "expired": "This evaluation has expired, so the organisation is read-only. Ask DekernAI to extend it.",
    "suspended": "This organisation is suspended, so it is read-only. Contact DekernAI.",
}
