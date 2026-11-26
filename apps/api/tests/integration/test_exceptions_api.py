"""EXC-08: exceptions by API. The approve/reject rules (re-run, separation of duties, 409 on a second
approval, blocked payments) are tested over the API in test_cases.py; this file covers the lists,
the case detail and the scope."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from conftest import make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.api.auth import issue_key
from detent.clock import FrozenClock
from detent.domain.roles import Role
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine

pytestmark = pytest.mark.db


@pytest.fixture
def dorg(engine: Engine, clock: FrozenClock) -> DecisionOrg:
    return setup_decision_org(engine, clock)


@pytest.fixture
def api(dorg: DecisionOrg, engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    s = make_settings(dorg.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def _escalate(api: TestClient, d: DecisionOrg, ref: str = "INV-EX-1") -> str:
    dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": d.wallets["WALLET_BLUEFIN_BASE"]}
    r = api.post(
        "/v1/payment_intents",
        json=payout("cpt_bluefin", "18500.00", "USDC", dest, reference=ref),
        headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201 and r.json()["status"] == "ESCALATED", r.text
    return str(r.json()["id"])


def _key(engine: Engine, clock: FrozenClock, d: DecisionOrg, scopes: list[str]) -> dict[str, str]:
    with engine.begin() as c:
        k = issue_key(c, clock, d.id, d.org.users[Role.REVIEWER], scopes, PEPPER)
    return {"Authorization": f"Bearer {k}"}


def test_list_and_detail_show_raw_facts_first(api: TestClient, dorg: DecisionOrg) -> None:
    pid = _escalate(api, dorg)
    [case] = api.get("/v1/exceptions?status=open", headers=dorg.auth()).json()["data"]
    assert case["object"] == "exception" and case["payment_id"] == pid and case["status"] == "OPEN"
    assert set(case["reasons"]) >= {"FIRST_PAYMENT", "ABOVE_AUTO_LIMIT"} and case["owner_id"]
    detail = api.get(f"/v1/exceptions/{case['id']}", headers=dorg.auth()).json()
    keys = list(detail)
    assert keys.index("raw_facts") < keys.index("rule_hits") < keys.index("investigation")
    facts = detail["raw_facts"]
    assert facts["amount"] == {"amount": "18500.00", "currency": "USDC"}
    assert facts["destination"]["address"].lower() == dorg.wallets["WALLET_BLUEFIN_BASE"].lower()
    assert {h["result"] for h in detail["rule_hits"]} <= {"ESCALATE", "BLOCK"} and detail["rule_hits"]
    assert detail["history"] and detail["history"][0]["kind"] == "opened"


def test_filters_and_paging(api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock) -> None:
    ids = []
    for i in range(3):
        _escalate(api, dorg, ref=f"INV-EX-{i}")
        clock.advance(timedelta(seconds=1))
    rows = api.get("/v1/exceptions", headers=dorg.auth()).json()["data"]
    ids = [r["id"] for r in rows]
    assert len(ids) == 3
    first = api.get("/v1/exceptions?limit=2", headers=dorg.auth()).json()
    rest = api.get(f"/v1/exceptions?starting_after={first['next_cursor']}", headers=dorg.auth()).json()
    assert [r["id"] for r in first["data"]] + [r["id"] for r in rest["data"]] == ids
    assert api.get("/v1/exceptions?overdue=true", headers=dorg.auth()).json()["data"] == []
    clock.advance(timedelta(days=30))
    assert len(api.get("/v1/exceptions?overdue=true", headers=dorg.auth()).json()["data"]) == 3
    assert api.get("/v1/exceptions?status=resolved", headers=dorg.auth()).json()["data"] == []
    owner = rows[0]["owner_id"]
    mine = api.get(f"/v1/exceptions?owner={owner}", headers=dorg.auth()).json()["data"]
    assert mine and all(r["owner_id"] == owner for r in mine)


def test_approving_needs_the_approve_scope(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pid = _escalate(api, dorg)
    [case] = api.get("/v1/exceptions", headers=dorg.auth()).json()["data"]
    read_only = _key(engine, clock, dorg, ["read"])
    r = api.post(f"/v1/exceptions/{case['id']}/approve", json={"reason": "ok"}, headers=read_only)
    assert r.status_code == 403 and r.json()["error"]["code"] == "insufficient_scope"
    approver = _key(engine, clock, dorg, ["read", "exceptions:approve"])
    ok = api.post(
        f"/v1/exceptions/{case['id']}/approve", json={"reason": "checked the invoice"}, headers=approver
    )
    assert ok.status_code == 200 and ok.json()["payment_id"] == pid
    done = api.get(f"/v1/exceptions/{case['id']}", headers=dorg.auth()).json()
    assert done["status"] == "RESOLVED" and done["resolution"] == "approved"
    assert done["resolution_reason"] == "checked the invoice"


def test_cases_are_scoped_to_the_organisation(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    _escalate(api, dorg)
    [case] = api.get("/v1/exceptions", headers=dorg.auth()).json()["data"]
    other = setup_decision_org(engine, clock)
    assert api.get("/v1/exceptions", headers=other.auth()).json()["data"] == []
    assert api.get(f"/v1/exceptions/{case['id']}", headers=other.auth()).status_code == 404
    r = api.post(f"/v1/exceptions/{case['id']}/approve", json={"reason": "x"}, headers=other.auth())
    assert r.status_code == 404
