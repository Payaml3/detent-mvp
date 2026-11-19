"""EVL-05: agreement with 50 synthetic labelled cases (``eval/data/agreement-set.yaml``).

Two figures, reported separately:

- decision agreement: the rules' first decision (EXECUTE, ESCALATE or BLOCK) against the label;
- recommendation agreement: on the cases both the rules and the label escalate, the investigation agent's
  recommendation (approve, reject, needs_information) against the label's resolution.

The labels are synthetic, written by hand; the agent answers are recorded stand-ins unless ``--live``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import yaml
from detent.settings import REPO_ROOT

DATA = REPO_ROOT / "eval" / "data" / "agreement-set.yaml"


def run(world: Any, *, progress: bool = True) -> dict[str, Any]:
    from detent_eval.harness import close_env, make_env
    from detent_eval.llm import source_label
    from detent_eval.steps import STEPS, open_case

    cases = yaml.safe_load(DATA.read_text())["cases"]
    rows = []
    for i, case in enumerate(cases):
        setup = {"bank": False, **(case.get("setup") or {})}
        env = make_env(world, {"id": case["id"], "setup": setup}, seed=1000 + i)
        try:
            intent = dict(case["intent"])
            if intent.pop("revoke_mandate", False):
                STEPS["mandate_revoke"](env, {})
            out = STEPS["intent"](env, {**intent, "save": "p1"})
            pid = env.saved.get("p1")
            outcome = None
            if pid:
                from sqlalchemy import text

                with env.engine.connect() as c:
                    outcome = c.execute(
                        text(
                            "SELECT outcome FROM decisions WHERE org_id=:o AND payment_id=:p "
                            "ORDER BY decided_at, id "
                            "LIMIT 1"
                        ),
                        {"o": env.org_id, "p": pid},
                    ).scalar_one_or_none()
            rec = None
            if pid and outcome == "ESCALATE" and open_case(env, pid):
                rec = STEPS["investigate"](env, {"payment": pid}).get("recommendation")
            label = case["label"]
            rows.append(
                {
                    "id": case["id"],
                    "description": case["description"],
                    "label": label,
                    "decision": outcome,
                    "reasons": out.get("reasons"),
                    "recommendation": rec,
                    "decision_agrees": outcome == label["decision"],
                    "recommendation_agrees": (rec == label.get("resolution"))
                    if rec and label.get("resolution")
                    else None,
                }
            )
        finally:
            close_env(env)
        if progress:
            r = rows[-1]
            mark = "ok " if r["decision_agrees"] else "DIFF"
            print(
                f"  {mark} {r['id']}  rules {r['decision']!s:<8} label {r['label']['decision']:<8} "
                f"agent {r['recommendation'] or '-':<17} label {r['label'].get('resolution') or '-'}",
                flush=True,
            )
    return summarise(rows, source_label())


def summarise(rows: list[dict[str, Any]], answers: str) -> dict[str, Any]:
    dec = [r for r in rows if r["decision"] is not None]
    recs = [r for r in rows if r["recommendation_agrees"] is not None]
    confusion = Counter(f"{r['label']['decision']}->{r['decision']}" for r in dec)
    return {
        "count": len(rows),
        "synthetic": True,
        "agent_answers": answers,
        "decision_agreement": round(sum(r["decision_agrees"] for r in dec) / len(dec), 4) if dec else None,
        "decision_cases": len(dec),
        "recommendation_agreement": round(sum(bool(r["recommendation_agrees"]) for r in recs) / len(recs), 4)
        if recs
        else None,
        "recommendation_cases": len(recs),
        "confusion": dict(sorted(confusion.items())),
        "cases": rows,
    }
