"""A synthetic reconciliation set (LED-06 AC4): settled payouts and credited deposits on the simulated bank
rails, with matching statement lines, plus designed breaks. Built straight in the database through the
real ledger, attempt and credit code (no HTTP), so 500 items take seconds. Synthetic, fictional data."""

from __future__ import annotations

from dataclasses import dataclass, field

from decision_helpers import DecisionOrg, setup_decision_org
from detent.agents.llm import RecordedLLM
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.ids import Prefix, new_id
from detent.domain.states import AttemptStatus, Status
from detent.execution.attempts import create_attempt, mark_attempt
from detent.intents.transition import transition
from detent.ledger.credit import process_inbound
from detent.ledger.deposits import DepositRequest, create_deposit_intent
from detent.policy.screening import MockScreening
from detent.rails.registry import install_rail
from detent.reconciliation.run import RunResult, run_reconciliation
from detent.settings import REPO_ROOT
from sqlalchemy import Connection, Engine, text

RECS = REPO_ROOT / "fixtures" / "agent-recordings" / "reconciliation"
ACT = Actor.system("synthetic")


@dataclass
class ReconOrg:
    d: DecisionOrg
    designed: dict[str, str] = field(default_factory=dict)  # break name -> subject key

    @property
    def id(self) -> str:
        return self.d.id


def recon_org(engine: Engine, clock: FrozenClock) -> ReconOrg:
    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        for rid, cur in (("banksim-sepa-inst", "EUR"), ("banksim-fps", "GBP")):
            install_rail(c, d.id, rail_id=rid, kind="banksim", network=rid, currency=cur, fee_flat_minor=20)
    return ReconOrg(d)


def _statement_line(
    c: Connection,
    clock: FrozenClock,
    org: str,
    rail: str,
    ext: str,
    direction: str,
    minor: int,
    cur: str,
    ref: str | None = None,
) -> None:
    c.execute(
        text(
            "INSERT INTO rail_records (id, org_id, rail_id, external_id, direction, amount_minor, currency, party, reference, "
            "source, occurred_at, statement_date) VALUES (:id, :o, :r, :e, :d, :a, :c, 'Synthetic party (fictional)', :ref, "
            "'statement', :t, :day)"
        ),
        {
            "id": f"rr_{rail}_{ext}",
            "o": org,
            "r": rail,
            "e": ext,
            "d": direction,
            "a": minor,
            "c": cur,
            "ref": ref,
            "t": clock.now(),
            "day": clock.now().date(),
        },
    )


def settled_payout(engine: Engine, clock: FrozenClock, org: str, n: int, *, on_statement: bool = True) -> str:
    rail, cur = ("banksim-sepa-inst", "EUR") if n % 2 else ("banksim-fps", "GBP")
    minor = 1_000 + 37 * n
    now = clock.now()
    pid = new_id(Prefix.PAY, now)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO payment_intents (id, org_id, source, counterparty_id, amount_minor, currency, status, "
                "idempotency_key, request_hash, initiated_by, created_at, updated_at) VALUES (:id, :o, 'platform', "
                "'cpt_harbor', :a, :c, 'READY', :k, 'synthetic', 'usr_synthetic', :t, :t)"
            ),
            {"id": pid, "o": org, "a": minor, "c": cur, "k": f"syn-{pid}", "t": now},
        )
        att = create_attempt(c, clock, org_id=org, payment_id=pid, rail_id=rail)
        mark_attempt(c, clock, org_id=org, attempt_id=att.id, to=AttemptStatus.SUBMITTED)
        transition(c, clock, org_id=org, payment_id=pid, to=Status.SUBMITTED, actor=ACT)
        mark_attempt(
            c, clock, org_id=org, attempt_id=att.id, to=AttemptStatus.CONFIRMED, evidence={"synthetic": True}
        )
        transition(c, clock, org_id=org, payment_id=pid, to=Status.CONFIRMED, actor=ACT)
        if on_statement:
            _statement_line(c, clock, org, rail, att.idempotency_key, "out", minor, cur)
    return pid


