"""DEM-01 (fictional demo platform, idempotent and resettable seed), CON-09 (reset demo data as a new data
generation, D-08 applied to the demo), FND-07 (/healthz reports each check; the footer states the regions)."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Iterator

import pytest
import yaml
from conftest import CREATED_ORGS, FAKE_TEST, login, make_settings
from decision_helpers import PEPPER
from detent.api.app import create_app
from detent.api.auth import hash_key
from detent.audit.log import Actor, verify_chain
from detent.clock import FrozenClock
from detent.demo.generations import (
    ResetRefused,
    active_demo_org,
    agent_key_for,
    demo_user_id,
    reset_demo,
)
from detent.runtime import Runtime, build_runtime
from detent.seed import seed_demo
from detent.settings import REPO_ROOT, Settings
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, text

pytestmark = pytest.mark.db

MANDATE_KEY = SecretStr("test-mandate-key-0123456789abcdef")
FIXTURE = yaml.safe_load((REPO_ROOT / "fixtures" / "counterparties.yaml").read_text())


@pytest.fixture
def demo(engine: Engine, clock: FrozenClock) -> Runtime:
    """A fresh demo organisation seeded from the fixtures (its own ID, so tests never share one)."""
    org = f"org_t{secrets.token_hex(6)}"
    CREATED_ORGS.append(org)
    s = make_settings(
        org,
        api_key_pepper=SecretStr(PEPPER),
        mandate_signing_key_demo=MANDATE_KEY,
        agent_api_key=SecretStr(FAKE_TEST + "agent" + secrets.token_hex(16)),
        agent_llm="recorded",
    )
    rt = build_runtime(s, engine=engine, clock=clock)
    seed_demo(rt, org_id=org)
    return rt


def _pl(rt: Runtime, org: str) -> Actor:
    return Actor(demo_user_id("usr_pl", org), "payments_lead")


def _count(engine: Engine, table: str, org: str) -> int:
    with engine.connect() as c:
        return int(c.execute(text(f"SELECT count(*) FROM {table} WHERE org_id=:o"), {"o": org}).scalar_one())


def test_seed_is_fictional_and_idempotent(demo: Runtime) -> None:
    org = demo.settings.demo_org_id
    before = {
        t: _count(demo.engine, t, org)
        for t in ("users", "counterparties", "destinations", "rails", "audit_events")
    }
    assert seed_demo(demo, org_id=org) == {"orgs_added": 0, "users_added": 0}
    after = {t: _count(demo.engine, t, org) for t in before}
    assert after == before  # a second run changes nothing
    with demo.engine.connect() as c:
        names = c.execute(text("SELECT name FROM counterparties WHERE org_id=:o"), {"o": org}).scalars().all()
        org_name = c.execute(text("SELECT name FROM organisations WHERE org_id=:o"), {"o": org}).scalar_one()
        users = c.execute(text("SELECT display_name FROM users WHERE org_id=:o"), {"o": org}).scalars().all()
    assert names and all(n.endswith("(fictional)") for n in names)  # every name labelled fictional
    assert org_name.endswith("(fictional)")
    assert len(users) == len(FIXTURE["users"])
    assert all(c["contact_email"].endswith(".invalid") for c in FIXTURE["counterparties"])


def test_reset_starts_a_new_generation_and_deletes_nothing(demo: Runtime) -> None:
    old = demo.settings.demo_org_id
    with demo.engine.begin() as c:
        c.execute(text("UPDATE demo_clock SET offset_seconds = 7200 WHERE org_id=:o"), {"o": old})
    events_before = _count(demo.engine, "audit_events", old)

    r = reset_demo(demo, actor=_pl(demo, old))

    assert (r.previous_org_id, r.generation) == (old, 2) and r.org_id == f"{old}_g2"
    assert active_demo_org(demo.engine, demo.settings) == r.org_id
    with demo.engine.connect() as c:
        engaged = c.execute(text("SELECT engaged FROM kill_switch WHERE org_id=:o"), {"o": old}).scalar_one()
        new_engaged = c.execute(
            text("SELECT engaged FROM kill_switch WHERE org_id=:o"), {"o": r.org_id}
        ).scalar_one()
        offset = c.execute(
            text("SELECT offset_seconds FROM demo_clock WHERE org_id=:o"), {"o": r.org_id}
        ).scalar_one()
        users = c.execute(text("SELECT id FROM users WHERE org_id=:o"), {"o": r.org_id}).scalars().all()
        policy = c.execute(
            text("SELECT count(*) FROM policy_versions WHERE org_id=:o AND status='active'"), {"o": r.org_id}
        ).scalar_one()
        old_ok = verify_chain(c, old)
        new_ok = verify_chain(c, r.org_id)
    assert engaged is True and new_engaged is False  # the old generation can never send again
    assert offset == 7200  # the demo clock never runs backwards across a reset
    assert sorted(users) == sorted(demo_user_id(u["id"], r.org_id) for u in FIXTURE["users"])
    assert policy == 1
    assert _count(demo.engine, "counterparties", r.org_id) == len(FIXTURE["counterparties"])
    # Nothing was deleted: the old generation's audit log only grew (the kill switch, the reset notice).
    assert _count(demo.engine, "audit_events", old) == events_before + 2
    assert old_ok.ok and new_ok.ok

    r3 = reset_demo(demo, actor=_pl(demo, r.org_id))
    assert (r3.generation, r3.org_id) == (3, f"{old}_g3")
    with demo.engine.connect() as c:
        gens = c.execute(
            text("SELECT generation, org_id FROM demo_generations WHERE base_org_id=:b ORDER BY 1"),
            {"b": old},
        ).all()
    assert [tuple(g) for g in gens] == [(1, old), (2, f"{old}_g2"), (3, f"{old}_g3")]


def test_generations_are_append_only(demo: Runtime) -> None:
    old = demo.settings.demo_org_id
    reset_demo(demo, actor=_pl(demo, old))
    for sql in (
        "UPDATE demo_generations SET org_id = org_id WHERE base_org_id=:b",
        "DELETE FROM demo_generations WHERE base_org_id=:b",
    ):
        with pytest.raises(Exception, match="append-only"), demo.engine.begin() as c:
            c.execute(text(sql), {"b": old})


def test_only_the_payments_lead_can_reset(demo: Runtime) -> None:
    org = demo.settings.demo_org_id
    with pytest.raises(ResetRefused):
        reset_demo(demo, actor=Actor(demo_user_id("usr_rv", org), "reviewer"))
    assert active_demo_org(demo.engine, demo.settings) == org


def test_reset_is_refused_while_an_attempt_is_in_flight(demo: Runtime) -> None:
    """Every generation sends from the same test wallet: an UNKNOWN attempt must resolve first (inv. 3)."""
    from decision_helpers import payout
    from detent.intents.service import IntentRequest, submit_intent
    from detent.policy.screening import MockScreening

    org = demo.settings.demo_org_id
    _, body = submit_intent(
        demo.engine,
        demo.clock,
        org_id=org,
        actor_id="usr_api",
        idempotency_key="in-flight",
        request=IntentRequest.model_validate(
            payout(
                "cpt_kestrel",
                "40.00",
                "GBP",
                {"kind": "bank_account", "network": "banksim-fps", "destination_id": "dst_kestrel_acct"},
            )
        ),
        decision_only=False,
        screening=MockScreening.from_fixture(),
    )
    assert body["status"] == "READY"
    with demo.engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO attempts (id, org_id, payment_id, attempt_no, rail_id, status, idempotency_key, "
                "created_at) VALUES ('att_demo_inflight_' || :o, :o, :p, 1, 'banksim-fps', 'UNKNOWN', :p, now())"
            ),
            {"o": org, "p": body["id"]},
        )
    with pytest.raises(ResetRefused, match="in flight"):
        reset_demo(demo, actor=_pl(demo, org))
    assert active_demo_org(demo.engine, demo.settings) == org


def _ready_payout(demo: Runtime, key: str) -> str:
    from decision_helpers import payout
    from detent.intents.service import IntentRequest, submit_intent
    from detent.policy.screening import MockScreening

    _, body = submit_intent(
        demo.engine,
        demo.clock,
        org_id=demo.settings.demo_org_id,
        actor_id="usr_api",
        idempotency_key=key,
        request=IntentRequest.model_validate(
            payout(
                "cpt_kestrel",
                "40.00",
                "GBP",
                {"kind": "bank_account", "network": "banksim-fps", "destination_id": "dst_kestrel_acct"},
            )
        ),
        decision_only=False,
        screening=MockScreening.from_fixture(),
    )
    assert body["status"] == "READY"
    return str(body["id"])


def _insert_attempt(c: Connection, org: str, pid: str) -> None:
    c.execute(
        text(
            "INSERT INTO attempts (id, org_id, payment_id, attempt_no, rail_id, status, idempotency_key, "
            "created_at) VALUES ('att_demo_race_' || :o, :o, :p, 1, 'banksim-fps', 'UNKNOWN', :p, now())"
        ),
        {"o": org, "p": pid},
    )


def _engaged(demo: Runtime, org: str) -> bool:
    with demo.engine.connect() as c:
        return bool(
            c.execute(text("SELECT engaged FROM kill_switch WHERE org_id=:o"), {"o": org}).scalar_one()
        )


def test_a_refused_reset_leaves_the_kill_switch_off(demo: Runtime) -> None:
    """The check and the engage are one transaction: refusing a reset changes nothing."""
    org = demo.settings.demo_org_id
    pid = _ready_payout(demo, "refused-reset")
    with demo.engine.begin() as c:
        _insert_attempt(c, org, pid)
    with pytest.raises(ResetRefused, match="in flight"):
        reset_demo(demo, actor=_pl(demo, org))
    assert not _engaged(demo, org)
    with demo.engine.connect() as c:
        status = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org, "p": pid}
        ).scalar_one()
    assert status == "READY"  # not held by a kill switch that never engaged


def test_reset_waits_for_a_send_holding_the_kill_switch_lock(demo: Runtime) -> None:
    """A sender reads the kill switch FOR SHARE in the transaction that creates its attempt. A reset that
    starts meanwhile waits for it, then sees the new attempt and refuses (no attempt slips between the
    in-flight check and the engage)."""
    org = demo.settings.demo_org_id
    pid = _ready_payout(demo, "race")
    outcome: list[BaseException | None] = []

    def do_reset() -> None:
        try:
            reset_demo(demo, actor=_pl(demo, org))
            outcome.append(None)
        except BaseException as exc:  # the test inspects it
            outcome.append(exc)

    with demo.engine.begin() as sender:
        engaged = sender.execute(
            text("SELECT engaged FROM kill_switch WHERE org_id=:o FOR SHARE"), {"o": org}
        ).scalar_one()
        assert engaged is False
        t = threading.Thread(target=do_reset)
        t.start()
        t.join(timeout=1.0)
        assert t.is_alive(), "the reset must wait for the sender's lock"
        _insert_attempt(sender, org, pid)
    t.join(timeout=10)
    assert not t.is_alive()
    assert isinstance(outcome[0], ResetRefused)
    assert active_demo_org(demo.engine, demo.settings) == org
    assert not _engaged(demo, org)


def test_each_generation_gets_its_own_agent_key(demo: Runtime) -> None:
    old = demo.settings.demo_org_id
    r = reset_demo(demo, actor=_pl(demo, old))
    k1, k2 = agent_key_for(demo.settings, old), agent_key_for(demo.settings, r.org_id)
    assert k1 is not None and k2 is not None and k1.get_secret_value() != k2.get_secret_value()
    assert k2.get_secret_value().startswith(FAKE_TEST)
    with demo.engine.connect() as c:
        bound = c.execute(
            text("SELECT org_id, mandate_id FROM api_keys WHERE hash=:h AND org_id=:o"),
            {"h": hash_key(k2.get_secret_value(), PEPPER), "o": r.org_id},
        ).one()
    assert tuple(bound) == (r.org_id, "mnd_demo_ap_agent")


@pytest.fixture
def console(demo: Runtime) -> Iterator[TestClient]:
    s: Settings = demo.settings.model_copy(
        update={"hosting_region": "Frankfurt (EU Central)", "database_region": "AWS eu-central-1"}
    )
    with TestClient(create_app(s, engine=demo.engine, clock=demo.clock, configure_logging=False)) as c:
        yield c


def test_console_reset_switches_to_the_new_generation(console: TestClient, demo: Runtime) -> None:
    old = demo.settings.demo_org_id
    login(console, demo_user_id("usr_pl", old))
    page = console.get("/console/demo")
    assert (
        page.status_code == 200 and "Reset demo data" in page.text and "Frankfurt (EU Central)" in page.text
    )
    assert "AWS eu-central-1" in page.text  # FND-07: the footer states the regions
    r = console.post("/console/demo/run/reset", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/console/act-as"
    picker = console.get("/console/act-as").text
    new_pl, old_pl = demo_user_id("usr_pl", f"{old}_g2"), demo_user_id("usr_pl", old)
    assert f'"{new_pl}"' in picker and f'"{old_pl}"' not in picker
    login(console, demo_user_id("usr_rv", f"{old}_g2"))
    assert console.get("/console/demo").status_code == 200
    r = console.post("/console/demo/run/reset", follow_redirects=False)  # a reviewer may not reset
    assert "payments+lead" in r.headers["location"] or "payments%20lead" in r.headers["location"]
    assert active_demo_org(demo.engine, demo.settings) == f"{old}_g2"


def test_healthz_reports_database_and_both_chain_rpcs(console: TestClient) -> None:
    body = console.get("/healthz").json()
    assert body["checks"] == {
        "database": "ok",
        "base-sepolia": "not_configured",
        "eth-sepolia": "not_configured",
    }
    assert body["regions"] == {"hosting": "Frankfurt (EU Central)", "database": "AWS eu-central-1"}


def test_healthz_in_demo_mode_needs_both_chains(demo: Runtime) -> None:
    s = demo.settings.model_copy(
        update={"app_env": "demo", "base_sepolia_rpc_url": "http://127.0.0.1:9/", "eth_sepolia_rpc_url": None}
    )
    with TestClient(create_app(s, engine=demo.engine, clock=demo.clock, configure_logging=False)) as c:
        r = c.get("/healthz")
    assert r.status_code == 503
    assert r.json()["checks"]["base-sepolia"] == "unreachable"
    assert r.json()["checks"]["eth-sepolia"] == "not_configured"


def test_console_runs_a_scenario_once_per_generation(console: TestClient, demo: Runtime) -> None:
    org = demo.settings.demo_org_id
    login(console, demo_user_id("usr_rv", org))
    inv = console.get("/console/demo/invoice.txt")
    with demo.engine.connect() as c:
        wallet = c.execute(
            text("SELECT address FROM destinations WHERE org_id=:o AND id='dst_bluefin_base'"), {"o": org}
        ).scalar_one()
    assert inv.status_code == 200 and wallet.lower() in inv.text.lower() and "{{" not in inv.text
    r = console.post("/console/demo/run/invoice_18500", follow_redirects=False)
    assert r.status_code == 303 and "result=" in r.headers["location"]
    page = console.get("/console/demo").text
    assert "Open the proposal" in page and "Done" in page
    console.post("/console/demo/run/invoice_18500", follow_redirects=False)  # a second click changes nothing
    with demo.engine.connect() as c:
        runs = c.execute(
            text("SELECT count(*) FROM audit_events WHERE org_id=:o AND kind='demo.scenario_run'"), {"o": org}
        ).scalar_one()
        calls = c.execute(text("SELECT count(*) FROM agent_calls WHERE org_id=:o"), {"o": org}).scalar_one()
    assert (runs, calls) == (1, 1)


def test_scenario_runner_is_absent_in_the_public_sandbox(demo: Runtime) -> None:
    s = demo.settings.model_copy(update={"app_env": "sandbox"})
    app = create_app(s, engine=demo.engine, clock=demo.clock, configure_logging=False)
    with TestClient(app, base_url="https://testserver") as c:  # sandbox session cookies are HTTPS-only
        login(c, demo_user_id("usr_pl", demo.settings.demo_org_id))
        r = c.get("/console/demo", follow_redirects=False)
        assert r.status_code == 404, (r.status_code, r.headers.get("location"))
        assert c.post("/console/demo/run/reset", follow_redirects=False).status_code == 404
