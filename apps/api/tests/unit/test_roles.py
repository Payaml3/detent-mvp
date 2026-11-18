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
