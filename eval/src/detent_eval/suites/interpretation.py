"""EVL-04: the instruction agent on 30 labelled invoices.

The six invoices in ``fixtures/invoices/expected-outputs.yaml`` plus the 24 in ``interpretation-set.yaml``.
Each is read by the instruction agent (the recorded stand-in unless the run is ``--live``) and scored on:

- field accuracy: expected field values matched, over all expected fields;
- flag recall: expected flags raised, over all expected flags;
- invented values: a non-empty field whose value is nowhere in the document after the code-side checks.
  Must be 0: the gate fails otherwise;
- the canonical invoice, read ``runs`` times (10): every run must match every field and raise no flag.

With stand-ins the scores show that the code-side checks hold, not how good a model is; the report says so.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import yaml
from detent.settings import REPO_ROOT

INVOICES = REPO_ROOT / "fixtures" / "invoices"
SPAN_FIELDS = ("payee_name", "amount", "currency", "network", "wallet_address", "invoice_number", "due_date")


def load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    first = yaml.safe_load((INVOICES / "expected-outputs.yaml").read_text())
    for name, exp in first.items():
        cases.append(
            {
                "name": name,
                "kind": "canonical" if "canonical" in name else "core",
                "fields": exp.get("fields") or {},
                "flags": exp.get("flags") or [],
                "runs": int(exp.get("runs", 1)),
            }
        )
    extra = yaml.safe_load((INVOICES / "interpretation-set.yaml").read_text())
    for name, exp in extra.items():
        cases.append(
            {
                "name": name,
                "kind": exp.get("kind", "other"),
                "fields": exp.get("fields") or {},
                "flags": exp.get("flags") or [],
                "runs": int(exp.get("runs", 1)),
            }
        )
    return cases


def _fill(v: Any, ph: dict[str, str]) -> Any:
    if isinstance(v, str):
        for k, val in ph.items():
            v = v.replace("{{" + k + "}}", val)
    return v


def _same(want: Any, got: Any) -> bool:
    if want is None or got is None:
        return want is None and got is None
    return str(want).strip().lower() == str(got).strip().lower()


def score_run(
    case: dict[str, Any], doc: str, proposal: dict[str, Any], flags: list[str], ph: dict[str, str]
) -> dict[str, Any]:
    fields_ok = 0
    misses = []
    for k, want in case["fields"].items():
        got = (proposal.get(k) or {}).get("value")
        if _same(_fill(want, ph), got):
            fields_ok += 1
        else:
            misses.append({"field": k, "expected": _fill(want, ph), "got": got})
    flags_hit = [f for f in case["flags"] if f in flags]
    invented = []
    for k in SPAN_FIELDS:
        cell = proposal.get(k) or {}
        if cell.get("value") is not None and cell.get("source_span") is None:
            invented.append({"field": k, "value": cell.get("value")})
    exact = not misses and set(flags) == set(case["flags"])
    return {
        "fields": len(case["fields"]),
        "fields_ok": fields_ok,
        "misses": misses,
        "flags_expected": len(case["flags"]),
        "flags_hit": len(flags_hit),
        "flags": flags,
        "invented": invented,
        "exact": exact,
    }


def run(world: Any, *, progress: bool = True) -> dict[str, Any]:
    from detent.agents.instruction import fixture_placeholders, propose_from_invoice

    from detent_eval.harness import close_env, make_env
    from detent_eval.llm import client_for, source_label

    env = make_env(world, {"id": "interpretation", "setup": {"bank": False}}, seed=4)
    try:
        with env.engine.connect() as c:
            ph = fixture_placeholders(c, env.org_id)
        results = []
        for case in load_cases():
            doc = _fill((INVOICES / case["name"]).read_text(), ph)
            runs = []
            for _ in range(case["runs"]):
                llm, model = client_for(env, ph, None)
                p = propose_from_invoice(
                    env.engine,
                    env.clock,
                    org_id=env.org_id,
                    document=doc,
                    mandate_id="mnd_demo_ap_agent",
                    llm=llm,
                    model=model,
                    daily_token_budget=50_000_000,
                )
                runs.append(score_run(case, doc, p.proposal, sorted({f["code"] for f in p.flags}), ph))
            r = {
                "name": case["name"],
                "kind": case["kind"],
                "runs": runs,
                "exact_runs": sum(1 for x in runs if x["exact"]),
            }
            results.append(r)
            if progress:
                ok = "ok " if r["exact_runs"] == len(runs) else "DIFF"
                print(
                    f"  {ok} {case['name']:<36} {case['kind']:<22} {r['exact_runs']}/{len(runs)} exact",
                    flush=True,
                )
    finally:
        close_env(env)
    return summarise(results, source_label())


def summarise(results: list[dict[str, Any]], answers: str) -> dict[str, Any]:
    tot: defaultdict[str, int] = defaultdict(int)
    per_kind: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        first = r["runs"][0]
        for k in ("fields", "fields_ok", "flags_expected", "flags_hit"):
            tot[k] += first[k]
            per_kind[r["kind"]][k] += first[k]
        per_kind[r["kind"]]["count"] += 1
        tot["invented"] += sum(len(x["invented"]) for x in r["runs"])
    canon = next((r for r in results if r["kind"] == "canonical"), None)
    return {
        "count": len(results),
        "agent_answers": answers,
        "field_accuracy": round(tot["fields_ok"] / tot["fields"], 4) if tot["fields"] else None,
        "flag_recall": round(tot["flags_hit"] / tot["flags_expected"], 4) if tot["flags_expected"] else None,
        "invented_values": tot["invented"],
        "canonical": {"runs": len(canon["runs"]), "correct": canon["exact_runs"]} if canon else {},
        "per_kind": {k: dict(v) for k, v in sorted(per_kind.items())},
        "cases": results,
    }
