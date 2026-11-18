from detent.domain.roles import Role, allowed


def test_only_payments_lead_releases_kill_switch() -> None:
    assert allowed("kill_switch.release", Role.PAYMENTS_LEAD)
    for r in Role:
        if r is not Role.PAYMENTS_LEAD:
            assert not allowed("kill_switch.release", r)


def test_oncall_can_engage_kill_switch() -> None:
    assert allowed("kill_switch.engage", Role.ONCALL)


def test_unknown_action_is_denied_for_everyone() -> None:
    assert not any(allowed("payments.teleport", r) for r in Role)


def test_no_single_role_can_change_the_mode_alone() -> None:
    # EXE-09: a mode change needs the payments lead AND the compliance lead.
    assert not any(allowed("org.change_mode", r) for r in Role)


def test_mode_change_needs_both_leads_as_two_different_people() -> None:
    from detent.domain.roles import mode_change_approved

    pl, cl = Role.PAYMENTS_LEAD, Role.COMPLIANCE_LEAD
    assert mode_change_approved(proposer=("usr_a", pl), approver=("usr_b", cl))
    assert mode_change_approved(proposer=("usr_a", cl), approver=("usr_b", pl))
    # Same role twice, a non-lead, or one person in both seats is refused.
    assert not mode_change_approved(proposer=("usr_a", pl), approver=("usr_b", pl))
    assert not mode_change_approved(proposer=("usr_a", pl), approver=("usr_b", Role.REVIEWER))
    assert not mode_change_approved(proposer=("usr_a", pl), approver=("usr_a", cl))
