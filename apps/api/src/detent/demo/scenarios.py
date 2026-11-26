"""The demo scenario runner (CON-09): one click per part of the 10-minute demo (spec/11).

Every scenario runs inside the current demo generation and goes through the product's own services, so the
rules decide and the worker sends, exactly as for any other payment. The runner never sends a payout itself
and never approves anything. What it does on its own is play the outside world: fictional payers who send
the batch's deposits, and faults armed on the fault proxy for the next matching send.

Idempotent: a scenario that already ran in this generation returns its recorded result (an audit event
``demo.scenario_run``) and changes nothing. Payments and deposit intents use fixed idempotency keys too, so
a run that stopped half-way picks up where it stopped. Time comes from the controllable demo clock.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

import httpx
import yaml
from sqlalchemy import text

from detent.audit.log import Actor, append
from detent.db.engine import transaction
from detent.settings import REPO_ROOT

if TYPE_CHECKING:
    from detent.runtime import Runtime

log = logging.getLogger("detent.demo")

BATCH_FILE = REPO_ROOT / "fixtures" / "batches" / "demo-batch-20.yaml"
REGISTRY_FILE = REPO_ROOT / "fixtures" / "counterparties.yaml"
CANONICAL_INVOICE = REPO_ROOT / "fixtures" / "invoices" / "inv-canonical-18500-usdc.txt"
INJECTION_INVOICE = REPO_ROOT / "fixtures" / "invoices" / "inv-injection-body.txt"
MANDATE_ID = "mnd_demo_ap_agent"
RUNNER_HEADER = {"x-dekernai-scenario-runner": "1"}
P08_AMOUNT_HEX = "047ed160"  # 75.42 USDC = 75,420,000 units: the only transfer whose first rail reverts


class ScenarioError(Exception):
    """The scenario can't run here (a missing wallet, an unreachable fault proxy, a payment in flight)."""


@dataclass
class Result:
    scenario: str
    lines: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)  # (label, href)
    repeated: bool = False

    def as_payload(self) -> dict[str, Any]:
        return {"scenario": self.scenario, "lines": self.lines, "links": [list(x) for x in self.links]}


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    title: str
    minute: str
    what: str
    run: Callable[[Runtime, str, Actor], Result]


# ------------------------------------------------------------------------------------------ bookkeeping
def recorded(rt: Runtime, org_id: str, scenario: str) -> Result | None:
    with rt.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT payload FROM audit_events WHERE org_id=:o AND kind='demo.scenario_run' "
                "AND payload->>'scenario' = :s ORDER BY seq LIMIT 1"
            ),
            {"o": org_id, "s": scenario},
        ).scalar_one_or_none()
    if row is None:
        return None
    return Result(
        scenario, list(row["lines"]), [(str(a), str(b)) for a, b in row.get("links", [])], repeated=True
    )


def _record(rt: Runtime, org_id: str, actor: Actor, result: Result) -> None:
    with transaction(rt.engine) as conn:
        append(
            conn,
            rt.clock,
            org_id=org_id,
            actor=actor,
            kind="demo.scenario_run",
            subject_id=org_id,
            payload=result.as_payload(),
        )


def run_scenario(rt: Runtime, org_id: str, scenario_id: str, actor: Actor) -> Result:
    sc = SCENARIOS.get(scenario_id)
    if sc is None:
        raise ScenarioError(f"unknown scenario {scenario_id!r}")
    if not sc.id.startswith("reset"):
        done = recorded(rt, org_id, sc.id)
        if done is not None:
            return done
    result = sc.run(rt, org_id, actor)
    if not sc.id.startswith("reset"):
        _record(rt, org_id, actor, result)
    return result


def _screening() -> Any:
    from detent.policy.screening import MockScreening

    return MockScreening.from_fixture()


def _minor(amount: str) -> int:
    whole, _, frac = amount.partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])


