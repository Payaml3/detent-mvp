"""Scenario packs per platform type (DEM-06): a payout platform, a crypto service provider and a marketplace.

A pack is one fixture in ``fixtures/packs/``: the platform, its users, counterparties and destinations, rule
overrides on the default rule set, and a short batch of payouts with the outcome each should get. The founder
picks one when resetting the demo; the new generation is seeded from it. The default pack is the original
fixtures (the 10-minute demo in spec/11 uses it). Every name is fictional.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from sqlalchemy import Connection, text

from detent.audit.log import Actor
from detent.settings import REPO_ROOT

if TYPE_CHECKING:
    from detent.runtime import Runtime

PACKS_DIR = REPO_ROOT / "fixtures" / "packs"
DEFAULT_FIXTURE = REPO_ROOT / "fixtures" / "counterparties.yaml"
DEFAULT_POLICY = REPO_ROOT / "fixtures" / "policy" / "default-policy.yaml"
DEFAULT = "default"


class PackError(ValueError):
    pass


@dataclass(frozen=True)
class Pack:
    id: str
    label: str
    description: str
    fixture: Path
    data: dict[str, Any]

    @property
    def batch(self) -> list[dict[str, Any]]:
        return list(self.data.get("batch") or [])


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def packs() -> list[Pack]:
    out = [
        Pack(
            DEFAULT,
            "Default demo",
            "The 10-minute demo (spec/11): B2B payouts and deposits across three rails.",
            DEFAULT_FIXTURE,
            yaml.safe_load(DEFAULT_FIXTURE.read_text()),
        )
    ]
    for p in sorted(PACKS_DIR.glob("*.yaml")):
        data = yaml.safe_load(p.read_text())
        out.append(Pack(data["id"], data["label"], data["description"], p, data))
    return out


def load(pack_id: str) -> Pack:
    for p in packs():
        if p.id == pack_id:
            return p
    raise PackError(f"unknown scenario pack {pack_id!r}")


def policy_text(pack: Pack) -> str:
    """The default rule set with the pack's overrides (a pack never loosens what it doesn't name)."""
    base = yaml.safe_load(DEFAULT_POLICY.read_text())
    over = pack.data.get("policy_overrides") or {}
    if not over:
        return DEFAULT_POLICY.read_text()
    merged = _merge(base, over)
    merged["platform"] = pack.id
    return str(yaml.safe_dump(merged, sort_keys=False))


def current_pack(conn: Connection, org_id: str) -> str:
    """The pack the organisation was seeded from (recorded on its ``demo.reset`` event)."""
    p = conn.execute(
        text(
            "SELECT payload->>'pack' FROM audit_events WHERE org_id=:o AND kind='demo.reset' "
            "ORDER BY seq DESC LIMIT 1"
        ),
        {"o": org_id},
    ).scalar_one_or_none()
    return str(p) if p else DEFAULT


def _body(pack: Pack, p: dict[str, Any]) -> dict[str, Any]:
    cpt = next(c for c in pack.data["counterparties"] if c["id"] == p["counterparty"])
    d = next((x for x in cpt["destinations"] if x["network"] == p.get("network")), cpt["destinations"][0])
    return {
        "kind": "payout",
        "source": "platform",
        "counterparty_id": p["counterparty"],
        "destination": {"kind": d["kind"], "network": d["network"], "destination_id": d["id"]},
        "amount": {"amount": p["amount"], "currency": p["currency"]},
        "reference": f"{pack.id} batch {p['ref']}",
    }


def run_pack_batch(rt: Runtime, org_id: str, actor: Actor, pack_id: str) -> list[dict[str, Any]]:
    """Submits the pack's batch through the normal intent service. Returns each payout's expected and actual
    outcome. Idempotent: the same pack and reference reuse the same idempotency key."""
    from detent.intents.service import IntentRequest, submit_intent
    from detent.policy.screening import MockScreening

    pack = load(pack_id)
    screening = MockScreening.from_fixture()
    out = []
    for p in pack.batch:
        _, body = submit_intent(
            rt.engine,
            rt.clock,
            org_id=org_id,
            actor_id=actor.id,
            actor_role=actor.role or "platform",
            idempotency_key=f"pack-{pack.id}-{p['ref']}",
            request=IntentRequest.model_validate(_body(pack, p)),
            decision_only=False,
            screening=screening,
        )
        decision = body.get("decision") or {}
        out.append(
            {
                "ref": p["ref"],
                "id": body.get("id"),
                "status": body.get("status"),
                "expected": p["expect"],
                "outcome": decision.get("outcome"),
                "reasons": decision.get("reasons") or [],
            }
        )
    return out
