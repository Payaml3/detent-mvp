"""P2 group 1: KYB-gated organisations, owner invite and sign-up, team roles, expiry and suspension
(DSH-01, DSH-02, DSH-03, DSH-11)."""

from __future__ import annotations

import re
import secrets
import threading
from datetime import timedelta
from typing import Any

import pytest
from conftest import make_settings
from detent.api.app import create_app
from detent.api.auth import issue_key
from detent.clock import FrozenClock
from detent.dashboard import access
from detent.dashboard.access import AccessError, Member
from detent.domain.roles import Role
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

PASSWORD = "a long sandbox passphrase 42"
PEPPER = "test-pepper-abcdef123456"
SETTINGS = make_settings("org_detent", dashboard_url="https://dashboard.example.test")


def _email(tag: str) -> str:
    return f"{tag}-{secrets.token_hex(4)}@example.test"


@pytest.fixture
def staff(engine: Engine, clock: FrozenClock) -> Member:
    with engine.begin() as conn:
        return access.create_staff(
            conn, clock, email=_email("staff"), display_name="Staff Admin", password=PASSWORD
        )


@pytest.fixture
def web(engine: Engine, clock: FrozenClock) -> Any:
    settings = SETTINGS
    app = create_app(settings, engine=engine, clock=clock, configure_logging=False)
    with TestClient(app) as c:
        yield c


def token_of(c: TestClient, path: str = "/dashboard/login") -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', c.get(path).text)
    assert m, path
    return m.group(1)


def sign_in(c: TestClient, email: str, password: str = PASSWORD) -> Any:
    return c.post(
        "/dashboard/login",
        data={"email": email, "password": password, "csrf": token_of(c), "next": ""},
        follow_redirects=False,
    )


def post(c: TestClient, path: str, data: dict[str, str], page: str = "/dashboard/") -> Any:
    return c.post(path, data={**data, "csrf": token_of(c, page)}, follow_redirects=False)


def link_in_outbox(engine: Engine, org_id: str, email: str) -> str:
    with engine.connect() as conn:
        body = conn.execute(
            text(
                "SELECT body FROM outbox WHERE org_id=:o AND recipient=:e AND channel='email_mock' "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"o": org_id, "e": email},
        ).scalar_one()
    m = re.search(r"/dashboard/invite/([A-Za-z0-9_-]+)", body)
    assert m and "https://dashboard.example.test/dashboard/invite/" in body
    return m.group(1)


def accept(c: TestClient, token: str, name: str = "Ada Owner", password: str = PASSWORD) -> Any:
    c.get(f"/dashboard/invite/{token}")
    csrf = token_of(c)
    return c.post(
        f"/dashboard/invite/{token}",
        data={"display_name": name, "password": password, "password_again": password, "csrf": csrf},
        follow_redirects=False,
    )


def audit_kinds(engine: Engine, org_id: str) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text("SELECT kind FROM audit_events WHERE org_id=:o ORDER BY seq"), {"o": org_id}
            ).scalars()
        )


def new_client_org(engine: Engine, clock: FrozenClock, staff: Member, owner_email: str) -> tuple[str, str]:
    with engine.begin() as conn:
        return access.create_organisation(
            conn, clock, SETTINGS, staff=staff, kind="client", name="Fictional Payouts Ltd",
            owner_email=owner_email, kyb_reference="KYB-2026-0042", kyb_approved_on=clock.now().date(),
        )  # fmt: skip


def owner_of(engine: Engine, clock: FrozenClock, staff: Member) -> tuple[str, Member]:
    email = _email("owner")
    org_id, token = new_client_org(engine, clock, staff, email)
    with engine.begin() as conn:
        member = access.accept_invite(conn, clock, token=token, display_name="Ada Owner", password=PASSWORD)
    return org_id, member


# ------------------------------------------------------------------------------------------ DSH-01
def test_there_is_no_public_sign_up_route(web: TestClient) -> None:
    paths = [getattr(r, "path", "") for r in web.app.routes]  # type: ignore[attr-defined]
    assert not [p for p in paths if re.search(r"sign.?up|register", p, re.I)]
    assert web.post("/dashboard/signup", data={}).status_code in (403, 404, 405)
    assert web.get("/dashboard/invite/not-a-real-token").status_code == 404
    assert "no public sign-up" in web.get("/dashboard/login").text.lower()