# --------------------------------------------------------------------------------- $18,500 invoice
def demo_document(rt: Runtime, org_id: str, path: Any) -> str:
    """A fixture invoice with its wallet placeholders filled from this generation's registry, so the text is
    what the fictional supplier would have sent (the wallet the registry knows)."""
    from detent.agents.instruction import fixture_placeholders

    raw = str(path.read_text())
    with rt.engine.connect() as conn:
        for k, v in fixture_placeholders(conn, org_id).items():
            raw = raw.replace("{{" + k + "}}", v)
    return raw


def _propose(rt: Runtime, org_id: str, path: Any) -> Any:
    from detent.agents.instruction import fixture_placeholders, propose_from_invoice
    from detent.agents.llm import llm_for

    with rt.engine.connect() as conn:
        placeholders = fixture_placeholders(conn, org_id)
    llm, _ = llm_for(rt.settings, placeholders)
    return propose_from_invoice(
        rt.engine,
        rt.clock,
        org_id=org_id,
        document=demo_document(rt, org_id, path),
        mandate_id=MANDATE_ID,
        llm=llm,
        model=rt.settings.model_agent,
        daily_token_budget=rt.settings.ai_daily_token_budget,
    )


def invoice_18500(rt: Runtime, org_id: str, actor: Actor) -> Result:
    """Minute 1 to 3: the agent reads the $18,500 USDC invoice and proposes it. Nothing is submitted: the
    presenter checks the fields and clicks "Submit as agent"."""
    p = _propose(rt, org_id, CANONICAL_INVOICE)
    return Result(
        "invoice_18500",
        [
            f"The agent read the $18,500 USDC invoice from Bluefin Components (fictional): {p.id}.",
            "Nothing is submitted yet. Check the fields and the mandate, then click Submit as agent.",
        ],
        [
            ("Open the proposal", f"/console/invoices/{p.id}"),
            ("Download the invoice to drop by hand", "/console/demo/invoice.txt"),
        ],
    )


# ---------------------------------------------------------------------------------- fault proxy
def _faults(rt: Runtime) -> str:
    return rt.settings.faultproxy_url.rstrip("/")


def _armed(rt: Runtime) -> list[dict[str, Any]]:
    r = httpx.get(f"{_faults(rt)}/__faults", headers=RUNNER_HEADER, timeout=3)
    r.raise_for_status()
    return list(r.json())


def _arm(rt: Runtime, scenario: dict[str, Any]) -> bool:
    """Arm a fault unless the same one is already armed and unused. True when it is armed now."""
    try:
        for s in _armed(rt):
            same = all(s.get(k) == scenario.get(k) for k in ("match", "fault", "body_contains"))
            if same and s.get("count", 0) != 0:
                return True
        r = httpx.post(f"{_faults(rt)}/__faults", json=scenario, headers=RUNNER_HEADER, timeout=3)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("fault proxy unreachable", extra={"error": type(exc).__name__})
        return False
    return True


def forced_timeout(rt: Runtime, org_id: str, actor: Actor) -> Result:
    """Minute 4 to 6: the next chain send is forwarded to the chain but its answer is lost. The attempt
    becomes UNKNOWN, nothing is resent, and the resolver finds the receipt: CONFIRMED."""
    ok = _arm(rt, {"match": "eth_sendRawTransaction", "fault": "timeout_after_forward", "count": 1})
    if not ok:
        raise ScenarioError(
            f"the fault proxy at {rt.settings.faultproxy_url} is unreachable; the Base Sepolia RPC must go "
            "through it for this scenario"
        )
    return Result(
        "forced_timeout",
        [
            "Armed: the next chain send is forwarded, then its answer is dropped (timeout_after_forward).",
            "Approve the $18,500 case now. The attempt becomes UNKNOWN; nothing is resent; the resolver "
            "finds the receipt and the payment is CONFIRMED.",
        ],
        [("Exceptions", "/console/exceptions")],
    )


# ------------------------------------------------------------------------------------ the batch
def batch() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(BATCH_FILE.read_text())
    return data


