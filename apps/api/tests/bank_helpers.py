"""Bank-rail test helpers: a banksim server, an organisation with the SEPA Instant-style rail, pay and send."""

from __future__ import annotations

import time
from dataclasses import dataclass

from banksim.app import Config, SchemeConfig
from decision_helpers import DecisionOrg, payout, setup_decision_org
from detent.clock import FrozenClock
from detent.domain.money import Currency, Money
from detent.execution.resolver import resolve_unknown
from detent.execution.send import apply_rail_status, send_payment
from detent.intents.service import IntentRequest, submit_intent
from detent.policy.screening import MockScreening
from detent.rails.banksim import BankAdapter
from detent.rails.base import AttemptView
from detent.rails.registry import install_rail
from sqlalchemy import Engine, text

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


def setup_bank_org(engine: Engine, clock: FrozenClock, url: str, *, timeout: float = 1.0) -> BankOrg:
    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        install_rail(
            c,
            d.id,
            rail_id="banksim-sepa-inst",
            kind="banksim",
            network="banksim-sepa-inst",
            currency="EUR",
            fee_flat_minor=25,
            fee_bps=5,
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


def resolve_or_confirm(engine: Engine, clock: FrozenClock, bo: BankOrg, pid: str) -> str:
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
        Money(int(a.amount_minor), Currency("EUR")),
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


def settle(engine: Engine, clock: FrozenClock, bo: BankOrg, pid: str, tries: int = 60) -> str:
    """Poll the rail until the payment has a final answer (or give up and return the last status)."""
    import time

    st = ""
    for _ in range(tries):
        st = resolve_or_confirm(engine, clock, bo, pid)
        if st not in ("SUBMITTED", "UNKNOWN"):
            return st
        time.sleep(0.2)
    return st
