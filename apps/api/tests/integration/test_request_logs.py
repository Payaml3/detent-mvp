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
    assert data == []