def destination_for(p: dict[str, Any], registry: dict[str, Any] | None = None) -> dict[str, str]:
    """The registered destination a batch payout pays: the counterparty's destination on the payout's
    network (or its only one)."""
    reg = registry or yaml.safe_load(REGISTRY_FILE.read_text())
    cpt = next(c for c in reg["counterparties"] if c["id"] == p["counterparty"])
    dests = cpt["destinations"]
    d = next((x for x in dests if x["network"] == p.get("network")), dests[0])
    return {"kind": d["kind"], "network": d["network"], "destination_id": d["id"]}


def payout_body(p: dict[str, Any], registry: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "payout",
        "source": "platform",
        "counterparty_id": p["counterparty"],
        "destination": destination_for(p, registry),
        "amount": {"amount": p["amount"], "currency": p["currency"]},
        "reference": f"demo batch {p['ref']}",
    }
    if p.get("allow_network_switch"):
        body["allow_network_switch"] = True
    return body


def _payer(rt: Runtime, network: str) -> Any:
    from detent.rails.signer import LocalKeySigner

    key = {
        "base-sepolia": rt.settings.demo_payer_private_key_base,
        "eth-sepolia": rt.settings.demo_payer_private_key_eth,
    }.get(network)
    if key is None:
        raise ScenarioError(
            f"no demo payer wallet for {network}: set DEMO_PAYER_PRIVATE_KEY_"
            f"{'BASE' if network == 'base-sepolia' else 'ETH'} (a funded test wallet; see detent demo check)"
        )
    return LocalKeySigner(key)


def _send_usdc(rt: Runtime, org_id: str, network: str, to: str, minor_units: int) -> tuple[str, int]:
    """A fictional payer sends test USDC to a deposit address. Returns (tx hash, block)."""
    from web3 import Web3

    from detent.rails.evm import ERC20_ABI

    url = {"base-sepolia": rt.settings.base_sepolia_rpc_url, "eth-sepolia": rt.settings.eth_sepolia_rpc_url}[
        network
    ]
    if not url:
        raise ScenarioError(f"no RPC URL configured for {network}")
    with rt.engine.connect() as conn:
        token = conn.execute(
            text("SELECT token_address FROM rails WHERE org_id=:o AND id=:r"), {"o": org_id, "r": network}
        ).scalar_one()
    signer = _payer(rt, network)
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))
    contract = w3.eth.contract(address=Web3.to_checksum_address(token), abi=ERC20_ABI)
    tx = contract.functions.transfer(Web3.to_checksum_address(to), minor_units).build_transaction(
        {
            "from": signer.address,
            "nonce": w3.eth.get_transaction_count(signer.address, "pending"),
            "chainId": w3.eth.chain_id,
        }
    )
    raw, _ = signer.sign(tx)
    h = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    return "0x" + h.hex().removeprefix("0x"), int(receipt["blockNumber"])


def _sent(rt: Runtime, org_id: str) -> dict[str, dict[str, Any]]:
    with rt.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT payload FROM audit_events WHERE org_id=:o AND kind='demo.deposit_sent'"),
            {"o": org_id},
        ).scalars()
        return {str(r["ref"]): dict(r) for r in rows}


