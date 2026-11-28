"""CON-11: the client's AI team. Each agent as a team member, with its limits, its work and what people and
the rules did with it. Read-only, and agents still only propose (invariant 5)."""

from __future__ import annotations

import pytest
from conftest import login
from decision_helpers import DecisionOrg
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.mandates.store import fixture_mandate, issue_mandate
from detent.reconciliation.fixes import approve_fix, reject_fix
from detent.views.ai_team import ROSTER, ai_team
from fastapi.testclient import TestClient
from recon_helpers import build_500, reconcile
from sqlalchemy import Engine, text
from test_console_operations import bluefin, client
from test_instruction_agent import KEY, run

pytestmark = pytest.mark.db


def _audit_seq(engine: Engine, org_id: str) -> int:
    with engine.connect() as c:
        return int(
            c.execute(
                text("SELECT coalesce(max(seq), 0) FROM audit_events WHERE org_id=:o"), {"o": org_id}
            ).scalar_one()
        )


def _drain(engine: Engine, clock: FrozenClock, d: DecisionOrg) -> None:
    from conftest import make_settings
    from detent.runtime import Runtime
    from detent.worker.loop import Worker

    w = Worker(Runtime(make_settings(d.id), engine, clock), worker_id="ai-team-test")
    while w.run_one():
        pass


def test_the_page_shows_three_agents_their_limits_and_that_the_rules_decide(
    engine: Engine, clock: FrozenClock
) -> None:
    d, c = client(engine, clock)
    with c, engine.begin() as conn:
        issue_mandate(conn, clock, d.id, fixture_mandate(clock, d.id), KEY, actor=Actor.system("seed"))
    with c:
        run(engine, clock, d, "inv-canonical-18500-usdc.txt")
        login(c, d.org.users[Role.REVIEWER])
        before = _audit_seq(engine, d.id)
        r = c.get("/console/agents")
        assert r.status_code == 200
        page = r.text
        for prof in ROSTER:
            assert f'data-agent="{prof.kind}"' in page and prof.name in page
        assert "They propose; your rules and your people decide." in page
        member = page.split('data-member="instruction"', 1)[1].split('data-member="investigation"', 1)[0]
        assert "Mandate mnd_demo_ap_agent" in member and "20,000.00 USDC per payment" in member
        assert "Approve, send, retry or re-route a payment" in member.split('data-section="never"', 1)[1]
        assert "your policy decides execute, escalate or block" in member
        assert "Proposed 18,500.00 USDC to cpt_bluefin" in member and "recorded stand-in" in member
        assert "AI budget" in member and "tokens used today" in member
        assert "recorded stand-in answers" in page  # no AI key in tests: the page says so
        # Read-only: no forms, no buttons, nothing written to the audit log.
        main = page.split("<main", 1)[1].split("</main>", 1)[0]
        assert "<form" not in main and "<button" not in main
        assert _audit_seq(engine, d.id) == before
        assert 'href="/console/agents"' in page  # in the console navigation


def test_an_investigation_shows_who_approved_the_case(engine: Engine, clock: FrozenClock) -> None:
    d, c = client(engine, clock)
    with c:
        case_id = bluefin(c, d)["exception"]["id"]
        _drain(engine, clock, d)
        login(c, d.org.users[Role.REVIEWER])
        r = c.post(
            f"/console/exceptions/{case_id}/approve",
            data={"reason": "Known supplier"},
            follow_redirects=False,
        )
        assert r.status_code == 303, r.text
        page = c.get("/console/agents").text
    member = page.split('data-member="investigation"', 1)[1].split('data-member="reconciliation"', 1)[0]
    assert "recommends approve" in member and f'href="/console/exceptions/{case_id}"' in member
    reply = member.split('class="ai-replies"', 1)[1]
    assert "Test reviewer" in reply and "approved the case" in reply
    assert "accepted 1 and rejected 0" in member
    overview = c.get("/console/").text
    team_map = overview.split('data-section="ai-team-map"', 1)[1].split("</section>", 1)[0]
    assert (
        'data-node="investigation"' in team_map
        and "connected to your rules" in team_map
        and "Your people" in team_map
    )
    assert "Test reviewer" in team_map and "approved the case" in team_map
    assert "Nothing from the agents is waiting for a person." in team_map
    for layer in ("decision", "orchestration", "operations"):
        assert f'data-layer="{layer}"' in team_map
    assert "No AI agent" in team_map and "prepares payments" in team_map and "proposes fixes" in team_map


