"""P3 group 2: every guide runs as written against a sandbox organisation (DOC-03), and the reference's "try it"
reaches only the sandbox (DOC-05).

Request bodies are read from the guide pages themselves, so a page can't drift from the API. A sandbox
organisation comes with the fictional accounts-payable agent's mandate and travel-rule originator details.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import make_settings
from detent.api.app import create_app
from detent.api.auth import issue_key
from detent.clock import FrozenClock
from detent.dashboard import access
from detent.dashboard.access import Member
from detent.domain.roles import Role
from detent.runtime import Runtime
from detent.worker.loop import Worker
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from test_dashboard_access import PASSWORD, _email, sign_in

pytestmark = pytest.mark.db

DOCS = Path(__file__).resolve().parents[4] / "docs"
GUIDES = DOCS / "guides"
PEPPER = "test-pepper-abcdef123456"
S = make_settings(
    "org_detent",
    api_key_pepper=SecretStr(PEPPER),
    mandate_signing_key_demo=SecretStr("test-mandate-key-0123456789abcdef"),
)
SAME = {"Origin": "http://testserver"}
SCOPES = ["read", "intents:create", "exceptions:approve", "admin"]


def block(page: str, tag: str) -> Any:
    m = re.search(r"```" + re.escape(tag) + r"\n(.*?)```", (GUIDES / page).read_text(), re.S)
    assert m, f"{page}: no ```{tag} block"
    return json.loads(m.group(1))


@dataclass
class Org:
    id: str
    owner: Member
    lead: Member
    compliance: Member

    def key(
        self, m: Member, engine: Engine, clock: FrozenClock, scopes: list[str] = SCOPES
    ) -> dict[str, str]:
        with engine.begin() as conn:
            return {"Authorization": "Bearer " + issue_key(conn, clock, self.id, m.id, scopes, PEPPER)}


@pytest.fixture
def org(engine: Engine, clock: FrozenClock) -> Org:
    with engine.begin() as conn:
        staff = access.create_staff(
            conn, clock, email=_email("staff"), display_name="Staff", password=PASSWORD
        )
        org_id, token = access.create_organisation(
            conn, clock, S, staff=staff, kind="client", name="Fictional Payouts Ltd", owner_email=_email("o"),
            kyb_reference="KYB-2026-0042", kyb_approved_on=clock.now().date(),
        )  # fmt: skip
        owner = access.accept_invite(conn, clock, token=token, display_name="Ada Owner", password=PASSWORD)
        people = []
        for role, name in ((Role.PAYMENTS_LEAD, "Lee Lead"), (Role.COMPLIANCE_LEAD, "Cam Compliance")):
            t = access.invite(conn, clock, S, org_id=org_id, email=_email(role.value), role=role, by=owner)
            people.append(access.accept_invite(conn, clock, token=t, display_name=name, password=PASSWORD))
    return Org(org_id, owner, *people)


@pytest.fixture
def api(engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    with TestClient(create_app(S, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def auto(engine: Engine, org: Org) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE organisations SET mode='auto' WHERE org_id=:o"), {"o": org.id})


def drain(engine: Engine, clock: FrozenClock, org_id: str, *, seconds: int = 0, rounds: int = 1) -> None:
    w = Worker(Runtime(S, engine, clock), worker_id="test-guides", org_id=org_id)
    for _ in range(rounds):
        while w.run_one():
            pass
        clock.advance(timedelta(seconds=seconds))
    while w.run_one():
        pass


def create(api: TestClient, path: str, auth: dict[str, str], body: Any) -> Any:
    r = api.post(path, json=body, headers={**auth, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 201, r.text
    return r.json()


def status(api: TestClient, auth: dict[str, str], pid: str) -> str:
    return str(api.get(f"/v1/payment_intents/{pid}", headers=auth).json()["status"])


def reasons(body: Any) -> set[str]:
    return {c["reason"] for c in body["decision"]["checks"] if c.get("reason")}


# ------------------------------------------------------------------------------------------------ guides
def test_the_agent_invoice_guide_runs_as_written(
    api: TestClient, engine: Engine, clock: FrozenClock, org: Org
) -> None:
    auto(engine, org)
    agent = org.key(org.owner, engine, clock, ["intents:create"])  # "only the intents:create scope"
    reviewer = org.key(org.lead, engine, clock)
    [mandate] = api.get("/v1/mandates", headers=reviewer).json()["data"]
    assert mandate["mandate_id"] == "mnd_demo_ap_agent" and mandate["scope"]["payees"] == [
        "cpt_bluefin",
        "cpt_harbor",
    ]
    assert mandate["scope"]["max_per_payment"] == {"amount": "20000.00", "currency": "USDC"}

    got = create(
        api, "/v1/payment_intents", agent, block("agent-supplier-invoice.mdx", "json agent-intent.json")
    )
    shown = block("agent-supplier-invoice.mdx", "json escalated")
    assert (got["status"], got["decision"]["outcome"]) == (shown["status"], shown["decision"]["outcome"])
    checks = {c["check"]: (c["result"], c.get("reason")) for c in got["decision"]["checks"]}
    for c in shown["decision"]["checks"]:
        assert checks[c["check"]] == (c["result"], c.get("reason")), c
    assert reasons(got) == {"ABOVE_AUTO_LIMIT", "FIRST_PAYMENT"}  # nothing else, travel rule included
    assert got["exception"]["owner"] and got["exception"]["deadline_at"]

    case = got["exception"]["id"]
    ok = api.post(f"/v1/exceptions/{case}/approve", json={"reason": "Invoice checked"}, headers=reviewer)
    assert ok.status_code == 200 and ok.json()["payment_status"] == "READY", ok.text
    drain(engine, clock, org.id)
    assert status(api, reviewer, got["id"]) == "CONFIRMED"
    assert api.get("/v1/mandates", headers=reviewer).json()["data"][0]["used"] == "18500.00 USDC"

    over = create(
        api, "/v1/payment_intents", agent, block("agent-supplier-invoice.mdx", "json over-mandate.json")
    )
    assert over["status"] == "BLOCKED" and reasons(over) == {"MANDATE_AMOUNT_EXCEEDED"}


def test_the_approval_guide_holds(api: TestClient, engine: Engine, clock: FrozenClock, org: Org) -> None:
    auto(engine, org)
    platform, reviewer = org.key(org.owner, engine, clock), org.key(org.lead, engine, clock)
    body = {**block("agent-supplier-invoice.mdx", "json agent-intent.json"), "source": "platform"}
    body.pop("mandate_id")
    first = create(api, "/v1/payment_intents", platform, body)
    [case] = api.get("/v1/exceptions?status=open", headers=reviewer).json()["data"]
    assert case["payment_id"] == first["id"] and case["owner_id"] and case["deadline_at"]
    detail = api.get(f"/v1/exceptions/{case['id']}", headers=reviewer).json()
    assert list(detail).index("raw_facts") < list(detail).index("rule_hits")

    reason = block("approve-escalations.mdx", "json approve.json")
    own = org.key(org.lead, engine, clock)
    mine = create(api, "/v1/payment_intents", own, {**body, "reference": "INV-2"})
    selfish = api.post(f"/v1/exceptions/{mine['exception']['id']}/approve", json=reason, headers=own)
    assert selfish.status_code == 403  # "the member who created a payment can't approve it"

    ok = api.post(f"/v1/exceptions/{case['id']}/approve", json=reason, headers=reviewer).json()
    assert ok["payment_status"] == "READY" and ok["new_case_id"] is None
    rejected = api.post(f"/v1/exceptions/{mine['exception']['id']}/reject", json=reason, headers=platform)
    assert rejected.status_code == 403  # the owner may not approve or reject
    with engine.begin() as conn:
        t = access.invite(
            conn, clock, S, org_id=org.id, email=_email("rev"), role=Role.REVIEWER, by=org.owner
        )
        rev = access.accept_invite(conn, clock, token=t, display_name="Rae Reviewer", password=PASSWORD)
    done = api.post(
        f"/v1/exceptions/{mine['exception']['id']}/reject", json=reason, headers=org.key(rev, engine, clock)
    )
    assert done.status_code == 200 and done.json()["payment_status"] == "REJECTED"


def test_the_kill_switch_guide_holds(api: TestClient, engine: Engine, clock: FrozenClock, org: Org) -> None:
    auto(engine, org)
    lead, owner = org.key(org.lead, engine, clock), org.key(org.owner, engine, clock)
    for other in (owner, org.key(org.compliance, engine, clock)):
        assert api.post("/v1/kill_switch", headers=other).status_code == 403
    assert api.post("/v1/kill_switch", headers=lead).json() == block("kill-switch.mdx", "json engaged")
    held = create(api, "/v1/payment_intents", owner, block("handle-unknown.mdx", "json unknown.json")
                  | {"amount": {"amount": "50.00", "currency": "USDC"}})  # fmt: skip
    drain(engine, clock, org.id)
    assert status(api, owner, held["id"]) == "HELD"
    assert api.delete("/v1/kill_switch", headers=org.key(org.compliance, engine, clock)).status_code == 403
    assert api.delete("/v1/kill_switch", headers=lead).json() == block("kill-switch.mdx", "json released")
    drain(engine, clock, org.id)
    assert status(api, owner, held["id"]) == "CONFIRMED"


def test_the_unknown_guide_holds(api: TestClient, engine: Engine, clock: FrozenClock, org: Org) -> None:
    auto(engine, org)
    auth = org.key(org.owner, engine, clock)
    p = create(api, "/v1/payment_intents", auth, block("handle-unknown.mdx", "json unknown.json"))
    drain(engine, clock, org.id)
    assert status(api, auth, p["id"]) == "UNKNOWN"
    drain(engine, clock, org.id, seconds=20, rounds=4)
    done = api.get(f"/v1/payment_intents/{p['id']}", headers=auth).json()
    assert done["status"] == "CONFIRMED" and len(done["attempts"]) == 1


def test_the_deposit_guide_holds(api: TestClient, engine: Engine, clock: FrozenClock, org: Org) -> None:
    auth = org.key(org.owner, engine, clock)
    got = create(api, "/v1/deposit_intents", auth, block("credit-deposits.mdx", "json deposit.json"))
    shown = block("credit-deposits.mdx", "json deposit-response")
    assert (got["object"], got["status"]) == (shown["object"], shown["status"])
    assert {k: got["instructions"][k] for k in shown["instructions"]} == shown["instructions"]
    assert got["instructions"]["address"].startswith("0x") and got["credits"] == []
    assert (clock.now() + timedelta(days=7)).isoformat().startswith(got["expires_at"][:10])
    again = api.get(f"/v1/deposit_intents/{got['id']}", headers=auth).json()
    assert again["id"] == got["id"] and again["credits"] == []


def test_the_shadow_to_auto_guide_holds(
    api: TestClient, engine: Engine, clock: FrozenClock, org: Org
) -> None:
    auth = org.key(org.owner, engine, clock)
    body = block("handle-unknown.mdx", "json unknown.json") | {
        "amount": {"amount": "50.00", "currency": "USDC"}
    }
    shadowed = create(api, "/v1/payment_intents", auth, body)
    assert shadowed["status"] == "SHADOWED"
    listed = api.get("/v1/payment_intents?status=SHADOWED", headers=auth).json()["data"]
    assert [p["id"] for p in listed] == [shadowed["id"]] and listed[0]["decision"]["checks"]

    def console(m: Member) -> TestClient:
        c = TestClient(create_app(S, engine=engine, clock=clock, configure_logging=False))
        assert sign_in(c, m.email).status_code == 303
        return c

    lead, compliance = console(org.lead), console(org.compliance)
    assert lead.get("/console/settings").status_code == 200
    lead.post("/console/settings/mode/propose", data={"to_mode": "auto", "reason": "Shadow run reviewed"},
              headers=SAME)  # fmt: skip
    with engine.connect() as conn:
        change = conn.execute(
            text("SELECT id FROM mode_changes WHERE org_id=:o AND status='proposed'"), {"o": org.id}
        ).scalar_one()
    lead.post(f"/console/settings/mode/{change}/approve", headers=SAME)  # one person can't do both
    assert create(api, "/v1/payment_intents", auth, body)["status"] == "SHADOWED"
    compliance.post(f"/console/settings/mode/{change}/approve", headers=SAME)
    assert (
        create(api, "/v1/payment_intents", auth, body)["status"]
        == block("shadow-to-auto.mdx", "json auto")["status"]
    )


# ------------------------------------------------------------------------------------------------ DOC-05
def test_try_it_reaches_only_the_sandbox() -> None:
    spec = json.loads((DOCS / "api" / "openapi.json").read_text())
    for server in spec["servers"]:
        url = server["url"]
        assert url.startswith("http://localhost") or "sandbox" in url, url
        assert "variables" not in server  # the base URL can't be pointed anywhere else
    assert spec["security"] == [{"bearer": []}]
    assert spec["components"]["securitySchemes"]["bearer"] == {**spec["components"]["securitySchemes"]["bearer"],
                                                                "type": "http", "scheme": "bearer"}  # fmt: skip
    config = json.loads((DOCS / "docs.json").read_text())
    assert config["api"]["playground"]["display"] == "interactive"
    assert config["navbar"]["primary"]["label"] == "Request sandbox access"
    page = (DOCS / "tools" / "try-it.mdx").read_text()
    assert "Request sandbox access" in page and "sk_live_" in page