def test_admin_creates_a_client_org_only_with_kyb_and_invites_the_owner(
    web: TestClient, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    assert sign_in(web, staff.email).headers["location"] == "/admin/"
    owner = _email("owner")
    form = {"kind": "client", "name": "Fictional Payouts Ltd", "owner_email": owner}
    r = post(web, "/admin/organisations", form, page="/admin/organisations/new")
    assert r.status_code == 422 and "KYB approval reference and date" in r.text
    r = post(web, "/admin/organisations", {**form, "kyb_reference": "KYB-2026-0042", "kyb_approved_on": "2026-12-01"},
             page="/admin/organisations/new")  # fmt: skip
    assert r.status_code == 303
    org_id = r.headers["location"].rsplit("/", 1)[1]
    first = web.get(f"/admin/organisations/{org_id}").text
    assert "https://dashboard.example.test/dashboard/invite/" in first
    assert "/dashboard/invite/" not in web.get(f"/admin/organisations/{org_id}").text  # shown once
    with engine.connect() as conn:
        org = conn.execute(
            text(
                "SELECT kind, kyb_reference, kyb_approved_on, expires_at FROM organisations WHERE org_id=:o"
            ),
            {"o": org_id},
        ).one()
        inv = conn.execute(
            text("SELECT role, expires_at, created_at, used_at FROM invites WHERE org_id=:o"), {"o": org_id}
        ).one()
        seeded = conn.execute(
            text("SELECT (SELECT count(*) FROM counterparties WHERE org_id=:o), "
                 "(SELECT count(*) FROM policy_versions WHERE org_id=:o AND status='active'), "
                 "(SELECT count(*) FROM destinations WHERE org_id=:o AND user_account_ref IS NOT NULL)"),
            {"o": org_id}
        ).one()  # fmt: skip
    assert (org.kind, org.kyb_reference, str(org.kyb_approved_on), org.expires_at) == (
        "client", "KYB-2026-0042", "2026-12-01", None,
    )  # fmt: skip
    assert inv.role == "account_owner" and inv.used_at is None
    assert inv.expires_at - inv.created_at == timedelta(days=7)
    assert seeded[0] > 0 and seeded[1] == 1  # G-18: fictional counterparties and rule set v1
    assert seeded[2] == 3  # USR-04: fictional user accounts, one destination each
    link_in_outbox(engine, org_id, owner)
    assert audit_kinds(engine, org_id)[-2:] == ["organisation.created", "invite.sent"]


def test_the_database_refuses_a_client_org_without_kyb(engine: Engine, clock: FrozenClock) -> None:
    with pytest.raises(Exception, match="organisations_client_needs_kyb"), engine.begin() as conn:
        conn.execute(
            text("INSERT INTO organisations (id, name, mode, fail_safe, kind, created_at) "
                 "VALUES (:id, 'x', 'shadow', 'manual_queue', 'client', :now)"),
            {"id": f"org_t{secrets.token_hex(6)}", "now": clock.now()},
        )  # fmt: skip


def test_an_evaluation_org_expires_after_60_days_by_default(
    engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    with engine.begin() as conn:
        org_id, _ = access.create_organisation(
            conn, clock, SETTINGS, staff=staff, kind="evaluation", name="Evaluation Co",
            owner_email=_email("eval"),
        )  # fmt: skip
        org = access.load_org(conn, org_id)
    assert org.kind == "evaluation" and org.kyb_reference is None
    assert org.expires_at - clock.now() == timedelta(days=60)


def test_staff_only_actions_refuse_other_members(engine: Engine, clock: FrozenClock, staff: Member) -> None:
    org_id, owner = owner_of(engine, clock, staff)
    with engine.begin() as conn, pytest.raises(AccessError, match="DekernAI admin"):
        access.suspend(conn, clock, staff=owner, org_id=org_id, reason="trying")


# ------------------------------------------------------------------------------------------ DSH-02
def test_the_invite_link_verifies_the_email_and_sets_an_argon2_password(
    web: TestClient, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    owner = _email("owner")
    org_id, _ = new_client_org(engine, clock, staff, owner)
    token = link_in_outbox(engine, org_id, owner)
    page = web.get(f"/dashboard/invite/{token}").text
    assert owner in page and "Fictional Payouts Ltd" in page
    r = accept(web, token, password="short")
    assert r.status_code == 422 and "at least 12" in r.text
    r = accept(web, token)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard/?welcome=1"
    with engine.connect() as conn:
        user = conn.execute(
            text("SELECT role, password_hash, email_verified_at FROM users WHERE org_id=:o AND email=:e"),
            {"o": org_id, "e": owner},
        ).one()
    assert user.role == "account_owner"
    assert user.password_hash.startswith("$argon2id$") and PASSWORD not in user.password_hash
    assert user.email_verified_at == clock.now()
    assert "invite.accepted" in audit_kinds(engine, org_id)


def test_first_login_shows_the_onboarding_checklist(
    web: TestClient, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    owner = _email("owner")
    org_id, _ = new_client_org(engine, clock, staff, owner)
    accept(web, link_in_outbox(engine, org_id, owner))
    home = web.get("/dashboard/?welcome=1").text
    for step in (
        "Invite your team",
        "Create sandbox keys",
        "Set up policy",
        "Integrate",
        "Request verification",
    ):
        assert step in home
    assert "Your email is confirmed" in home
    post(web, "/dashboard/logout", {})
    assert web.get("/dashboard/", follow_redirects=False).headers["location"].startswith("/dashboard/login")
    assert sign_in(web, owner, "wrong password entirely").status_code == 401
    assert sign_in(web, owner).headers["location"] == "/dashboard/"


def test_invites_are_single_use_and_expire(
    web: TestClient, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    owner = _email("owner")
    org_id, token = new_client_org(engine, clock, staff, owner)
    assert accept(web, token).status_code == 303
    web.cookies.clear()
    assert accept(web, token).status_code == 410  # used
    with engine.begin() as conn:
        member = access.load_member(
            conn,
            org_id,
            conn.execute(
                text("SELECT id FROM users WHERE org_id=:o AND email=:e"), {"o": org_id, "e": owner}
            ).scalar_one(),
        )
        assert member is not None
        late = access.invite(conn, clock, SETTINGS, org_id=org_id, email=_email("dev"),
                             role=Role.DEVELOPER, by=member)  # fmt: skip
    clock.advance(timedelta(days=7, seconds=1))
    r = web.get(f"/dashboard/invite/{late}")
    assert r.status_code == 410 and "expired" in r.text
    with engine.begin() as conn, pytest.raises(AccessError, match="expired"):
        access.accept_invite(conn, clock, token=late, display_name="Late", password=PASSWORD)


def test_emails_go_to_the_outbox_and_no_other_provider_can_be_set() -> None:
    with pytest.raises(ValueError, match="EMAIL_PROVIDER"):
        make_settings("org_detent", email_provider="smtp")


# ------------------------------------------------------------------------------------------ DSH-03
def _api_key(engine: Engine, clock: FrozenClock, org_id: str, user_id: str) -> str:
    with engine.begin() as conn:
        return issue_key(conn, clock, org_id, user_id, ["read"], PEPPER)


def test_an_expired_evaluation_is_locked_until_extended(
    web: TestClient, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    owner = _email("owner")
    with engine.begin() as conn:
        org_id, token = access.create_organisation(
            conn, clock, SETTINGS, staff=staff, kind="evaluation", name="Evaluation Co",
            owner_email=owner, expires_in_days=10,
        )  # fmt: skip
    accept(web, token)
    with engine.connect() as conn:
        uid = conn.execute(text("SELECT id FROM users WHERE org_id=:o"), {"o": org_id}).scalar_one()
    key = {"Authorization": f"Bearer {_api_key(engine, clock, org_id, uid)}"}
    assert web.get("/v1/payment_intents", headers=key).status_code == 200
    clock.advance(timedelta(days=10, seconds=1))
    r = web.get("/v1/payment_intents", headers=key)
    assert r.status_code == 403 and r.json()["error"]["code"] == "organisation_expired"
    assert "read-only" in web.get("/dashboard/").text
    r = post(
        web, "/dashboard/team/invite", {"email": _email("dev"), "role": "developer"}, page="/dashboard/team"
    )
    assert r.status_code == 403 and "read-only" in r.text
    with engine.begin() as conn:
        access.extend(conn, clock, staff=staff, org_id=org_id, days=30)
    assert web.get("/v1/payment_intents", headers=key).status_code == 200
    assert "organisation.extended" in audit_kinds(engine, org_id)


def test_a_client_org_never_expires_and_suspension_is_audited(
    web: TestClient, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    org_id, owner = owner_of(engine, clock, staff)
    key = {"Authorization": f"Bearer {_api_key(engine, clock, org_id, owner.id)}"}
    with engine.begin() as conn, pytest.raises(AccessError, match="Only an evaluation"):
        access.extend(conn, clock, staff=staff, org_id=org_id, days=5)
    clock.advance(timedelta(days=400))
    assert web.get("/v1/payment_intents", headers=key).status_code == 200
    sign_in(web, staff.email)
    r = post(web, f"/admin/organisations/{org_id}/suspend", {"reason": "KYB review reopened"}, page="/admin/")
    assert r.status_code == 303
    r = web.get("/v1/payment_intents", headers=key)
    assert r.status_code == 403 and r.json()["error"]["code"] == "organisation_suspended"
    with engine.connect() as conn:
        ev = conn.execute(
            text(
                "SELECT actor, actor_role, payload FROM audit_events WHERE org_id=:o AND kind='organisation.suspended'"
            ),
            {"o": org_id},
        ).one()
    assert ev.actor == staff.id and ev.payload["reason"] == "KYB review reopened"
    with engine.begin() as conn:
        access.unsuspend(conn, clock, staff=staff, org_id=org_id, reason="Review closed")
    assert web.get("/v1/payment_intents", headers=key).status_code == 200


# ------------------------------------------------------------------------------------------ DSH-11
def test_owner_invites_a_developer_who_cannot_manage_the_team(
    web: TestClient, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    owner = _email("owner")
    org_id, token = new_client_org(engine, clock, staff, owner)
    accept(web, token)
    dev = _email("dev")
    assert (
        post(
            web, "/dashboard/team/invite", {"email": dev, "role": "developer"}, page="/dashboard/team"
        ).status_code
        == 303
    )
    with engine.connect() as conn:
        inv = conn.execute(text("SELECT role, expires_at, created_at FROM invites WHERE org_id=:o AND email=:e"),
                           {"o": org_id, "e": dev}).one()  # fmt: skip
    assert inv.role == "developer" and inv.expires_at - inv.created_at == timedelta(days=7)
    post(web, "/dashboard/logout", {})
    web.cookies.clear()
    accept(web, link_in_outbox(engine, org_id, dev), name="Dev One")
    team = web.get("/dashboard/team").text
    assert "Dev One" in team and "Invite a member" not in team
    r = post(web, "/dashboard/team/invite", {"email": _email("x"), "role": "admin"}, page="/dashboard/team")
    assert r.status_code == 403 and "Your role can" in r.text


def test_roles_follow_spec_08_and_the_last_owner_stays(
    engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    org_id, owner = owner_of(engine, clock, staff)
    settings = SETTINGS
    members: dict[str, Member] = {}
    with engine.begin() as conn:
        for role in (Role.ADMIN, Role.DEVELOPER, Role.AUDITOR):
            tok = access.invite(
                conn, clock, settings, org_id=org_id, email=_email(role.value), role=role, by=owner
            )
            members[role.value] = access.accept_invite(
                conn, clock, token=tok, display_name=role.value, password=PASSWORD
            )
    admin, dev = members["admin"], members["developer"]
    with engine.begin() as conn:
        with pytest.raises(AccessError, match="role can't"):  # only an account owner grants that role
            access.change_role(conn, clock, by=admin, org_id=org_id, user_id=dev.id, role=Role.ACCOUNT_OWNER)
        access.change_role(conn, clock, by=admin, org_id=org_id, user_id=dev.id, role=Role.REVIEWER)
        with pytest.raises(AccessError, match="at least one account owner"):
            access.change_role(conn, clock, by=owner, org_id=org_id, user_id=owner.id, role=Role.ADMIN)
        with pytest.raises(AccessError, match="at least one account owner"):
            access.remove_member(conn, clock, by=owner, org_id=org_id, user_id=owner.id)
    with engine.begin() as conn, pytest.raises(Exception, match="at least one account owner"):
        conn.execute(
            text("UPDATE users SET role='admin' WHERE org_id=:o AND id=:u"), {"o": org_id, "u": owner.id}
        )
    kinds = audit_kinds(engine, org_id)
    assert kinds.count("invite.sent") >= 4 and "member.role_changed" in kinds


def test_two_owners_cannot_demote_each_other_at_once(
    engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    org_id, a = owner_of(engine, clock, staff)
    with engine.begin() as conn:
        tok = access.invite(conn, clock, SETTINGS, org_id=org_id, email=_email("b"),
                            role=Role.ACCOUNT_OWNER, by=a)  # fmt: skip
        b = access.accept_invite(conn, clock, token=tok, display_name="B", password=PASSWORD)
    barrier, results = threading.Barrier(2), []

    def demote(by: Member, target: Member) -> None:
        barrier.wait()
        try:
            with engine.begin() as conn:
                access.change_role(conn, clock, by=by, org_id=org_id, user_id=target.id, role=Role.ADMIN)
            results.append("ok")
        except AccessError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=demote, args=(a, b)), threading.Thread(target=demote, args=(b, a))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) in (["forbidden", "ok"], ["last_account_owner", "ok"])
    with engine.connect() as conn:
        owners = conn.execute(
            text(
                "SELECT count(*) FROM users WHERE org_id=:o AND role='account_owner' AND removed_at IS NULL"
            ),
            {"o": org_id},
        ).scalar_one()
    assert owners == 1


def test_removing_a_member_stops_their_sign_in_and_keys(
    web: TestClient, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    org_id, owner = owner_of(engine, clock, staff)
    dev_email = _email("dev")
    with engine.begin() as conn:
        tok = access.invite(conn, clock, SETTINGS, org_id=org_id, email=dev_email,
                            role=Role.DEVELOPER, by=owner)  # fmt: skip
        dev = access.accept_invite(conn, clock, token=tok, display_name="Dev", password=PASSWORD)
    key = {"Authorization": f"Bearer {_api_key(engine, clock, org_id, dev.id)}"}
    assert web.get("/v1/payment_intents", headers=key).status_code == 200
    assert sign_in(web, dev_email).status_code == 303
    with engine.begin() as conn:
        assert access.remove_member(conn, clock, by=owner, org_id=org_id, user_id=dev.id) == 1
    assert web.get("/dashboard/", follow_redirects=False).status_code == 303  # session ends at once
    assert sign_in(web, dev_email).status_code == 401
    assert web.get("/v1/payment_intents", headers=key).status_code == 401
    with engine.connect() as conn:
        ev = conn.execute(
            text("SELECT payload FROM audit_events WHERE org_id=:o AND kind='member.removed'"), {"o": org_id}
        ).scalar_one()
    assert ev["email"] == dev_email and len(ev["keys_revoked"]) == 1


def test_members_of_one_org_cannot_touch_another(engine: Engine, clock: FrozenClock, staff: Member) -> None:
    org_a, owner_a = owner_of(engine, clock, staff)
    org_b, owner_b = owner_of(engine, clock, staff)
    with engine.begin() as conn, pytest.raises(AccessError, match="No such organisation"):
        access.change_role(conn, clock, by=owner_a, org_id=org_b, user_id=owner_b.id, role=Role.ADMIN)
    with engine.begin() as conn, pytest.raises(AccessError, match="No such member"):
        access.remove_member(conn, clock, by=owner_a, org_id=org_a, user_id=owner_b.id)


def test_one_email_signs_in_to_one_organisation(engine: Engine, clock: FrozenClock, staff: Member) -> None:
    _, owner_a = owner_of(engine, clock, staff)
    org_b, owner_b = owner_of(engine, clock, staff)
    with engine.begin() as conn, pytest.raises(AccessError, match="another organisation"):
        access.invite(conn, clock, SETTINGS, org_id=org_b, email=owner_a.email.upper(),
                      role=Role.DEVELOPER, by=owner_b)  # fmt: skip


# ------------------------------------------------------------------------------------------ web safety
def test_posts_need_the_csrf_token(
    web: TestClient, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    sign_in(web, staff.email)
    r = web.post(
        "/admin/organisations", data={"kind": "evaluation", "name": "No token", "owner_email": _email("x")}
    )
    assert r.status_code == 400 and "form expired" in r.text


def test_admin_screens_are_hidden_from_client_members(
    web: TestClient, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    owner = _email("owner")
    _, token = new_client_org(engine, clock, staff, owner)
    accept(web, token)
    assert web.get("/admin/").status_code == 404
    assert web.get("/dashboard/login?next=//evil.example").status_code == 200
    r = sign_in(web, owner)
    assert r.headers["location"] == "/dashboard/"


def test_sign_in_attempts_are_limited(web: TestClient, staff: Member) -> None:
    codes = [sign_in(web, staff.email, "wrong password entirely").status_code for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429
