"""Replay any payment (AUD-02).

Each recorded decision is evaluated again from what was stored at the time: the inputs snapshot (the
typed facts) and the exact rule version, by its stored YAML and content hash. An approval re-run also
replays the approval rule (D-01) with the reasons the approver saw and the snapshot before it. An
agent-proposed payment shows the stored agent output; replay never calls a model.

The replayed outcome and checks must equal the recorded ones. A mismatch raises an alert: an audit
event, an incident row and an error log line. Nothing about the payment changes.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.domain.ids import Prefix, new_id
from detent.domain.money import Currency, Money
from detent.policy.engine import Evaluation, evaluate
from detent.policy.facts import (
    CounterpartyFacts,
    DestinationFacts,
    Facts,
    MandateFacts,
    ScreeningResult,
    TravelRuleFacts,
    Unavailable,
)
from detent.policy.schema import load_ruleset

log = logging.getLogger("detent.replay")


class NotReplayable(ValueError):
    pass


def _money(v: Any) -> Money | None:
    return None if v is None else Money.parse(v["amount"], Currency(v["currency"]))


def _dt(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def _unavailable(v: Any) -> bool:
    return isinstance(v, dict) and set(v) == {"dependency", "error"}


def facts_from_json(f: dict[str, Any]) -> Facts:
    """The inverse of the decision snapshot (``intents.service._jsonable``)."""
    cp = f["counterparty"]
    de = f["destination"]
    scr = f["screening"]
    tr = f["travel_rule"]
    md = f.get("mandate")

    def used(v: Any) -> Money | Unavailable:
        return Unavailable(**v) if _unavailable(v) else _money(v)  # type: ignore[return-value]

    return Facts(
        now=_dt(f["now"]),
        source=f["source"],
        amount=_money(f["amount"]),  # type: ignore[arg-type]
        network=f["network"],
        counterparty=CounterpartyFacts(
            cp["id"],
            cp["name"],
            cp["kyb_status"],
            cp["allowlisted"],
            int(cp["payment_count"]),
            _money(cp.get("median")),
        ),
        destination=DestinationFacts(
            de["id"],
            de["registered"],
            de["address"],
            de["account_masked"],
            _dt(de["first_seen_at"]),
            _dt(de["last_changed_at"]),
            de.get("last_changed_by"),
            de.get("previous"),
        ),
        screening=Unavailable(**scr)
        if _unavailable(scr)
        else ScreeningResult(scr["hit"], scr.get("matched"), scr.get("field")),
        travel_rule=Unavailable(**tr)
        if _unavailable(tr)
        else TravelRuleFacts(tr["originator"], tr["beneficiary"], tr.get("supplied")),
        used_today_platform=used(f["used_today_platform"]),
        used_today_counterparty=used(f["used_today_counterparty"]),
        recent_block_id=f.get("recent_block_id"),
        mandate=None
        if md is None
        else Unavailable(**md)
        if _unavailable(md)
        else MandateFacts(md["id"], md["valid"], md.get("reason"), md.get("evidence")),
    )


def _agent_output(conn: Connection, org_id: str, payment_id: str) -> dict[str, Any] | None:
    r = conn.execute(
        text(
            "SELECT id, parsed, source, model, served_model FROM agent_calls WHERE org_id=:o AND "
            "kind='instruction' "
            "AND payment_id=:p ORDER BY created_at, id LIMIT 1"
        ),
        {"o": org_id, "p": payment_id},
    ).one_or_none()
    if r is None:
        return None
    return {
        "agent_call_id": r.id,
        "source": r.source,
        "model": r.served_model or r.model,
        "proposal": r.parsed.get("proposal"),
        "flags": [f["code"] for f in r.parsed.get("flags", [])],
        "model_called_during_replay": False,
    }


def replay_payment(engine: Engine, clock: Clock, *, org_id: str, payment_id: str) -> dict[str, Any]:
    from detent.intents.service import approval_covers

    with engine.connect() as conn:
        p = conn.execute(
            text(
                "SELECT id, status, source FROM payment_intents WHERE org_id=:o AND id=:p AND "
                "generation = (SELECT data_generation FROM organisations WHERE org_id = :o)"
            ),
            {"o": org_id, "p": payment_id},
        ).one_or_none()
        if p is None:
            raise NotReplayable(f"no payment {payment_id}")
        decisions = conn.execute(
            text(
                "SELECT d.id, d.outcome, d.checks, d.inputs_snapshot, d.approved_reasons, "
                "d.decided_at, d.policy_hash, "
                "v.version, v.yaml, v.content_hash FROM decisions d JOIN policy_versions v ON "
                "v.org_id=d.org_id AND "
                "v.id=d.policy_version_id WHERE d.org_id=:o AND d.payment_id=:p ORDER BY (SELECT "
                "min(a.seq) FROM audit_events a WHERE a.org_id=d.org_id "
                "AND a.kind='decision.made' AND a.payload->>'decision_id' = d.id), d.decided_at, d.id"
            ),
            {"o": org_id, "p": payment_id},
        ).all()
        agent = _agent_output(conn, org_id, payment_id) if p.source == "agent" else None
    steps: list[dict[str, Any]] = []
    before: dict[str, Any] | None = None
    for d in decisions:
        snap = d.inputs_snapshot or {}
        step: dict[str, Any] = {
            "decision_id": d.id,
            "decided_at": d.decided_at.isoformat().replace("+00:00", "Z"),
            "rule_version": d.version,
            "recorded": {"outcome": d.outcome, "checks": d.checks},
        }
        if "facts" not in snap:  # the decision itself failed: it was recorded as a system escalation
            step |= {
                "replayed": None,
                "match": d.outcome == "ESCALATE",
                "note": "decision failed when made; no facts to replay",
            }
            steps.append(step)
            continue
        rules = load_ruleset(d.yaml)
        if rules.content_hash != d.policy_hash:
            step |= {"replayed": None, "match": False, "note": "stored rule version does not match its hash"}
            steps.append(step)
            continue
        result: Evaluation = evaluate(facts_from_json(snap["facts"]), rules)
        if d.approved_reasons:
            covered, _ = approval_covers(
                result, list(d.approved_reasons), (before or {}).get("facts"), snap["facts"]
            )
            if covered:
                result = Evaluation("EXECUTE", result.checks)
        replayed = {"outcome": result.outcome, "checks": [c.to_json() for c in result.checks]}
        step |= {"replayed": replayed, "match": replayed == step["recorded"]}
        steps.append(step)
        before = snap
    ok = all(s["match"] for s in steps) and bool(steps)
    out = {
        "payment_id": payment_id,
        "status": p.status,
        "match": ok,
        "steps": steps,
        "agent": agent,
        "model_called": False,
    }
    if not ok:
        _alert(engine, clock, org_id, payment_id, steps)
    return out


def _alert(engine: Engine, clock: Clock, org_id: str, payment_id: str, steps: list[dict[str, Any]]) -> None:
    bad = [s["decision_id"] for s in steps if not s["match"]] or ["no decisions"]
    log.error("replay mismatch", extra={"for_payment": payment_id, "decisions": bad})
    import json

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO incidents (id, org_id, severity, trigger, opened_at, subject_id, detail) "
                "VALUES (:id, :o, 2, 'replay_mismatch', :t, :p, CAST(:d AS jsonb))"
            ),
            {
                "id": new_id(Prefix.INC, clock.now()),
                "o": org_id,
                "t": clock.now(),
                "p": payment_id,
                "d": json.dumps({"decisions": bad}),
            },
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=Actor.system("replay"),
            kind="replay.mismatch",
            subject_id=payment_id,
            payload={"decisions": bad},
        )
