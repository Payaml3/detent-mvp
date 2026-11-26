"""The sandbox controls' service (DSH-07, SBX-03; spec/08 "Sandbox controls").

A member with `sandbox.control` can run a test scenario, which creates one sandbox payout with a test
value (SBX-01) through the same decision path as the API, and can move the organisation between the
simulated chain and real test networks. Both are audited.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import append
from detent.clock import Clock
from detent.dashboard.access import AccessError, Member, _require
from detent.intents.service import IntentRequest, RequestProblem, submit_intent
from detent.policy.screening import Screening
from detent.rails.simchain import SIMULATED_NETWORKS
from detent.sandbox.usage import QuotaExceeded
from detent.settings import Settings


@dataclass(frozen=True, slots=True)
class Scenario:
    key: str
    label: str
    expect: str
    request: dict[str, Any]


# Fixture payees seeded into every new organisation (G-18). Lumen is established on both test networks,
# so a technical failure can fail over; the flagged payee's wallet is on the screening list.
SCENARIOS: dict[str, Scenario] = {
    s.key: s
    for s in (
        Scenario(
            "timeout",
            "Timeout to UNKNOWN",
            "The rail takes the payout but the answer is lost: UNKNOWN, then CONFIRMED from rail evidence. "
            "Nothing is sent twice.",
            {
                "counterparty_id": "cpt_lumen",
                "destination": {
                    "kind": "evm_wallet",
                    "network": "base-sepolia",
                    "destination_id": "dst_lumen_base",
                },
                "amount": {"amount": "90.13", "currency": "USDC"},
                "allow_network_switch": True,
            },
        ),
        Scenario(
            "rail_failure",
            "Rail failure and failover",
            "The first rail's transaction reverts: the payout fails over to Ethereum Sepolia under the same "
            "payment ID.",
            {
                "counterparty_id": "cpt_lumen",
                "destination": {
                    "kind": "evm_wallet",
                    "network": "base-sepolia",
                    "destination_id": "dst_lumen_base",
                },
                "amount": {"amount": "90.42", "currency": "USDC"},
                "allow_network_switch": True,
            },
        ),
        Scenario(
            "flagged_address",
            "Flagged address",
            "The payee's wallet is on the screening list: BLOCK, which is final.",
            {
                "counterparty_id": "cpt_flagged",
                "destination": {
                    "kind": "evm_wallet",
                    "network": "base-sepolia",
                    "destination_id": "dst_flagged",
                },
                "amount": {"amount": "90.00", "currency": "USDC"},
            },
        ),
    )
}


def run_scenario(
    engine: Engine,
    clock: Clock,
    settings: Settings,
    screening: Screening,
    *,
    by: Member,
    scenario: str,
) -> dict[str, Any]:
    """Create the scenario's payout as the member, exactly as `POST /v1/payment_intents` would."""
    _require(by, "sandbox.control")
    s = SCENARIOS.get(scenario)
    if s is None:
        raise AccessError("validation_error", "Choose one of the listed scenarios.")
    body = IntentRequest.model_validate(
        {"kind": "payout", "source": "platform", "reference": f"SANDBOX-{scenario.upper()}", **s.request}
    )
    try:
        _code, out = submit_intent(
            engine,
            clock,
            org_id=by.org_id,
            actor_id=by.id,
            actor_role=by.role.value,
            idempotency_key=f"sandbox-{uuid.uuid4()}",
            request=body,
            decision_only=False,
            screening=screening,
            mandate_key=settings.mandate_signing_key_demo,
        )
    except RequestProblem as exc:
        raise AccessError(exc.code, exc.message) from exc
    except QuotaExceeded as exc:
        raise AccessError("quota_exceeded", str(exc), status=429) from exc
    with engine.begin() as conn:
        append(
            conn,
            clock,
            org_id=by.org_id,
            actor=by.actor,
            kind="sandbox.scenario_run",
            subject_id=out["id"],
            payload={"scenario": scenario, "via": "dashboard"},
        )
    return out


def testnet_available(settings: Settings) -> list[str]:
    """The real test networks this instance can send on (an RPC URL, a faucet wallet and a token)."""
    nets = {
        "base-sepolia": (
            settings.base_sepolia_rpc_url,
            settings.test_wallet_private_key_base,
            settings.usdc_address_base_sepolia,
        ),
        "eth-sepolia": (
            settings.eth_sepolia_rpc_url,
            settings.test_wallet_private_key_eth,
            settings.usdc_address_eth_sepolia,
        ),
    }
    return [n for n, parts in nets.items() if all(parts)]


