"""Roles and the permission table (FND-04).

Role checks run on the server through ``detent.console.auth.require_permission``. Hiding a
button is never the only control.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    PAYMENTS_LEAD = "payments_lead"
    COMPLIANCE_LEAD = "compliance_lead"
    REVIEWER = "reviewer"
    BACKUP_OWNER = "backup_owner"
    ONCALL = "oncall"
    ADMIN = "admin"


R = Role

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
    "org.change_mode": frozenset({R.PAYMENTS_LEAD, R.COMPLIANCE_LEAD}),
    "demo.clock.advance": frozenset(Role),
}


def allowed(action: str, role: Role) -> bool:
    roles = PERMISSIONS.get(action)
    if roles is None:
        # Fail closed: an action missing from the table is allowed for nobody.
        return False
    return role in roles