def credited_deposit(
    engine: Engine,
    clock: FrozenClock,
    org: str,
    n: int,
    *,
    account: str | None = None,
    minor: int | None = None,
    received: int | None = None,
    on_statement: bool = True,
    booked: bool = True,
) -> tuple[str, str]:
    """A deposit intent and (unless booked=False) its inbound credit, decided. Returns (intent id, inbound id)."""
    rail, cur = ("banksim-fps", "GBP") if n % 2 else ("banksim-sepa-inst", "EUR")
    minor = minor or 2_000 + 41 * n
    req = DepositRequest.model_validate(
        {
            "account_ref": account or f"acct_s{n:04d}",
            "currency": cur,
            "network": rail,
            "expected_amount": {"amount": f"{minor // 100}.{minor % 100:02d}", "currency": cur},
        }
    )
    _, dep = create_deposit_intent(
        engine, clock, org_id=org, actor_id="usr_synthetic", idempotency_key=f"syn-dep-{org}-{n}", request=req
    )
    ref = dep["instructions"]["reference"]
    got = received or minor
    bank_id = f"bin_syn_{org[-8:]}_{n:04d}"
    with engine.begin() as c:
        if on_statement:
            _statement_line(c, clock, org, rail, bank_id, "in", got, cur, ref)
        if not booked:
            return str(dep["id"]), ""
        iid = new_id(Prefix.INB, clock.now())
        c.execute(
            text(
                "INSERT INTO inbound_transfers (id, org_id, rail_id, tx_hash, log_index, from_address, to_address, amount_minor, "
                "token, confirmations, seen_at, currency, network) VALUES (:id, :o, :r, :h, 0, 'Synthetic payer (fictional)', "
                ":ref, :a, :c, 1, :t, :cur, :net)"
            ),
            {
                "id": iid,
                "o": org,
                "r": rail,
                "h": bank_id,
                "ref": ref,
                "a": got,
                "c": cur,
                "cur": cur,
                "net": rail,
                "t": clock.now(),
            },
        )
    process_inbound(engine, clock, org_id=org, inbound_id=iid, screening=MockScreening.from_fixture())
    return str(dep["id"]), iid


def mark_statements_imported(engine: Engine, clock: FrozenClock, org: str) -> None:
    with engine.begin() as c:
        for rail in ("banksim-sepa-inst", "banksim-fps"):
            c.execute(
                text(
                    "INSERT INTO bank_statements (org_id, rail_id, statement_date, format, lines, imported_at) "
                    "VALUES (:o, :r, :d, 'json', 0, :t) ON CONFLICT DO NOTHING"
                ),
                {"o": org, "r": rail, "d": clock.now().date(), "t": clock.now()},
            )


def build_500(engine: Engine, clock: FrozenClock) -> ReconOrg:
    """247 matched payouts + 250 deposits and 3 designed breaks = 500 counted items."""
    ro = recon_org(engine, clock)
    org = ro.id
    for n in range(249):
        settled_payout(engine, clock, org, n)
    for n in range(248):
        credited_deposit(engine, clock, org, n)
    # Break 1: a payout the ledger settled but the bank statement doesn't show.
    missing = settled_payout(engine, clock, org, 900, on_statement=False)
    ro.designed["payout_missing_on_rail"] = f"payout:{missing}"
    # Break 2: 200.00 arrives for account A, whose intent expects 50.00, while account B's intent expects
    # exactly 200.00 (the dep-07 pattern). It is held in suspense; the fix should match it to B.
    credited_deposit(
        engine, clock, org, 901, account="acct_b", minor=20_000, booked=False, on_statement=False
    )
    _, inb = credited_deposit(engine, clock, org, 903, account="acct_a", minor=5_000, received=20_000)
    ro.designed["unallocated_inbound"] = f"suspense:{inb}"
    # Break 3: a bank statement credit the watcher never booked, whose reference belongs to an intent.
    credited_deposit(engine, clock, org, 905, account="acct_c", minor=7_700, booked=False)
    ro.designed["rail_record_unbooked"] = "record:banksim-fps:" + f"bin_syn_{org[-8:]}_0905"
    mark_statements_imported(engine, clock, org)
    return ro


def recorded(ph: object) -> RecordedLLM:
    return RecordedLLM.from_dir(RECS, ph)  # type: ignore[arg-type]


def reconcile(engine: Engine, clock: FrozenClock, org: str) -> RunResult:
    return run_reconciliation(
        engine, clock, org_id=org, llm_factory=recorded, model="claude-sonnet-5-5", daily_token_budget=10**9
    )
