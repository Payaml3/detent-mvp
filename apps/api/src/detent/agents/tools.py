"""The instruction agent's tools (AGT-03, spec/05).

Every tool reads; the only one that writes is ``propose_payment_intent``, and it goes through the
public API with the agent's own key (scope ``intents:create``, bound to one mandate). It never touches
the decision, execution or approval code: the policy decides what happens to the proposal.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from sqlalchemy import Connection, text

TOOLS: dict[str, dict[str, Any]] = {
    "find_counterparty": {
        "name": "find_counterparty",
        "description": "Look up registered payees whose name contains the given text. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "get_destinations": {
        "name": "get_destinations",
        "description": "List a registered payee's payout destinations (network and address). Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {"counterparty_id": {"type": "string"}},
            "required": ["counterparty_id"],
            "additionalProperties": False,
        },
    },
    "get_mandate": {
        "name": "get_mandate",
        "description": "Read the scope of the mandate the agent works under. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {"mandate_id": {"type": "string"}},
            "required": ["mandate_id"],
            "additionalProperties": False,
        },
    },
}


class HttpPoster(Protocol):
    """Any HTTP client with ``post`` (httpx.Client, or an in-process test client of the same app)."""

    def post(self, url: str, *, json: Any, headers: dict[str, str]) -> Any: ...


WRITE_TOOLS = {"propose_payment_intent"}  # not offered to the model; called by code after a person's review


def run_tool(conn: Connection, org_id: str, name: str, args: dict[str, Any]) -> str:
    if name == "find_counterparty":
        rows = conn.execute(
            text(
                "SELECT id, name, kyb_status, allowlisted FROM counterparties WHERE org_id=:o AND name "
                "ILIKE :n "
                "ORDER BY name LIMIT 10"
            ),
            {"o": org_id, "n": f"%{args.get('name', '')}%"},
        ).all()
        return json.dumps(
            [{"counterparty_id": r.id, "name": r.name, "kyb_status": r.kyb_status} for r in rows]
        )
    if name == "get_destinations":
        rows = conn.execute(
            text(
                "SELECT id, network, address, account_masked FROM destinations WHERE org_id=:o AND "
                "counterparty_id=:c"
            ),
            {"o": org_id, "c": args.get("counterparty_id")},
        ).all()
        return json.dumps(
            [
                {"destination_id": r.id, "network": r.network, "address": r.address or r.account_masked}
                for r in rows
            ]
        )
    if name == "get_mandate":
        row = conn.execute(
            text("SELECT payload FROM mandates WHERE org_id=:o AND id=:m"),
            {"o": org_id, "m": args.get("mandate_id")},
        ).scalar_one_or_none()
        return json.dumps(row["scope"] if row else None)
    return json.dumps({"error": f"unknown tool {name}"})


def propose_payment_intent(
    http: HttpPoster, *, agent_key: str, proposal_id: str, body: dict[str, Any]
) -> Any:
    """The agent's only write: POST /v1/payment_intents with its own key. The Idempotency-Key is the
    proposal's ID, so submitting the same proposal twice creates one intent."""
    return http.post(
        "/v1/payment_intents",
        json=body,
        headers={"Authorization": f"Bearer {agent_key}", "Idempotency-Key": f"proposal:{proposal_id}"},
    )
