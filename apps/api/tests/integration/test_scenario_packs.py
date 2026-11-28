"""DEM-06: scenario packs for a payout platform, a crypto service provider and a marketplace, selectable on reset."""

from __future__ import annotations

import secrets

import pytest
from conftest import CREATED_ORGS, FAKE_TEST, login, make_settings
from decision_helpers import PEPPER
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.demo import packs
from detent.demo.generations import ResetRefused, demo_user_id, reset_demo
from detent.policy.schema import load_ruleset
from detent.runtime import Runtime, build_runtime
from detent.seed import seed_demo
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

OUTCOME_STATUS = {"EXECUTE": "READY", "ESCALATE": "ESCALATED", "BLOCK": "BLOCKED"}


@pytest.fixture
def demo(engine: Engine, clock: FrozenClock) -> Runtime:
    org = f"org_t{secrets.token_hex(6)}"
    CREATED_ORGS.append(org)
    s = make_settings(
        org, api_key_pepper=SecretStr(PEPPER), agent_api_key=SecretStr(FAKE_TEST + "agent" + secrets.token_hex(16)),
        agent_llm="recorded",
    )  # fmt: skip
    rt = build_runtime(s, engine=engine, clock=clock)
    seed_demo(rt, org_id=org)
    return rt


def lead(org: str) -> Actor:
    return Actor(demo_user_id("usr_pl", org), "payments_lead")


def test_three_packs_each_with_platform_counterparties_rules_and_a_batch() -> None:
    ids = [p.id for p in packs.packs()]
    assert ids == ["default", "crypto-service", "marketplace", "payout-platform"]
    for p in packs.packs()[1:]:
        assert p.data["platform"]["name"].endswith("(fictional)")
        assert all(c["name"].endswith("(fictional)") for c in p.data["counterparties"])
        assert all(c["contact_email"].endswith(".invalid") for c in p.data["counterparties"])
        assert 3 <= len(p.batch) <= 6 and {b["expect"] for b in p.batch} == {"EXECUTE", "ESCALATE", "BLOCK"}
        load_ruleset(packs.policy_text(p))  # the rules are a valid rule set
    crypto = load_ruleset(packs.policy_text(packs.load("crypto-service")))
    assert (
        crypto.checks.limits.auto_limit.get("USDC").to_decimal_str() == "25000.00"
    )  # the pack's own override


@pytest.mark.parametrize("pack_id", ["payout-platform", "crypto-service", "marketplace"])
def test_reset_into_a_pack_and_its_batch_decides_as_expected(demo: Runtime, pack_id: str) -> None:
    old = demo.settings.demo_org_id
    r = reset_demo(demo, actor=lead(old), pack=pack_id)
    pack = packs.load(pack_id)
    with demo.engine.connect() as c:
        name = c.execute(text("SELECT name FROM organisations WHERE org_id=:o"), {"o": r.org_id}).scalar_one()
        cpts = set(
            c.execute(text("SELECT id FROM counterparties WHERE org_id=:o"), {"o": r.org_id}).scalars()
        )
        assert packs.current_pack(c, r.org_id) == pack_id
    assert name == pack.data["platform"]["name"]
    assert cpts == {x["id"] for x in pack.data["counterparties"]}
    rows = packs.run_pack_batch(demo, r.org_id, lead(r.org_id), pack_id)
    for row in rows:
        assert row["status"] == OUTCOME_STATUS[row["expected"]], row
    again = packs.run_pack_batch(demo, r.org_id, lead(r.org_id), pack_id)
    assert [x["id"] for x in again] == [x["id"] for x in rows]  # idempotent


def test_unknown_pack_is_refused(demo: Runtime) -> None:
    with pytest.raises(ResetRefused, match="unknown scenario pack"):
        reset_demo(demo, actor=lead(demo.settings.demo_org_id), pack="casino")


def test_console_reset_with_a_pack(demo: Runtime) -> None:
    org = demo.settings.demo_org_id
    with TestClient(
        create_app(demo.settings, engine=demo.engine, clock=demo.clock, configure_logging=False)
    ) as api:
        login(api, demo_user_id("usr_pl", org))
        page = api.get("/console/demo").text
        assert "Scenario pack" in page and "Marketplace" in page and "Crypto service provider" in page
        r = api.post("/console/demo/reset", data={"pack": "marketplace"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/console/act-as"
        new = f"{org}_g2"
        login(api, demo_user_id("usr_pl", new))
        assert "Run this pack" in api.get("/console/demo").text
        done = api.post("/console/demo/pack-batch", follow_redirects=False)
        assert done.status_code == 303 and "mk1%20EXECUTE" in done.headers["location"]
