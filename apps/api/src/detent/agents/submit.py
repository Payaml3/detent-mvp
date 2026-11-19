"""From proposal to intent (AGT-02, AGT-03).

A proposal with flags can't be submitted until a person resolves each one: they supply or confirm the
flagged values, with a note, and the resolution is audited. Submission is the agent's only write and goes
through the public API with the agent's own key, so the API's scope and mandate checks apply and the
policy decides. The proposal's ID is the idempotency key.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy import Engine, text

from detent.agents.tools import HttpPoster, propose_payment_intent
from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.domain.money import Money, MoneyError
from detent.domain.roles import Role, allowed

REQUIRED = ("counterparty_id", "amount", "currency", "network", "wallet_address")
_VALIDATE: dict[str, Callable[[str], bool]] = {
    "network": lambda v: v in ("base-sepolia", "eth-sepolia", "local-evm", "simchain"),
    "wallet_address": lambda v: re.fullmatch(r"0x[0-9a-fA-F]{40}", v) is not None,
    "currency": lambda v: v in ("USDC",),
    "counterparty_id": lambda v: v.startswith("cpt_"),
}


class NotReady(ValueError):
    pass


def _load(engine: Engine, org_id: str, proposal_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT id, status, parsed, resolution, payment_id FROM agent_calls WHERE org_id=:o AND "
                "id=:i "
                "AND kind='instruction'"
            ),
            {"o": org_id, "i": proposal_id},
        ).one()


def resolve_flags(
    engine: Engine,
    clock: Clock,
    *,
    org_id: str,
    proposal_id: str,
    actor: Actor,
    values: dict[str, str],
    note: str = "",
) -> None:
    """A person resolves the flags: every flagged field that is empty must be supplied; others are "
    "confirmed."""
    if not allowed("exception.approve", Role(actor.role or "admin")):
        raise PermissionError(f"{actor.role} may not resolve a proposal's flags")
    row = _load(engine, org_id, proposal_id)
    if row.status == "needs_human":
        raise NotReady(
            "this proposal needs a person to enter the payment; the agent produced no usable fields"
        )
    prop = row.parsed["proposal"]
    flagged = {f for fl in row.parsed["flags"] for f in fl["fields"]}
    missing = [f for f in REQUIRED if f in flagged and not prop[f]["value"] and not values.get(f)]
    if missing:
        raise ValueError(f"supply a value for: {', '.join(missing)}")
    for k, v in values.items():
        if k not in prop:
            raise ValueError(f"unknown field {k}")
        if k == "amount":
            try:
                Money.parse(v, prop["currency"]["value"] or "USDC")
            except (MoneyError, ValueError) as exc:
                raise ValueError(f"amount: {exc}") from exc
        elif k in _VALIDATE and not _VALIDATE[k](v):
            raise ValueError(f"{k}: invalid value")
    resolution = {"values": values, "note": note, "flags": [f["code"] for f in row.parsed["flags"]]}
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE agent_calls SET resolution=CAST(:r AS jsonb), resolved_by=:a WHERE org_id=:o AND "
                "id=:i"
            ),
            {"r": json.dumps(resolution), "a": actor.id, "o": org_id, "i": proposal_id},
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="agent.flags_resolved",
            subject_id=proposal_id,
            payload=resolution,
        )


def intent_body(engine: Engine, org_id: str, proposal_id: str) -> dict[str, Any]:
    row = _load(engine, org_id, proposal_id)
    d = row.parsed
    if row.status == "needs_human":
        raise NotReady("needs_human: " + ", ".join(f["code"] for f in d["flags"]))
    if d["flags"] and row.resolution is None:
        raise NotReady("unresolved flags: " + ", ".join(f["code"] for f in d["flags"]))
    values = {k: v["value"] for k, v in d["proposal"].items()}
    values.update((row.resolution or {}).get("values", {}))
    missing = [f for f in REQUIRED if not values.get(f)]
    if missing:
        raise NotReady("missing values: " + ", ".join(missing))
    return {
        "kind": "payout",
        "source": "agent",
        "mandate_id": d.get("mandate_id"),
        "counterparty_id": values["counterparty_id"],
        "destination": {
            "kind": "evm_wallet",
            "network": values["network"],
            "address": values["wallet_address"],
        },
        "amount": {"amount": values["amount"], "currency": values["currency"]},
        "reference": values.get("invoice_number"),
        "notes": f"Proposed by the instruction agent ({proposal_id}) from an invoice.",
    }


def submit_proposal(
    engine: Engine, clock: Clock, http: HttpPoster, *, agent_key: str, org_id: str, proposal_id: str
) -> Any:
    body = intent_body(engine, org_id, proposal_id)
    r = propose_payment_intent(http, agent_key=agent_key, proposal_id=proposal_id, body=body)
    if r.status_code in (200, 201):
        pid = r.json()["id"]
        with engine.begin() as conn:
            changed = conn.execute(
                text(
                    "UPDATE agent_calls SET status='submitted', payment_id=:p WHERE org_id=:o AND id=:i "
                    "AND payment_id IS NULL RETURNING id"
                ),
                {"p": pid, "o": org_id, "i": proposal_id},
            ).scalar_one_or_none()
            if changed:
                append(
                    conn,
                    clock,
                    org_id=org_id,
                    actor=Actor.system("instruction_agent"),
                    kind="agent.proposal_submitted",
                    subject_id=proposal_id,
                    payload={"payment_id": pid},
                )
    return r
