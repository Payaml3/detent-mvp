"""P2 group 1: password rules, safe redirects and the spec/08 dashboard permissions (DSH-02, DSH-11)."""

from __future__ import annotations

import pytest
from detent.dashboard.passwords import WeakPassword, check_new_password, hash_password, verify_password
from detent.dashboard.web import safe_next
from detent.domain.roles import MEMBER_ROLES, Role, allowed


def test_passwords_are_argon2id_and_verify() -> None:
    h = hash_password("a long sandbox passphrase 42")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "a long sandbox passphrase 42")
    assert not verify_password(h, "a long sandbox passphrase 43")
    assert not verify_password(None, "not-a-real-password-for-timing-only")  # the timing dummy never signs in
    assert not verify_password("not a hash", "anything")


@pytest.mark.parametrize(
    "password",
    ["short", "x" * 257, "aaaaaaaaaaaaaaaa", "ada@example.test", "my ada@example.test!"],
)
def test_weak_passwords_are_refused(password: str) -> None:
    with pytest.raises(WeakPassword):
        check_new_password(password, email="ada@example.test")


def test_redirects_after_sign_in_stay_on_site() -> None:
    assert safe_next("/dashboard/team", "/") == "/dashboard/team"
    assert safe_next("/admin/", "/") == "/admin/"
    for bad in (
        "https://evil.example",
        "//evil.example",
        "/dashboard//evil",
        "/console/",
        "/\\evil",
        None,
        "",
    ):
        assert safe_next(bad, "/dashboard/") == "/dashboard/"


def test_member_roles_are_the_spec_02_list() -> None:
    assert {r.value for r in MEMBER_ROLES} == {
        "account_owner", "admin", "developer", "payments_lead", "compliance_lead", "reviewer", "backup_owner",
        "auditor",
    }  # fmt: skip
    assert Role.ONCALL not in MEMBER_ROLES  # DekernAI only


def test_dashboard_permissions_follow_spec_08() -> None:
    def who(action: str) -> set[str]:
        return {r.value for r in Role if allowed(action, r)}

    assert who("team.manage") == {"account_owner", "admin"}
    assert who("team.grant_account_owner") == {"account_owner"}
    assert who("keys.manage") == who("webhooks.manage") == {"account_owner", "admin", "developer"}
    assert who("request_logs.read") == who("sandbox.control") == {"account_owner", "admin", "developer"}
    assert who("verification.request") == {"account_owner", "admin"}
    assert "auditor" not in who("demo.clock.advance")
    for action in ("exception.approve", "policy.approve", "kill_switch.release", "mandate.issue"):
        assert "auditor" not in who(action) and "developer" not in who(action)