def run_batch(rt: Runtime, org_id: str, actor: Actor) -> Result:
    """Minute 7 to 9: 20 payouts and 8 deposits. The rules decide each payout and the worker sends the
    approved ones; fictional payers send the deposits; dep-07 lands on the wrong address (the designed
    break). Then "Close the day" imports the bank statements and runs reconciliation."""
    from detent.intents.service import IntentRequest, submit_intent
    from detent.ledger.deposits import DepositRequest, create_deposit_intent, deposit_address

    data = batch()
    registry = yaml.safe_load(REGISTRY_FILE.read_text())
    screening = _screening()
    p08 = _arm(
        rt,
        {
            "match": "eth_estimateGas",
            "fault": "low_gas_estimate",
            "count": 2,
            "body_contains": P08_AMOUNT_HEX,
        },
    )
    outcomes: dict[str, int] = {}
    for p in data["payouts"]:
        _, body = submit_intent(
            rt.engine,
            rt.clock,
            org_id=org_id,
            actor_id="usr_demo_runner",
            actor_role="platform",
            idempotency_key=f"demo-batch-{p['ref']}",
            request=IntentRequest.model_validate(payout_body(p, registry)),
            decision_only=False,
            screening=screening,
        )
        st = str(body.get("status"))
        outcomes[st] = outcomes.get(st, 0) + 1

    intents: dict[str, dict[str, Any]] = {}
    for dep in data["deposits"]:
        network = dep.get("network") or dep.get("rail")
        req = DepositRequest.model_validate(
            {
                "account_ref": dep["account"],
                "currency": dep["currency"],
                "network": network,
                "expected_amount": {"amount": dep["amount"], "currency": dep["currency"]},
            }
        )
        _, intents[dep["ref"]] = create_deposit_intent(
            rt.engine,
            rt.clock,
            org_id=org_id,
            actor_id="usr_demo_runner",
            idempotency_key=f"demo-batch-{dep['ref']}",
            request=req,
        )

    sent = _sent(rt, org_id)
    rescan: dict[str, int] = {}
    for dep in data["deposits"]:
        if dep["ref"] in sent:
            continue
        minor = _minor(dep["amount"])
        if dep.get("rail"):  # the simulated bank: a fictional payer's inbound transfer
            ref = intents[dep["ref"]]["instructions"]["reference"]
            bank = rt.settings.banksim_url.rstrip("/")
            body = {
                "scheme": "fps",
                "amount_minor": minor,
                "reference": ref,
                "payer": "Demo payer (fictional)",
                "account": org_id,
                "id": f"bin_demo_{org_id}_{dep['ref']}",
            }
            httpx.post(f"{bank}/inbound", json=body, timeout=10).raise_for_status()
            if dep.get("duplicate_notification"):
                httpx.post(f"{bank}/inbound", json=body, timeout=10).raise_for_status()
            info: dict[str, Any] = {"ref": dep["ref"], "rail": dep["rail"]}
        else:
            if dep.get("sent_to"):  # dep-07: sent on Base Sepolia to another user's address
                network, to = "base-sepolia", deposit_address(org_id, "acct_u1002", "base-sepolia")
            else:
                network, to = dep["network"], str(intents[dep["ref"]]["instructions"]["address"])
            tx, block = _send_usdc(rt, org_id, network, to, minor * 10**4)
            if dep.get("duplicate_notification"):
                rescan[network] = block
            info = {"ref": dep["ref"], "rail": network, "tx_hash": tx, "block": block}
        with transaction(rt.engine) as conn:
            append(
                conn,
                rt.clock,
                org_id=org_id,
                actor=actor,
                kind="demo.deposit_sent",
                subject_id=str(intents[dep["ref"]]["id"]),
                payload=info,
            )
    _watch(rt, org_id, rescan)

    lines = [
        "20 payouts submitted: "
        + ", ".join(f"{n} {s}" for s, n in sorted(outcomes.items()))
        + ". The worker sends the approved ones.",
        "8 deposits sent by fictional payers (test USDC and the simulated bank); dep-07 went to the wrong "
        "address on purpose, and dep-08's notification arrived twice.",
        "p08 (75.42 USDC): its Base Sepolia transfer reverts, so it fails over to Ethereum Sepolia under the "
        "same payment ID."
        if p08
        else "p08 failover not armed: the fault proxy is unreachable.",
        "When the payments have settled, run Close the day.",
    ]
    return Result(
        "batch_20", lines, [("Payments", "/console/payments"), ("Reconciliation", "/console/reconciliation")]
    )


