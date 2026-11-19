"""CON-08: the rails screen shows each rail's network or currency, balance, pre-funded usage and last 20 attempts."""

from __future__ import annotations

import pytest
from conftest import login, make_settings
from decision_helpers import PEPPER, setup_decision_org
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.domain.money import Money
from detent.domain.roles import Role
from detent.rails.registry import install_rail
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


def test_rails_screen(engine: Engine, clock: FrozenClock) -> None:
    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        install_rail(
            c,
            d.id,
            rail_id="base-sepolia",
            kind="evm",
            network="base-sepolia",
            chain_id=84532,
            currency="USDC",
            prefunded_daily_limit=Money.parse("40000.00", "USDC"),
        )
        install_rail(
            c,
            d.id,
            rail_id="banksim-fps",
            kind="banksim",
            network="banksim-fps",
            currency="GBP",
            per_payment_limit=Money.parse("25000.00", "GBP"),
        )
        c.execute(
            text(
                "INSERT INTO counters (org_id, scope, period, currency, amount_minor, count) "
                "VALUES (:o, 'prefund:base-sepolia', :d, 'USDC', 10000000000, 3)"
            ),
            {"o": d.id, "d": clock.now().date().isoformat()},
        )
    app = create_app(
        make_settings(d.id, api_key_pepper=SecretStr(PEPPER)),
        engine=engine,
        clock=clock,
        configure_logging=False,
    )
    with TestClient(app) as client:
        login(client, d.org.users[Role.PAYMENTS_LEAD])
        html = client.get("/console/rails").text
    assert "base-sepolia" in html and "banksim-fps" in html and "GBP" in html
    assert "10000.00 of 40000.00 USDC (25%)" in html  # pre-funded limit usage today
    assert "Last 20 attempts" in html
    assert "balance unavailable" in html.lower()  # no adapter configured in this test: say so, never guess
