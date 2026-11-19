"""LED-03, LED-04, LED-05 on the simulated bank rail: deposit intents, the watcher and credit-once."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from conftest import make_settings
from decision_helpers import PEPPER, DecisionOrg, setup_decision_org
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.exceptions.cases import add_business_days
from detent.ledger.credit import process_inbound, process_pending
from detent.ledger.journal import balances
from detent.ledger.watchers import watch_bank
from detent.policy.screening import MockScreening
from detent.rails.banksim import BankAdapter
from detent.rails.registry import install_rail
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db
SCREEN = MockScreening.from_fixture()


class BankDeposits:
    def __init__(self, d: DecisionOrg, api: TestClient, bank: str) -> None:
        self.d, self.api, self.bank = d, api, bank
        self.adapter = BankAdapter(
            rail_id="banksim-fps",
            base_url=bank,
            scheme="fps",
            currency="GBP",
            per_payment_limit_minor=None,
            receiving_account=d.id,
        )

    def intent(
        self, account: str, amount: str | None = "300.00", key: str | None = None, **kw: Any
    ) -> httpx.Response:
        body: dict[str, Any] = {"account_ref": account, "currency": "GBP", "network": "banksim-fps", **kw}
        if amount:
            body["expected_amount"] = {"amount": amount, "currency": "GBP"}
        return self.api.post(
            "/v1/deposit_intents",
            json=body,
            headers={**self.d.auth(), "Idempotency-Key": key or str(uuid.uuid4())},
        )  # type: ignore[return-value]

    def pay_in(
        self, reference: str, minor: int, payer: str = "A. Payer (fictional)", iid: str | None = None
    ) -> None:
        body = {
            "scheme": "fps",
            "amount_minor": minor,
            "reference": reference,
            "payer": payer,
            "account": self.d.id,
        }
        if iid:
            body["id"] = iid
        assert httpx.post(f"{self.bank}/inbound", json=body).status_code == 201


@pytest.fixture
def dep(engine: Engine, clock: FrozenClock, bank: str) -> Iterator[BankDeposits]:
    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        install_rail(c, d.id, rail_id="banksim-fps", kind="banksim", network="banksim-fps", currency="GBP")
    s = make_settings(d.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as api:
        yield BankDeposits(d, api, bank)


def _bal(engine: Engine, org: str) -> dict[tuple[str, str], int]:
    with engine.connect() as c:
        return {(str(b["kind"]), str(b["ref"])): int(b["balance_minor"]) for b in balances(c, org)}  # type: ignore[call-overload]


def _inbound(engine: Engine, org: str) -> list[Any]:
    with engine.connect() as c:
        return list(
            c.execute(
                text("SELECT * FROM inbound_transfers WHERE org_id=:o ORDER BY seen_at, id"), {"o": org}
            ).all()
        )


# ------------------------------------------------------------------------------------------- LED-03
def test_deposit_intent_gives_a_bank_reference_and_is_idempotent(
    dep: BankDeposits, clock: FrozenClock
) -> None:
    r = dep.intent("acct_u1003", key="dep-key-1")
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["id"].startswith("dep_") and j["status"] == "OPEN"
    assert j["instructions"]["kind"] == "bank_reference" and j["instructions"]["reference"].startswith("DTN-")
    assert j["expires_at"] == (clock.now() + timedelta(days=7)).isoformat().replace("+00:00", "Z")  # G-21
    again = dep.intent("acct_u1003", key="dep-key-1")
    assert again.status_code == 200 and again.json()["id"] == j["id"]
    clash = dep.intent("acct_u1003", amount="999.00", key="dep-key-1")
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "idempotency_key_reused"
    assert dep.api.post("/v1/deposit_intents", json={}, headers=dep.d.auth()).status_code in (400, 422)
    bad = dep.intent("acct_u1003", network="banksim-sepa-inst", currency="EUR")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unsupported_network"
    assert dep.api.get(f"/v1/deposit_intents/{j['id']}", headers=dep.d.auth()).json()["id"] == j["id"]


def test_chain_deposit_address_is_per_account_and_stable() -> None:
    from detent.ledger.deposits import deposit_address

    a = deposit_address("org_x", "acct_1", "base-sepolia")
    assert a == deposit_address("org_x", "acct_1", "base-sepolia") and a.startswith("0x") and len(a) == 42
    assert (
        a
        != deposit_address("org_x", "acct_2", "base-sepolia")
        != deposit_address("org_y", "acct_1", "base-sepolia")
    )
    assert a != deposit_address("org_x", "acct_1", "eth-sepolia")


# ---------------------------------------------------------------------------------------- LED-04/05
def test_deposit_is_credited_once_even_with_duplicate_notifications_and_restarts(
    dep: BankDeposits, engine: Engine, clock: FrozenClock
) -> None:
    j = dep.intent("acct_u1003").json()
    ref = j["instructions"]["reference"]
    dep.pay_in(ref, 30000, iid=f"bin_dup_{uuid.uuid4().hex[:8]}")
    dup = _inbound
    assert watch_bank(engine, clock, dep.d.id, "banksim-fps", dep.adapter) == 1
    assert watch_bank(engine, clock, dep.d.id, "banksim-fps", dep.adapter) == 0
    with engine.begin() as c:  # a restarted watcher with no cursor sees everything again
        c.execute(text("DELETE FROM watch_cursors WHERE org_id=:o"), {"o": dep.d.id})
    assert watch_bank(engine, clock, dep.d.id, "banksim-fps", dep.adapter) == 0
    [inb] = dup(engine, dep.d.id)
    with ThreadPoolExecutor(4) as pool:  # four workers race to credit it
        outs = list(
            pool.map(
                lambda _: process_inbound(
                    engine, clock, org_id=dep.d.id, inbound_id=inb.id, screening=SCREEN
                ),
                range(4),
            )
        )
    assert sorted(o.status for o in outs) == ["ALREADY_DECIDED"] * 3 + ["CREDITED"]
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM credits WHERE org_id=:o"), {"o": dep.d.id}).scalar_one() == 1
        )
    b = _bal(engine, dep.d.id)
    assert (
        b[("user_balance", "acct_u1003")] == -30000 and b[("rail_clearing", "banksim-fps:inbound")] == 30000
    )
    v = dep.api.get(f"/v1/deposit_intents/{j['id']}", headers=dep.d.auth()).json()
    assert v["status"] == "CREDITED" and v["credits"][0]["amount"] == {"amount": "300.00", "currency": "GBP"}


def test_each_mismatch_goes_to_suspense_and_opens_a_deposit_exception(
    dep: BankDeposits, engine: Engine, clock: FrozenClock
) -> None:
    short = dep.intent("acct_u1001", amount="300.00").json()["instructions"]["reference"]
    flagged = dep.intent("acct_u1002", amount="50.00").json()["instructions"]["reference"]
    dep.pay_in(short, 25000)  # amount mismatch
    dep.pay_in("DTN-NOSUCHREF", 1000)  # no intent
    dep.pay_in(
        flagged, 5000, payer="Example Sanctioned Trading Co (fictional)"
    )  # sender on the screening list
    watch_bank(engine, clock, dep.d.id, "banksim-fps", dep.adapter)
    outs = {tuple(o.reasons): o for o in process_pending(engine, clock, org_id=dep.d.id, screening=SCREEN)}
    assert set(outs) == {("AMOUNT_MISMATCH",), ("NO_INTENT",), ("SCREENING_HIT",)}
    assert {o.status for o in outs.values()} == {"SUSPENSE"}
    assert _bal(engine, dep.d.id)[("suspense", "suspense")] == -(25000 + 1000 + 5000)
    with engine.connect() as c:
        cases = c.execute(
            text(
                "SELECT type, deposit_id, deadline_at, created_at, owner_id FROM exception_cases WHERE org_id=:o"
            ),
            {"o": dep.d.id},
        ).all()
        credits = c.execute(
            text("SELECT count(*) FROM credits WHERE org_id=:o"), {"o": dep.d.id}
        ).scalar_one()
    assert credits == 0 and len(cases) == 3 and {c.type for c in cases} == {"deposit"}
    assert all(c.deadline_at == add_business_days(c.created_at, 1) for c in cases)  # P1BD, G-03
    assert all(c.owner_id == dep.d.org.users[Role.REVIEWER] for c in cases)


def test_expired_intent_is_never_silently_credited(
    dep: BankDeposits, engine: Engine, clock: FrozenClock
) -> None:
    ref = dep.intent("acct_u1003").json()["instructions"]["reference"]
    clock.advance(timedelta(days=8))
    dep.pay_in(ref, 30000)
    watch_bank(engine, clock, dep.d.id, "banksim-fps", dep.adapter)
    [o] = process_pending(engine, clock, org_id=dep.d.id, screening=SCREEN)
    assert o.status == "SUSPENSE" and o.reasons == ["INTENT_EXPIRED"]


def test_tolerance_is_a_per_organisation_setting(
    dep: BankDeposits, engine: Engine, clock: FrozenClock
) -> None:
    with engine.begin() as c:
        c.execute(
            text("UPDATE organisations SET deposit_tolerance_minor=100 WHERE org_id=:o"), {"o": dep.d.id}
        )
    ref = dep.intent("acct_u1003").json()["instructions"]["reference"]
    dep.pay_in(ref, 29950)
    watch_bank(engine, clock, dep.d.id, "banksim-fps", dep.adapter)
    [o] = process_pending(engine, clock, org_id=dep.d.id, screening=SCREEN)
    assert o.status == "CREDITED"


def test_another_organisations_bank_credits_are_not_seen(
    dep: BankDeposits, engine: Engine, clock: FrozenClock
) -> None:
    httpx.post(
        f"{dep.bank}/inbound",
        json={"scheme": "fps", "amount_minor": 700, "reference": "X", "account": "org_other"},
    )
    assert watch_bank(engine, clock, dep.d.id, "banksim-fps", dep.adapter) == 0


def test_business_days_skip_weekends() -> None:
    fri = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)
    assert fri.weekday() == 4
    assert add_business_days(fri, 1) == datetime(2026, 11, 23, 15, 0, tzinfo=UTC)
    assert add_business_days(datetime(2026, 11, 18, 9, 0, tzinfo=UTC), 1) == datetime(
        2026, 11, 19, 9, 0, tzinfo=UTC
    )


def test_the_worker_watches_and_credits(dep: BankDeposits, engine: Engine, clock: FrozenClock) -> None:
    from conftest import make_settings
    from detent.runtime import Runtime
    from detent.worker.loop import Worker

    with engine.begin() as c:
        c.execute(
            text("UPDATE rails SET base_url=:u WHERE org_id=:o AND id='banksim-fps'"),
            {"u": dep.bank, "o": dep.d.id},
        )
    ref = dep.intent("acct_u1003").json()["instructions"]["reference"]
    dep.pay_in(ref, 30000)
    w = Worker(Runtime(make_settings(dep.d.id), engine, clock), worker_id="dep-watch")
    assert w.watch_deposits(force=True)[dep.d.id] == 1
    with engine.connect() as c:
        assert (
            c.execute(
                text("SELECT status FROM inbound_transfers WHERE org_id=:o"), {"o": dep.d.id}
            ).scalar_one()
            == "CREDITED"
        )
