"""POL-07, C-06: rule changes are drafts; activation needs two different people, one of them the
compliance lead, who attests. Every version is kept; decisions link to the version they used."""

from __future__ import annotations

import pytest
from decision_helpers import DecisionOrg, setup_decision_org
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.policy.changes import (
    AttestationRequired,
    ChangeError,
    approve_draft,
    list_versions,
    propose_draft,
    withdraw_draft,
)
from detent.policy.store import active_policy
from policy_helpers import v2
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.db

LOOSER = ('auto_limit: {USDC: "10000.00"', 'auto_limit: {USDC: "15000.00"')
TIGHTER = ('auto_limit: {USDC: "10000.00"', 'auto_limit: {USDC: "8000.00"')


@pytest.fixture
def dorg(engine: Engine, clock: FrozenClock) -> DecisionOrg:
    return setup_decision_org(engine, clock)


def who(d: DecisionOrg, role: Role) -> Actor:
    return Actor(d.org.users[role], role.value)


def test_draft_does_not_change_the_active_version(
    dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    draft = propose_draft(
        engine, clock, org_id=dorg.id, actor=who(dorg, Role.PAYMENTS_LEAD), yaml_text=v2(LOOSER)
    )
    assert draft.loosening and draft.version == 2
    assert {"path": "checks.limits.auto_limit.USDC", "old": "10000.00", "new": "15000.00"} in draft.diff
    with engine.connect() as c:
        assert active_policy(c, dorg.id).version == 1


def test_proposer_cannot_approve_their_own_draft(
    dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pl = who(dorg, Role.PAYMENTS_LEAD)
    draft = propose_draft(engine, clock, org_id=dorg.id, actor=pl, yaml_text=v2(TIGHTER))
    with pytest.raises(ChangeError, match="different"):
        approve_draft(engine, clock, org_id=dorg.id, draft_id=draft.id, actor=pl, attest=True)


def test_compliance_lead_must_be_one_of_the_two(
    dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    # C-06: every activation, tightening included, needs the compliance lead.
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO users (id, org_id, email, display_name, role, created_at) "
                "VALUES (:id, :o, :e, 'Second payments lead', 'payments_lead', :t)"
            ),
            {
                "id": f"usr_pl2_{dorg.id[-6:]}",
                "o": dorg.id,
                "e": f"pl2-{dorg.id}@test.invalid",
                "t": clock.now(),
            },
        )
    pl2 = Actor(f"usr_pl2_{dorg.id[-6:]}", Role.PAYMENTS_LEAD.value)
    draft = propose_draft(
        engine, clock, org_id=dorg.id, actor=who(dorg, Role.PAYMENTS_LEAD), yaml_text=v2(TIGHTER)
    )
    with pytest.raises(ChangeError, match="compliance lead"):
        approve_draft(engine, clock, org_id=dorg.id, draft_id=draft.id, actor=pl2, attest=True)


def test_roles_outside_the_leads_cannot_propose_or_approve(
    dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    with pytest.raises(ChangeError, match="may not"):
        propose_draft(engine, clock, org_id=dorg.id, actor=who(dorg, Role.REVIEWER), yaml_text=v2(TIGHTER))
    draft = propose_draft(
        engine, clock, org_id=dorg.id, actor=who(dorg, Role.PAYMENTS_LEAD), yaml_text=v2(TIGHTER)
    )
    with pytest.raises(ChangeError, match="may not"):
        approve_draft(
            engine, clock, org_id=dorg.id, draft_id=draft.id, actor=who(dorg, Role.REVIEWER), attest=True
        )


def test_activation_records_attestation_and_supersedes(
    dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    draft = propose_draft(
        engine, clock, org_id=dorg.id, actor=who(dorg, Role.PAYMENTS_LEAD), yaml_text=v2(LOOSER)
    )
    cl = who(dorg, Role.COMPLIANCE_LEAD)
    with pytest.raises(AttestationRequired):
        approve_draft(engine, clock, org_id=dorg.id, draft_id=draft.id, actor=cl, attest=False)
    approve_draft(engine, clock, org_id=dorg.id, draft_id=draft.id, actor=cl, attest=True)
    with engine.connect() as c:
        assert active_policy(c, dorg.id).version == 2
        row = c.execute(
            text("SELECT * FROM policy_versions WHERE org_id=:o AND id=:i"), {"o": dorg.id, "i": draft.id}
        ).one()
        ev = c.execute(
            text(
                "SELECT payload FROM audit_events WHERE org_id=:o AND kind='policy.activated' AND subject_id=:i"
            ),
            {"o": dorg.id, "i": draft.id},
        ).scalar_one()
    assert row.status == "active" and row.attested_by == cl.id and row.loosening
    assert row.approved_by == [cl.id] and row.proposed_by == dorg.org.users[Role.PAYMENTS_LEAD]
    assert "AML accountability" in row.attestation
    assert ev["approvers"] == [dorg.org.users[Role.PAYMENTS_LEAD], cl.id] and ev["loosening"] is True
    versions = list_versions(engine, dorg.id)
    assert [(v["version"], v["status"]) for v in versions] == [(2, "active"), (1, "superseded")]


def test_compliance_lead_can_propose_and_payments_lead_approves(
    dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    cl = who(dorg, Role.COMPLIANCE_LEAD)
    with pytest.raises(AttestationRequired):
        propose_draft(engine, clock, org_id=dorg.id, actor=cl, yaml_text=v2(LOOSER), attest=False)
    draft = propose_draft(engine, clock, org_id=dorg.id, actor=cl, yaml_text=v2(LOOSER), attest=True)
    approve_draft(engine, clock, org_id=dorg.id, draft_id=draft.id, actor=who(dorg, Role.PAYMENTS_LEAD))
    with engine.connect() as c:
        assert active_policy(c, dorg.id).version == 2


def test_version_must_follow_the_latest_and_one_draft_at_a_time(
    dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pl = who(dorg, Role.PAYMENTS_LEAD)
    with pytest.raises(ChangeError, match="version 2"):
        propose_draft(
            engine, clock, org_id=dorg.id, actor=pl, yaml_text=v2(TIGHTER).replace("version: 2", "version: 5")
        )
    with pytest.raises(ChangeError, match="line"):
        propose_draft(engine, clock, org_id=dorg.id, actor=pl, yaml_text="version: 2\nchecks: [")
    d = propose_draft(engine, clock, org_id=dorg.id, actor=pl, yaml_text=v2(TIGHTER))
    with pytest.raises(ChangeError, match="already a draft"):
        propose_draft(engine, clock, org_id=dorg.id, actor=pl, yaml_text=v2(LOOSER))
    withdraw_draft(engine, clock, org_id=dorg.id, draft_id=d.id, actor=pl)
    d3 = propose_draft(
        engine, clock, org_id=dorg.id, actor=pl, yaml_text=v2(LOOSER).replace("version: 2", "version: 3")
    )
    assert d3.version == 3
    statuses = {v["version"]: v["status"] for v in list_versions(engine, dorg.id)}
    assert statuses == {1: "active", 2: "withdrawn", 3: "draft"}


def test_stored_versions_cannot_be_edited_or_deleted(
    dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    d = propose_draft(
        engine, clock, org_id=dorg.id, actor=who(dorg, Role.PAYMENTS_LEAD), yaml_text=v2(TIGHTER)
    )
    for sql in (
        "UPDATE policy_versions SET yaml='x' WHERE org_id=:o AND id=:i",
        "DELETE FROM policy_versions WHERE org_id=:o AND id=:i",
    ):
        with pytest.raises(DBAPIError), engine.begin() as c:
            c.execute(text(sql), {"o": dorg.id, "i": d.id})


def test_decisions_link_to_the_version_they_used(
    dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    import uuid

    from conftest import make_settings
    from decision_helpers import PEPPER, payout
    from detent.api.app import create_app
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    s = make_settings(dorg.id, api_key_pepper=SecretStr(PEPPER))
    body = payout(
        "cpt_quill",
        "500.00",
        "GBP",
        {"destination_id": "dst_quill_acct", "kind": "bank_account", "network": "banksim-fps"},
    )
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as api:
        h = {**dorg.auth(), "Idempotency-Key": str(uuid.uuid4())}
        first = api.post("/v1/payment_intents", json=body, headers=h).json()
        d = propose_draft(
            engine, clock, org_id=dorg.id, actor=who(dorg, Role.PAYMENTS_LEAD), yaml_text=v2(TIGHTER)
        )
        approve_draft(
            engine, clock, org_id=dorg.id, draft_id=d.id, actor=who(dorg, Role.COMPLIANCE_LEAD), attest=True
        )
        h2 = {**dorg.auth(), "Idempotency-Key": str(uuid.uuid4())}
        second = api.post("/v1/payment_intents", json=body, headers=h2).json()
        assert first["decision"]["policy_version"] == 1 and second["decision"]["policy_version"] == 2
        r = api.get("/v1/policy/versions", headers=dorg.auth())
        assert r.status_code == 200 and [v["version"] for v in r.json()["data"]] == [2, 1]
        one = api.get("/v1/policy/versions/1", headers=dorg.auth()).json()
        assert one["status"] == "superseded" and "auto_limit" in one["yaml"]
        assert api.get("/v1/policy/versions/9", headers=dorg.auth()).status_code == 404
