"""API-06: request logs, per organisation, metadata only, 30 days."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from conftest import make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.clock import FrozenClock
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


@pytest.fixture
def dorg(engine: Engine, clock: FrozenClock) -> DecisionOrg:
    return setup_decision_org(engine, clock)


@pytest.fixture
def api(dorg: DecisionOrg, engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    s = make_settings(dorg.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def test_calls_are_logged_with_key_payment_and_no_body(api: TestClient, dorg: DecisionOrg) -> None:
    dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": dorg.wallets["WALLET_BLUEFIN_BASE"]}
    idem = str(uuid.uuid4())
    body = payout("cpt_bluefin", "18500.00", "USDC", dest, reference="SECRET-REF-123")
    r = api.post("/v1/payment_intents", json=body, headers={**dorg.auth(), "Idempotency-Key": idem})
    pid = r.json()["id"]
    api.get(f"/v1/payment_intents/{pid}?x=1", headers=dorg.auth())
    logs = api.get("/v1/request_logs", headers=dorg.auth()).json()
    assert "SECRET-REF-123" not in str(logs)
    rows = logs["data"]
    get = next(x for x in rows if x["method"] == "GET" and x["payment_id"] == pid)
    assert get["status"] == 200 and get["path"] == f"/v1/payment_intents/{pid}" and get["request_id"]
    post = next(x for x in rows if x["method"] == "POST")
    assert post["idempotency_key"] == idem and post["status"] == 201
    only = api.get(f"/v1/request_logs?payment_id={pid}", headers=dorg.auth()).json()["data"]
    assert only and all(x["payment_id"] == pid for x in only)


def test_unauthenticated_calls_are_not_logged_and_entries_expire(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    api.get("/v1/payment_intents")  # no key: 401, no organisation to attach it to
    api.get("/v1/payment_intents", headers=dorg.auth())
    with engine.connect() as c:
        n = c.execute(text("SELECT count(*) FROM request_logs WHERE org_id=:o"), {"o": dorg.id}).scalar()
    assert n == 1
    clock.advance(timedelta(days=31))
    data = api.get("/v1/request_logs", headers=dorg.auth()).json()["data"]
    assert [x for x in data if x["path"] == "/v1/payment_intents"] == []  # past the window: never shown


def test_the_retention_sweep_deletes_only_old_rows(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    from detent.db.retention import purge_request_logs

    api.get("/v1/payment_intents", headers=dorg.auth())
    clock.advance(timedelta(days=31))
    api.get("/v1/payment_intents?status=CONFIRMED", headers=dorg.auth())
    assert purge_request_logs(engine, clock) >= 1
    with engine.connect() as c:
        rows = c.execute(text("SELECT at FROM request_logs WHERE org_id=:o"), {"o": dorg.id}).all()
    assert len(rows) == 1 and rows[0].at == clock.now()


def test_an_organisation_sees_only_its_own_logs(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    other = setup_decision_org(engine, clock)
    api.get("/v1/payment_intents", headers=other.auth())
    api.get("/v1/payment_intents", headers=dorg.auth())
    mine = api.get("/v1/request_logs", headers=dorg.auth()).json()["data"]
    theirs = api.get("/v1/request_logs", headers=other.auth()).json()["data"]
    assert mine and theirs
    assert {x["id"] for x in mine}.isdisjoint({x["id"] for x in theirs})
    with engine.connect() as c:
        keys = c.execute(text("SELECT id FROM api_keys WHERE org_id=:o"), {"o": dorg.id}).scalars().all()
    assert all(x["key_id"] in keys for x in mine)


def test_logs_page_with_starting_after_and_filter_by_status(api: TestClient, dorg: DecisionOrg) -> None:
    for _ in range(3):
        api.get("/v1/payment_intents", headers=dorg.auth())
    api.get("/v1/payment_intents/pay_nope", headers=dorg.auth())  # 404
    first = api.get("/v1/request_logs?limit=2", headers=dorg.auth()).json()
    assert len(first["data"]) == 2 and first["has_more"] is True
    nxt = api.get(f"/v1/request_logs?limit=2&starting_after={first['next_cursor']}", headers=dorg.auth())
    ids = [x["id"] for x in first["data"]] + [x["id"] for x in nxt.json()["data"]]
    assert ids == sorted(ids, reverse=True) and len(set(ids)) == len(ids)
    missing = api.get("/v1/request_logs?status=404", headers=dorg.auth()).json()["data"]
    assert [x["path"] for x in missing] == ["/v1/payment_intents/pay_nope"]