def set_rails_mode(conn: Connection, clock: Clock, settings: Settings, *, by: Member, mode: str) -> str:
    """SBX-03: move between the simulated chain and real test networks. Refused while a payout on those
    networks is in flight, so an UNKNOWN attempt is always resolved on the chain that carried it."""
    _require(by, "sandbox.control")
    if mode not in ("simulated", "testnet"):
        raise AccessError("validation_error", "Choose the simulated chain or real test networks.")
    current = conn.execute(
        text("SELECT sandbox_rails FROM organisations WHERE org_id=:o FOR UPDATE"), {"o": by.org_id}
    ).scalar_one()
    if current == mode:
        return str(current)
    if mode == "testnet" and not testnet_available(settings):
        raise AccessError(
            "testnet_unavailable", "Real test networks are not configured on this instance.", status=409
        )
    busy = conn.execute(
        text(
            "SELECT count(*) FROM attempts WHERE org_id=:o AND rail_id = ANY(:r) "
            "AND status IN ('CREATED', 'SUBMITTED', 'UNKNOWN')"
        ),
        {"o": by.org_id, "r": list(SIMULATED_NETWORKS)},
    ).scalar_one()
    if int(busy):
        raise AccessError(
            "payouts_in_flight",
            "A payout on a test network is still in flight. Wait until it is confirmed or failed.",
            status=409,
        )
    conn.execute(
        text("UPDATE organisations SET sandbox_rails=:m WHERE org_id=:o"), {"m": mode, "o": by.org_id}
    )
    append(
        conn,
        clock,
        org_id=by.org_id,
        actor=by.actor,
        kind="sandbox.rails_mode_changed",
        subject_id=by.org_id,
        payload={"from": current, "to": mode, "via": "dashboard"},
    )
    return mode


# A payment in one of these states can still reach a rail without anyone approving it, so a reset waits for
# it: a hidden payment must never send. ESCALATED and HELD payments wait for an approval that no screen of
# the new generation can give, so they stay held (invariant 7) and are hidden with the rest. The exception is
# a payment held only by the kill switch: releasing the switch sends it back to READY with no approval, so it
# counts as one that can still be sent.
_SENDING = ("READY", "SUBMITTED", "UNKNOWN", "FAILED")
# Every dashboard organisation is on test networks in the prototype, client organisations included.
_RESETTABLE = ("client", "evaluation", "sandbox")


def reset_sandbox(conn: Connection, clock: Clock, *, by: Member, confirm: str) -> int:
    """SBX-04 (C-04, D-08): start a new data generation. Earlier intents, cases, ledger entries, logs and
    events are hidden from the API and dashboard and never deleted; keys, webhooks, members and settings
    stay. Refused while a payout could still be sent. Returns the new generation."""
    _require(by, "sandbox.control")
    if confirm.strip().lower() != "reset":
        raise AccessError("validation_error", "Type reset to confirm.")
    org = conn.execute(
        text("SELECT kind, data_generation FROM organisations WHERE org_id=:o FOR UPDATE"), {"o": by.org_id}
    ).one()
    if org.kind not in _RESETTABLE:  # the demo organisation has its own reset (CON-09, G-26)
        raise AccessError("reset_not_allowed", "This organisation's data can't be reset here.", status=409)
    busy = conn.execute(
        text(
            "SELECT count(*) FROM payment_intents p WHERE p.org_id=:o AND (p.status = ANY(:s) "
            "OR (p.status = 'HELD' AND p.held_reason = 'KILL_SWITCH_ENGAGED') OR EXISTS "
            "(SELECT 1 FROM attempts a WHERE a.org_id = p.org_id AND a.payment_id = p.id "
            "AND a.status IN ('CREATED', 'SUBMITTED', 'UNKNOWN')))"
        ),
        {"o": by.org_id, "s": list(_SENDING)},
    ).scalar_one()
    if int(busy):
        raise AccessError(
            "payouts_in_flight",
            f"{int(busy)} payout(s) can still be sent or are waiting for the rail. Reset once they are "
            "confirmed, failed or cancelled.",
            status=409,
        )
    new = int(org.data_generation) + 1
    conn.execute(
        text("UPDATE organisations SET data_generation=:g WHERE org_id=:o"), {"g": new, "o": by.org_id}
    )
    append(
        conn,
        clock,
        org_id=by.org_id,
        actor=by.actor,
        kind="sandbox.reset",
        subject_id=by.org_id,
        payload={"from_generation": int(org.data_generation), "to_generation": new, "via": "dashboard"},
    )
    return new


def recent_payouts(conn: Connection, org_id: str, limit: int = 15) -> list[dict[str, Any]]:
    """The latest payouts and their attempts: rail, outcome and, on a real test network, an explorer link."""
    pays = conn.execute(
        text(
            "SELECT id, status, amount_minor, currency, reference, created_at FROM payment_intents "
            "WHERE org_id=:o AND generation = (SELECT data_generation FROM organisations WHERE org_id = :o) "
            "ORDER BY created_at DESC, id DESC LIMIT :n"
        ),
        {"o": org_id, "n": limit},
    ).all()
    ids = [p.id for p in pays]
    atts = conn.execute(
        text(
            "SELECT payment_id, attempt_no, rail_id, status, tx_hash, explorer_url, "
            "left(raw_tx, 4) = 'sim:' AS simulated FROM attempts WHERE org_id=:o AND payment_id = ANY(:p) "
            "ORDER BY attempt_no"
        ),
        {"o": org_id, "p": ids},
    ).all()
    by_pay: dict[str, list[Any]] = {}
    for a in atts:
        by_pay.setdefault(a.payment_id, []).append(a)
    return [{"p": p, "attempts": by_pay.get(p.id, [])} for p in pays]