def _watch(rt: Runtime, org_id: str, rescan: dict[str, int]) -> None:
    """Watch the deposit rails now, and once more over the duplicated notification's block (dep-08):
    the second pass sees the same transfer and must not credit it again."""
    from detent.ledger.credit import process_pending
    from detent.ledger.watchers import _cursor, _set_cursor, watch_bank, watch_evm
    from detent.rails.registry import build_adapters

    adapters = build_adapters(rt.settings, rt.engine, org_id)
    for rid, a in adapters.items():
        if hasattr(a, "transfers"):
            watch_evm(rt.engine, rt.clock, org_id, rid, a)
            if rid in rescan:
                with transaction(rt.engine) as conn:
                    cur = _cursor(conn, org_id, rid)
                    # Back to the duplicated transfer's block, never forward (that would skip blocks).
                    start = min(int(cur), rescan[rid]) if cur is not None else rescan[rid]
                    _set_cursor(conn, rt.clock, org_id, rid, str(start))
                    append(
                        conn,
                        rt.clock,
                        org_id=org_id,
                        actor=Actor.system("demo"),
                        kind="demo.duplicate_notification",
                        subject_id=rid,
                        payload={"rail": rid, "from_block": start},
                    )
                watch_evm(rt.engine, rt.clock, org_id, rid, a)
        elif hasattr(a, "inbound"):
            watch_bank(rt.engine, rt.clock, org_id, rid, a)
    process_pending(rt.engine, rt.clock, org_id=org_id, screening=_screening())


def close_day(rt: Runtime, org_id: str, actor: Actor) -> Result:
    """Import today's bank statements, watch the deposit rails and run reconciliation."""
    from detent.ledger.statements import import_statement
    from detent.rails.registry import build_adapters
    from detent.reconciliation.run import run_for

    with rt.engine.connect() as conn:
        busy = conn.execute(
            text("SELECT count(*) FROM payment_intents WHERE org_id=:o AND status IN ('READY','SUBMITTED')"),
            {"o": org_id},
        ).scalar_one()
    if busy:
        raise ScenarioError(f"{busy} payment(s) are still being sent; wait for them to settle")
    _watch(rt, org_id, {})
    # The simulated bank cuts its statements by its own business day, which can differ from the demo clock
    # (fast-forward moves the demo clock, never the bank's).
    try:
        info = httpx.get(f"{rt.settings.banksim_url.rstrip('/')}/healthz", timeout=5).json()
        day = date.fromisoformat(str(info["business_date"]))
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise ScenarioError(f"the bank simulator at {rt.settings.banksim_url} did not answer") from exc
    for rid, a in build_adapters(rt.settings, rt.engine, org_id).items():
        if hasattr(a, "inbound"):
            import_statement(rt.engine, rt.clock, org_id=org_id, rail_id=rid, adapter=a, day=day)
    res = run_for(rt.engine, rt.clock, rt.settings, org_id)
    return Result(
        "close_day",
        [
            f"Bank statements imported for {day.isoformat()}.",
            f"Reconciliation: {res.matched} of {res.counted} money-moving items matched, "
            f"{res.counted - res.matched} break(s) with a proposed fix.",
        ],
        [("Reconciliation", "/console/reconciliation")],
    )


