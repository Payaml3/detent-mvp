"""RAL-04 and RAL-01 for the bank rail; EXE-05/06/07 on the bank side; RAL-05 duplicate requests."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pytest
from banksim.app import Config, SchemeConfig
from banksim.app import create_app as bank_app
from conftest import TEST_DB_URL
from decision_helpers import DecisionOrg, payout, setup_decision_org
from detent.clock import FrozenClock
from detent.domain.money import Money
from detent.execution.resolver import resolve_unknown
from detent.execution.send import send_payment
from detent.intents.service import IntentRequest, submit_intent
from detent.policy.screening import MockScreening
from detent.rails.banksim import BankAdapter
from detent.rails.base import AttemptView, IntentView
from detent.rails.registry import install_rail
from fastapi import FastAPI, Request
from faultproxy.app import create_app as proxy_app
from servers import fault, serve
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}


@dataclass
class BankOrg:
    d: DecisionOrg
    bank: str
    adapter: BankAdapter

    @property
    def id(self) -> str:
        return self.d.id


def big() -> Config:
    s = SchemeConfig(
        per_payment_limit_minor=10_000_000_00, daily_limit_minor=10_000_000_00, fee_flat_minor=25, fee_bps=5
    )
    return Config(schemes={"fps": s, "sepa_inst": s}, hold_seconds=2.0)


@pytest.fixture
def bank() -> Iterator[str]:
    with serve(bank_app(TEST_DB_URL.replace("+psycopg", "+psycopg"), big())) as url:
        yield url


def setup_bank_org(engine: Engine, clock: FrozenClock, url: str, *, timeout: float = 1.0) -> BankOrg:
    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        install_rail(
            c, d.id, rail_id="banksim-sepa-inst", kind="banksim", network="banksim-sepa-inst", currency="EUR"
        )
    a = BankAdapter(
        rail_id="banksim-sepa-inst",
        base_url=url,
        scheme="sepa_inst",
        currency="EUR",
        per_payment_limit_minor=25_000_00,
        fee_flat_minor=25,
        fee_bps=5,
        timeout_seconds=timeout,
    )
    return BankOrg(d, url, a)


def pay(engine: Engine, clock: FrozenClock, bo: BankOrg, amount: str) -> str:
    req = IntentRequest.model_validate(payout("cpt_harbor", amount, "EUR", HARBOR))
    code, body = submit_intent(
        engine,
        clock,
        org_id=bo.id,
        actor_id="usr_api",
        idempotency_key=f"k{amount}{time.time()}",
        request=req,
        decision_only=False,
        screening=MockScreening.from_fixture(),
    )
    assert code == 201 and body["status"] == "READY", body
    return str(body["id"])


def send(engine: Engine, clock: FrozenClock, bo: BankOrg, pid: str) -> str:
    return send_payment(
        engine,
        clock,
        {"banksim-sepa-inst": bo.adapter},
        org_id=bo.id,
        payment_id=pid,
        screening=MockScreening.from_fixture(),
    ).value


def bank_payments(url: str) -> list[dict[str, object]]:
    return list(httpx.get(f"{url}/statements/{datetime.now(UTC).date().isoformat()}").json()["payments"])


def test_contract(bank: str) -> None:
    a = BankAdapter(
        rail_id="banksim-sepa-inst",
        base_url=bank,
        scheme="sepa_inst",
        currency="EUR",
        per_payment_limit_minor=25_000_00,
        fee_flat_minor=25,
        fee_bps=5,
    )
    iv = IntentView("pay_c1", Money.parse("100.00", "EUR"), "banksim-sepa-inst", "DE89 **** **** 3000")
    assert a.eligible(iv).eligible
    assert not a.eligible(
        IntentView("pay_c1", Money.parse("100.00", "GBP"), "banksim-sepa-inst", "x")
    ).eligible
    assert not a.eligible(
        IntentView("pay_c1", Money.parse("25000.01", "EUR"), "banksim-sepa-inst", "x")
    ).eligible
    assert a.quote(iv).fee_minor == 25 + 10000 * 5 // 10000
    assert a.health().ok
    v = AttemptView(
        "att_c",
        "pay_cBANK",
        1,
        "banksim-sepa-inst",
        "pay_cBANK",
        Money.parse("100.00", "EUR"),
        "DE89",
        None,
        None,
        None,
    )
    assert a.status(v).state == "NOT_FOUND"
    assert a.submit(v).rail_reference == "pay_cBANK"
    a.submit(v)  # the same idempotency key again: the rail deduplicates
    for _ in range(20):
        if a.status(v).state == "CONFIRMED":
            break
        time.sleep(0.1)
    assert a.status(v).state == "CONFIRMED"
    assert sum(1 for p in bank_payments(bank) if p["key"] == "pay_cBANK") == 1


def test_detent_sends_a_euro_payout_on_the_bank_rail(engine: Engine, clock: FrozenClock, bank: str) -> None:
    bo = setup_bank_org(engine, clock, bank)
    pid = pay(engine, clock, bo, "2000.00")
    st = send(engine, clock, bo, pid)
    for _ in range(20):
        if st == "CONFIRMED":
            break
        time.sleep(0.1)
        st = resolve_or_confirm(engine, clock, bo, pid)
    assert st == "CONFIRMED"
    [p] = [p for p in bank_payments(bank) if p["key"] == pid]
    assert p["amount_minor"] == 200000 and p["account"] == "DE89 **** **** 3000"


def resolve_or_confirm(engine: Engine, clock: FrozenClock, bo: BankOrg, pid: str) -> str:
    from detent.execution.send import apply_rail_status

    with engine.connect() as c:
        a = c.execute(
            text(
                "SELECT a.*, p.amount_minor FROM attempts a JOIN payment_intents p ON p.org_id=a.org_id "
                "AND p.id=a.payment_id WHERE a.org_id=:o AND a.payment_id=:p ORDER BY attempt_no DESC LIMIT 1"
            ),
            {"o": bo.id, "p": pid},
        ).one()
    v = AttemptView(
        a.id,
        pid,
        a.attempt_no,
        a.rail_id,
        a.idempotency_key,
        Money(int(a.amount_minor), "EUR"),  # type: ignore[arg-type]
        "DE89 **** **** 3000",
        None,
        None,
        None,
    )
    if a.status == "UNKNOWN":
        return resolve_unknown(
            engine, clock, {"banksim-sepa-inst": bo.adapter}, org_id=bo.id, payment_id=pid
        ).value
    return apply_rail_status(engine, clock, bo.adapter, bo.id, v).value


def test_amount_ending_13_times_out_then_settles_once(engine: Engine, clock: FrozenClock, bank: str) -> None:
    bo = setup_bank_org(engine, clock, bank)
    pid = pay(engine, clock, bo, "100.13")
    assert send(engine, clock, bo, pid) == "UNKNOWN"
    st = "UNKNOWN"
    for _ in range(30):
        st = resolve_unknown(
            engine, clock, {"banksim-sepa-inst": bo.adapter}, org_id=bo.id, payment_id=pid
        ).value
        if st != "UNKNOWN":
            break
        time.sleep(0.1)
    assert st == "CONFIRMED"
    assert sum(1 for p in bank_payments(bank) if p["key"] == pid) == 1


def test_amount_ending_42_fails_technically_and_ends_final(
    engine: Engine, clock: FrozenClock, bank: str
) -> None:
    bo = setup_bank_org(engine, clock, bank)
    pid = pay(engine, clock, bo, "100.42")
    assert send(engine, clock, bo, pid) == "FAILED_FINAL"  # one EUR rail: nothing to fail over to
    with engine.connect() as c:
        a = c.execute(
            text("SELECT status, failure_class FROM attempts WHERE org_id=:o AND payment_id=:p"),
            {"o": bo.id, "p": pid},
        ).one()
    assert tuple(a) == ("FAILED", "TECHNICAL_FINAL")


def test_rail_rejection_is_never_retried_or_rerouted(engine: Engine, clock: FrozenClock) -> None:
    tight = SchemeConfig(per_payment_limit_minor=25_000_00, daily_limit_minor=50_00, fee_flat_minor=25)
    with serve(bank_app(TEST_DB_URL, Config(schemes={"fps": tight, "sepa_inst": tight}))) as url:
        bo = setup_bank_org(engine, clock, url)
        pid = pay(engine, clock, bo, "100.00")
        with engine.begin() as c:
            c.execute(
                text("UPDATE payment_intents SET allow_network_switch=true WHERE org_id=:o AND id=:p"),
                {"o": bo.id, "p": pid},
            )
        assert send(engine, clock, bo, pid) == "FAILED_FINAL"
        with engine.connect() as c:
            rows = c.execute(
                text("SELECT status, failure_class FROM attempts WHERE org_id=:o AND payment_id=:p"),
                {"o": bo.id, "p": pid},
            ).all()
            jobs = c.execute(
                text("SELECT count(*) FROM jobs WHERE org_id=:o AND dedupe_key LIKE :k"),
                {"o": bo.id, "k": f"{pid}:%"},
            ).scalar()
    assert [tuple(r) for r in rows] == [("FAILED", "REJECTED_BY_RAIL")] and jobs == 0


def test_duplicate_requests_create_one_bank_payment(engine: Engine, clock: FrozenClock, bank: str) -> None:
    with serve(proxy_app(bank)) as proxy:
        bo = setup_bank_org(engine, clock, proxy)
        pid = pay(engine, clock, bo, "300.00")
        fault(proxy, "POST /payments", "duplicate_request")
        send(engine, clock, bo, pid)
        assert sum(1 for p in bank_payments(bank) if p["key"] == pid) <= 1
        time.sleep(0.3)
        assert sum(1 for p in bank_payments(bank) if p["key"] == pid) == 1


def test_settlement_callback(engine: Engine, clock: FrozenClock) -> None:
    got: list[dict[str, object]] = []
    hook = FastAPI()

    @hook.get("/healthz")
    def h() -> dict[str, str]:
        return {"ok": "yes"}

    @hook.post("/cb")
    async def cb(r: Request) -> dict[str, str]:
        got.append(await r.json())
        return {"ok": "yes"}

    with serve(hook) as hook_url:
        cfg = big()
        cfg.callback_url = f"{hook_url}/cb"
        cfg.settle_seconds = 0.2
        with serve(bank_app(TEST_DB_URL, cfg)) as url:
            r = httpx.post(
                f"{url}/payments",
                headers={"Idempotency-Key": "cb-1"},
                json={"scheme": "fps", "amount_minor": 1000, "currency": "GBP", "account": "**-**-01"},
            )
            assert r.status_code == 201 and r.json()["status"] == "ACCEPTED"
            for _ in range(30):
                if got:
                    break
                time.sleep(0.1)
    assert got == [{"key": "cb-1", "status": "SETTLED"}]
