"""Roles and the permission table (FND-04).

Role checks run on the server through ``detent.console.auth.require_permission``. Hiding a
button is never the only control.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ACCOUNT_OWNER = "account_owner"
    DEVELOPER = "developer"
    AUDITOR = "auditor"  # C-14: read-only (audit, replay, export)
    PAYMENTS_LEAD = "payments_lead"
    COMPLIANCE_LEAD = "compliance_lead"
    REVIEWER = "reviewer"
    BACKUP_OWNER = "backup_owner"
    ONCALL = "oncall"
    ADMIN = "admin"


R = Role

# DSH-11: the roles a client organisation's members can hold (spec/08). `oncall` is DekernAI only.
MEMBER_ROLES: tuple[Role, ...] = (
    R.ACCOUNT_OWNER,
    R.ADMIN,
    R.DEVELOPER,
    R.PAYMENTS_LEAD,
    R.COMPLIANCE_LEAD,
    R.REVIEWER,
    R.BACKUP_OWNER,
    R.AUDITOR,
)
_OWNERS = frozenset({R.ACCOUNT_OWNER, R.ADMIN})
_BUILDERS = frozenset({R.ACCOUNT_OWNER, R.ADMIN, R.DEVELOPER})

# Action -> roles allowed to perform it. Later stories add their actions here.
PERMISSIONS: dict[str, frozenset[Role]] = {
    # Invariant 10: anyone on duty can engage; only the payments lead releases.
    "kill_switch.engage": frozenset({R.PAYMENTS_LEAD, R.ONCALL}),
    "kill_switch.release": frozenset({R.PAYMENTS_LEAD}),
    "exception.approve": frozenset({R.REVIEWER, R.BACKUP_OWNER, R.PAYMENTS_LEAD}),
    "exception.reject": frozenset({R.REVIEWER, R.BACKUP_OWNER, R.PAYMENTS_LEAD}),
    "policy.propose": frozenset({R.PAYMENTS_LEAD, R.COMPLIANCE_LEAD}),
    "policy.approve": frozenset({R.PAYMENTS_LEAD, R.COMPLIANCE_LEAD}),
    "mandate.issue": frozenset({R.PAYMENTS_LEAD}),
    "mandate.revoke": frozenset({R.PAYMENTS_LEAD}),
    "recon.approve_fix": frozenset({R.PAYMENTS_LEAD}),
    # EXE-09: a mode change is never a single-person action; see mode_change_approved().
    "org.change_mode.propose": frozenset({R.PAYMENTS_LEAD, R.COMPLIANCE_LEAD}),
    "demo.clock.advance": frozenset(Role) - {R.AUDITOR},
    # INT-04: editing payout details. Payments lead only (G-23, Proposed: the narrowest safe choice).
    "counterparty.edit": frozenset({R.PAYMENTS_LEAD}),
    # OPS-01: opening and working an incident (DekernAI on-call and the client's two leads).
    "incident.manage": frozenset({R.ONCALL, R.PAYMENTS_LEAD, R.COMPLIANCE_LEAD}),
    # INT-05: cancelling before sending; spec/02 "payments lead cancels".
    "payment.cancel": frozenset({R.PAYMENTS_LEAD}),
    # EXE-06: the UNKNOWN_STUCK case goes to the payments lead (spec/04 owners).
    "unknown.cancel_by_replacement": frozenset({R.PAYMENTS_LEAD}),
    # DSH-11, spec/08 dashboard permissions. Only an account owner can grant or take away that role.
    "team.manage": _OWNERS,
    "team.grant_account_owner": frozenset({R.ACCOUNT_OWNER}),
    "settings.manage": _OWNERS,
    "verification.request": _OWNERS,
    "keys.manage": _BUILDERS,
    "webhooks.manage": _BUILDERS,
    "request_logs.read": _BUILDERS,
    "sandbox.control": _BUILDERS,
}


def allowed(action: str, role: Role) -> bool:
    roles = PERMISSIONS.get(action)
    if roles is None:
        # Fail closed: an action missing from the table is allowed for nobody.
        return False
    return role in roles


def mode_change_approved(*, proposer: tuple[str, Role], approver: tuple[str, Role]) -> bool:
    """EXE-09: a mode change needs the payments lead and the compliance lead, as two different people."""
    (proposer_id, proposer_role), (approver_id, approver_role) = proposer, approver
    both_leads = {proposer_role, approver_role} == {R.PAYMENTS_LEAD, R.COMPLIANCE_LEAD}
    return proposer_id != approver_id and both_leads
