"""INT-04: counterparty registry with destination history and stats from confirmed payments."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import login
from decision_helpers import setup_decision_org
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.money import Money
from detent.domain.roles import Role
from detent.intents.registry import counterparty_stats, refresh_stats, update_destination
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


def test_fixture_counterparties_are_seeded(engine: Engine, clock: FrozenClock) -> None:
    d = setup_decision_org(engine, clock)
    with engine.connect() as c:
        rows = dict(
            c.execute(text("SELECT id, kyb_status FROM counterparties WHERE org_id=:o"), {"o": d.id}).all()
        )
        q = c.execute(
            text(
                "SELECT first_seen_at, last_changed_at FROM destinations WHERE org_id=:o AND id='dst_quill_acct'"
            ),
            {"o": d.id},
        ).one()
    assert rows == {
        "cpt_bluefin": "verified",
        "cpt_harbor": "verified",
        "cpt_quill": "verified",
        "cpt_nova": "pending",
        "cpt_flagged": "verified",
    }
    assert clock.now() - q.first_seen_at == timedelta(
        days=200
    ) and clock.now() - q.last_changed_at == timedelta(days=3)


def test_editing_a_destination_updates_last_changed_and_audits(engine: Engine, clock: FrozenClock) -> None:
    d = setup_decision_org(engine, clock)
    clock.advance(timedelta(hours=1))
    new = "0x3333333333333333333333333333333333333333"
    with engine.begin() as c:
        update_destination(
            c, clock, d.id, "dst_bluefin_base", address=new, actor=Actor("usr_x", "payments_lead")
        )
    with engine.connect() as c:
        row = c.execute(
            text(
                "SELECT address, last_changed_at, last_changed_by, first_seen_at FROM destinations "
                "WHERE org_id=:o AND id='dst_bluefin_base'"
            ),
            {"o": d.id},
        ).one()
        ev = c.execute(
            text("SELECT payload FROM audit_events WHERE org_id=:o AND kind='destination.changed'"),
            {"o": d.id},
        ).one()
    assert row.address == new and row.last_changed_at == clock.now() and row.last_changed_by == "usr_x"
    assert (
        ev.payload["old"]["address"] == d.wallets["WALLET_BLUEFIN_BASE"]
        and ev.payload["new"]["address"] == new
    )


def test_stats_are_computed_from_confirmed_payments(engine: Engine, clock: FrozenClock) -> None:
    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        for i, (amt, st) in enumerate(
            [(100, "CONFIRMED"), (300, "CONFIRMED"), (900, "CONFIRMED"), (50_000, "BLOCKED")]
        ):
            c.execute(
                text(
                    "INSERT INTO payment_intents (id, org_id, source, counterparty_id, amount_minor, currency, status, "
                    "idempotency_key, request_hash, created_at, updated_at) VALUES (:id, :o, 'platform', 'cpt_bluefin', "
                    ":a, 'USDC', :s, :k, 'h', :t, :t)"
                ),
                {
                    "id": f"pay_t{i}{d.id[5:]}",
                    "o": d.id,
                    "a": amt * 10**6,
                    "s": st,
                    "k": f"k{i}",
                    "t": clock.now(),
                },
            )
        refresh_stats(c, d.id, "cpt_bluefin")
        stats = counterparty_stats(c, d.id, "cpt_bluefin")
    assert stats.payment_count == 3 and stats.median == Money.parse("300.00", "USDC")


def test_destination_editable_in_console_by_payments_lead_only(engine: Engine, clock: FrozenClock) -> None:
    from conftest import make_settings
    from detent.api.app import create_app

    d = setup_decision_org(engine, clock)
    app = create_app(make_settings(d.id), engine=engine, clock=clock, configure_logging=False)
    new = "0x4444444444444444444444444444444444444444"
    with TestClient(app) as c:
        login(c, d.org.users[Role.REVIEWER])
        page = c.get("/console/counterparties")
        assert page.status_code == 200 and "Quill Studio Ltd (fictional)" in page.text
        r = c.post("/console/destinations/dst_bluefin_base", data={"address": new}, follow_redirects=False)
        assert r.status_code == 403
        login(c, d.org.users[Role.PAYMENTS_LEAD])
        r = c.post("/console/destinations/dst_bluefin_base", data={"address": new}, follow_redirects=False)
        assert r.status_code == 303
    with engine.connect() as c:
        assert (
            c.execute(
                text("SELECT address FROM destinations WHERE org_id=:o AND id='dst_bluefin_base'"),
                {"o": d.id},
            ).scalar()
            == new
        )


def test_changed_details_shows_the_old_address(engine: Engine, clock: FrozenClock) -> None:
    import uuid

    from conftest import make_settings
    from decision_helpers import PEPPER, payout
    from detent.api.app import create_app
    from pydantic import SecretStr

    d = setup_decision_org(engine, clock)
    old = d.wallets["WALLET_BLUEFIN_BASE"]
    new = "0x5555555555555555555555555555555555555555"
    with engine.begin() as c:
        update_destination(
            c, clock, d.id, "dst_bluefin_base", address=new, actor=Actor("usr_x", "payments_lead")
        )
    app = create_app(
        make_settings(d.id, api_key_pepper=SecretStr(PEPPER)),
        engine=engine,
        clock=clock,
        configure_logging=False,
    )
    with TestClient(app) as c:
        j = c.post(
            "/v1/payment_intents",
            headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())},
            json=payout(
                "cpt_bluefin",
                "10.00",
                "USDC",
                {"kind": "evm_wallet", "network": "base-sepolia", "address": new},
            ),
        ).json()
    ch = next(x for x in j["decision"]["checks"] if x["check"] == "changed_details")
    assert ch["evidence"]["previous"] == old and ch["evidence"]["current"] == new