# --------------------------------------------------------------------------------- attack sample
def attack_sample(rt: Runtime, org_id: str, actor: Actor) -> Result:
    """A few attacks from the evaluation suite, run live against this generation. Each line says what was
    tried and what the product did. The full suite (120 attacks) is in the release-gate report."""
    from detent.domain.states import Status
    from detent.intents.service import IntentRequest, submit_intent
    from detent.intents.transition import apply_transition

    screening = _screening()
    lines: list[str] = []
    links: list[tuple[str, str]] = []

    def intent(key: str, body: dict[str, Any], **kw: Any) -> dict[str, Any]:
        _, out = submit_intent(
            rt.engine,
            rt.clock,
            org_id=org_id,
            actor_id=kw.pop("actor_id", "usr_demo_runner"),
            actor_role=kw.pop("actor_role", "platform"),
            idempotency_key=f"demo-attack-{key}",
            request=IntentRequest.model_validate(body),
            decision_only=False,
            screening=screening,
            **kw,
        )
        return out

    flagged = intent(
        "screened",
        payout_body({"counterparty": "cpt_flagged", "amount": "900.00", "currency": "USDC", "ref": "atk1"}),
    )
    lines.append(f"Pay a screened payee: {flagged['status']} ({flagged['id']}).")
    links.append(("The blocked payment", f"/console/payments/{flagged['id']}"))
    try:
        apply_transition(
            rt.engine,
            rt.clock,
            org_id=org_id,
            payment_id=str(flagged["id"]),
            to=Status.READY,
            actor=actor,
            reason="demo attack: force a blocked payment to send",
        )
        lines.append("Force the blocked payment to READY: ALLOWED (this must never happen).")
    except Exception as exc:  # the refusal is the expected outcome
        lines.append(
            f"Force the blocked payment to READY: refused ({type(exc).__name__}); BLOCKED is terminal."
        )

    if rt.settings.mandate_signing_key_demo is not None:
        over = dict(
            payout_body(
                {"counterparty": "cpt_bluefin", "amount": "60000.00", "currency": "USDC", "ref": "atk3"}
            ),
            source="agent",
            mandate_id=MANDATE_ID,
        )
        out = intent("over-mandate", over, mandate_key=rt.settings.mandate_signing_key_demo)
        outcome = (out.get("decision") or {}).get("outcome", out.get("status"))
        lines.append(f"The agent proposes $60,000, above its mandate: {out['status']} (decision {outcome}).")

    p = _propose(rt, org_id, INJECTION_INVOICE)
    flags = ", ".join(str(f.get("code")) for f in p.flags) or "none"
    lines.append(
        f"An invoice whose text tells the agent to pay a new wallet now: the agent proposes, flags: {flags}; "
        "nothing is sent until a person resolves the flags and the rules decide."
    )
    links.append(("The injected invoice", f"/console/invoices/{p.id}"))
    return Result("attack_sample", lines, links)


# --------------------------------------------------------------------------------------- reset
def reset(rt: Runtime, org_id: str, actor: Actor) -> Result:
    from detent.demo.generations import reset_demo

    try:
        r = reset_demo(rt, actor=actor)
    except Exception as exc:
        raise ScenarioError(str(exc)) from exc
    return Result(
        "reset",
        [
            f"New demo generation {r.generation}: {r.org_id}. The previous one ({r.previous_org_id}) is kept "
            "with its audit log and ledger, and its kill switch is engaged.",
            "Pick an acting user to continue.",
        ],
        [("Act as", "/console/act-as")],
    )


_S = [
    (
        "invoice_18500",
        "The $18,500 invoice",
        "1 to 3",
        "The agent reads the canonical invoice and proposes it.",
    ),
    ("forced_timeout", "Forced timeout", "4 to 6", "The next chain send times out: UNKNOWN, then CONFIRMED."),
    (
        "batch_20",
        "20-payment batch with deposits",
        "7 to 9",
        "Three rails, one block, one failover, one break.",
    ),
    ("close_day", "Close the day", "8 to 9", "Import bank statements and run reconciliation."),
    (
        "attack_sample",
        "Attack sample",
        "9 to 10",
        "Live attacks against the rules; the full suite is in the report.",
    ),
    ("reset", "Reset demo data", "before", "A new data generation; nothing is deleted."),
]
_FN: dict[str, Callable[[Runtime, str, Actor], Result]] = {
    "invoice_18500": invoice_18500,
    "forced_timeout": forced_timeout,
    "batch_20": run_batch,
    "close_day": close_day,
    "attack_sample": attack_sample,
    "reset": reset,
}
SCENARIOS: dict[str, Scenario] = {i: Scenario(i, t, m, w, _FN[i]) for i, t, m, w in _S}


def dumps(result: Result) -> str:
    return json.dumps(result.as_payload(), indent=2)
