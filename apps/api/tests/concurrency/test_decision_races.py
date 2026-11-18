"""INT-02 and POL-04 under real parallel requests against Postgres."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import make_settings
from decision_helpers import PEPPER, payout, setup_decision_org
from detent.api.app import create_app
from detent.clock import FrozenClock
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}


def test_parallel_requests_with_one_key_create_one_intent(engine: Engine, clock: FrozenClock) -> None:
    d = setup_decision_org(engine, clock)
    app = create_app(
        make_settings(d.id, api_key_pepper=SecretStr(PEPPER)),
        engine=engine,
        clock=clock,
        configure_logging=False,
    )
    body = payout("cpt_harbor", "100.00", "EUR", HARBOR)

    def one(_: int) -> tuple[int, str]:
        with TestClient(app) as c:
            r = c.post("/v1/payment_intents", json=body, headers={**d.auth(), "Idempotency-Key": "same"})
            return r.status_code, r.json()["id"]

    with ThreadPoolExecutor(10) as ex:
        results = list(ex.map(one, range(10)))
    assert {s for s, _ in results} == {201}
    assert len({pid for _, pid in results}) == 1
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM payment_intents WHERE org_id=:o"), {"o": d.id}).scalar() == 1
        )


def test_parallel_intents_at_the_daily_cap_never_all_execute(engine: Engine, clock: FrozenClock) -> None:
    # Harbor's per-counterparty EUR cap is 10,000.00. Twenty 1,000.00 payments race; at most ten fit.
    d = setup_decision_org(engine, clock)
    app = create_app(
        make_settings(d.id, api_key_pepper=SecretStr(PEPPER)),
        engine=engine,
        clock=clock,
        configure_logging=False,
    )

    def one(i: int) -> str:
        with TestClient(app) as c:
            r = c.post(
                "/v1/payment_intents",
                json=payout("cpt_harbor", "1000.00", "EUR", HARBOR),
                headers={**d.auth(), "Idempotency-Key": f"cap-{i}"},
            )
            assert r.status_code == 201, r.text
            return str(r.json()["decision"]["outcome"])

    with ThreadPoolExecutor(20) as ex:
        outcomes = list(ex.map(one, range(20)))
    assert outcomes.count("EXECUTE") == 10
    assert outcomes.count("ESCALATE") == 10
    with engine.connect() as c:
        used = c.execute(
            text("SELECT amount_minor FROM counters WHERE org_id=:o AND scope='counterparty:cpt_harbor:EUR'"),
            {"o": d.id},
        ).scalar()
    assert used == 10_000_00
