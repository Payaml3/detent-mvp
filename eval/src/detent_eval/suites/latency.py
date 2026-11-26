"""EVL-08: decision latency, rules-only and with the agent's investigation.

- rules-only: ``POST /v1/decisions`` (decide, never send) through the API, end to end in-process: key
  check, typed facts, policy, audit write. A mix of EXECUTE, ESCALATE and BLOCK outcomes.
- agent path: the same decision for an escalated payment, then the investigation agent on its case.
  With the recorded stand-in this measures DekernAI's own work around the model (evidence gathering, tool
  calls, checks, storage), not model time; ``--live`` includes the model's own latency.

Measured on the CI runner against a local Postgres; it says nothing about production hardware.
"""

from __future__ import annotations

import time
from typing import Any

N_RULES = 200
N_AGENT = 40
MIX = [
    ("cpt_local", "45.00"),
    ("cpt_local", "15000.00"),
    ("cpt_flagged", "500.00"),
    ("cpt_nova", "200.00"),
    ("cpt_local", "1200.00"),
]


def _pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(q * len(s)))], 1)


def run(world: Any, *, progress: bool = True) -> dict[str, Any]:
    from detent_eval.harness import close_env, make_env
    from detent_eval.llm import source_label
    from detent_eval.steps import STEPS

    env = make_env(world, {"id": "latency", "setup": {"bank": False}}, seed=8)
    try:
        STEPS["decision"](env, {"amount": "10.00"})  # warm up the app, the pool and the policy cache
        rules: list[float] = []
        for i in range(N_RULES):
            cpt, amount = MIX[i % len(MIX)]
            t0 = time.perf_counter()
            STEPS["decision"](env, {"cpt": cpt, "amount": amount})
            rules.append((time.perf_counter() - t0) * 1000)
        agent: list[float] = []
        for _ in range(N_AGENT):
            t0 = time.perf_counter()
            STEPS["intent"](env, {"amount": "15000.00", "save": "p"})
            STEPS["investigate"](env, {"payment": "p"})
            agent.append((time.perf_counter() - t0) * 1000)
    finally:
        close_env(env)
    out: dict[str, Any] = {
        "count": N_RULES + N_AGENT,
        "agent_answers": source_label(),
        "rules_only_ms": {"n": N_RULES, "p50": _pct(rules, 0.50), "p95": _pct(rules, 0.95)},
        "agent_path_ms": {"n": N_AGENT, "p50": _pct(agent, 0.50), "p95": _pct(agent, 0.95)},
        "environment": "in-process API client, local Postgres 16, CI-class machine; not production figures",
    }
    if progress:
        print(
            f"  rules-only p50 {out['rules_only_ms']['p50']} ms, p95 {out['rules_only_ms']['p95']} ms; "
            f"agent path p50 {out['agent_path_ms']['p50']} ms, p95 {out['agent_path_ms']['p95']} ms",
            flush=True,
        )
    return out