def test_the_overview_map_shows_work_waiting_for_a_person(engine: Engine, clock: FrozenClock) -> None:
    d, c = client(engine, clock)
    with c, engine.begin() as conn:
        issue_mandate(conn, clock, d.id, fixture_mandate(clock, d.id), KEY, actor=Actor.system("seed"))
    with c:
        p = run(engine, clock, d, "inv-canonical-18500-usdc.txt")
        with engine.begin() as conn:  # stand-in for a proposal the agent could not finish
            conn.execute(
                text("UPDATE agent_calls SET status='needs_human' WHERE org_id=:o AND id=:i"),
                {"o": d.id, "i": p.id},
            )
        login(c, d.org.users[Role.REVIEWER])
        team_map = c.get("/console/").text.split('data-section="ai-team-map"', 1)[1].split("</section>", 1)[0]
    assert f'data-waiting="{p.id}"' in team_map and "ai-link-wait" in team_map
    assert "Proposed 18,500.00 USDC to cpt_bluefin" in team_map


def test_reconciliation_fixes_show_the_payments_leads_decision(engine: Engine, clock: FrozenClock) -> None:
    ro = build_500(engine, clock)
    reconcile(engine, clock, ro.id)
    with engine.connect() as conn:
        breaks = {
            r.subject_key: r.id
            for r in conn.execute(
                text("SELECT id, subject_key FROM recon_breaks WHERE org_id=:o"), {"o": ro.id}
            )
        }
    pl = Actor(ro.d.org.users[Role.PAYMENTS_LEAD], Role.PAYMENTS_LEAD.value)
    approve_fix(
        engine,
        clock,
        org_id=ro.id,
        break_id=breaks[ro.designed["unallocated_inbound"]],
        actor=pl,
        reason="ok",
    )
    reject_fix(
        engine,
        clock,
        org_id=ro.id,
        break_id=breaks[ro.designed["payout_missing_on_rail"]],
        actor=pl,
        reason="no",
    )
    with engine.connect() as conn:
        team = {m.profile.kind: m for m in ai_team(conn, ro.id, clock.now(), daily_token_budget=1000)}
    rec = team["reconciliation"]
    assert rec.total >= 3 and (rec.accepted, rec.rejected) == (1, 1)
    said = [(x.who, x.what) for a in rec.activity for x in a.interactions]
    assert ("Test payments_lead", "approved and applied the fix") in said
    assert ("Test payments_lead", "rejected the fix") in said
    assert team["instruction"].total == 0 and team["instruction"].activity == []


def test_a_dashboard_member_reaches_the_ai_team_without_demo_links(
    engine: Engine, clock: FrozenClock
) -> None:
    from detent.dashboard import access
    from test_console_members import _org, _web
    from test_dashboard_access import PASSWORD, _email

    with engine.begin() as conn:
        staff = access.create_staff(
            conn, clock, email=_email("staff"), display_name="Staff", password=PASSWORD
        )
    owner = _org(engine, clock, staff)
    c: TestClient = _web(engine, clock, owner)
    home = c.get("/dashboard/").text
    assert 'href="/console/agents"' in home and "AI team" in home
    moved = c.get("/dashboard/ai-team", follow_redirects=False)
    assert (moved.status_code, moved.headers["location"]) == (303, "/console/agents")
    page = c.get("/console/agents")
    assert page.status_code == 200 and "Your AI team" in page.text
    assert "/console/invoices/" not in page.text  # the invoice drop is demo-only (DSH-09)
