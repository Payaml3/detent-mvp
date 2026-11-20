"""Build the founder's live pages (beside the roadmap) from the repository's sources of truth.

Usage: python tools/build_pages.py                 # writes founder/mvp-scope.md and founder/user-journey.md
       python tools/build_pages.py --check         # exit 1 if either page is out of date
       python tools/build_pages.py --html build    # also writes build/mvp-scope.html and build/user-journey.html
       python tools/build_pages.py --snapshot eval/out/results.json   # refresh eval/results/latest.json

MVP scope and proof reads spec/00-product-context.md (MVP definition, launch criteria L1 to L8, what can be
rough, out of scope), backlog/stories.yaml (criteria done for every story that traces to an L code),
backlog/model-items.yaml (MVP scope triage) and eval/results/latest.json (the last full evaluation run).

User journey reads founder/pages/user-journey.yaml (the steps and the stories behind each),
backlog/stories.yaml (built status), spec/11-demo-script.md (the 10-minute timeline) and
spec/00-product-context.md (personas).

Nothing here is hand-edited: change a source, then run `make pages`. The Markdown carries no generation
date, so the CI check only fails when a source changed.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_roadmap import CSS as ROADMAP_CSS
from build_roadmap import _clean, _stamp, _table_rows

ROOT = Path(__file__).resolve().parent.parent
SPEC00 = ROOT / "spec" / "00-product-context.md"
SPEC11 = ROOT / "spec" / "11-demo-script.md"
JOURNEY = ROOT / "founder" / "pages" / "user-journey.yaml"
RESULTS = ROOT / "eval" / "results" / "latest.json"
OUT_SCOPE = ROOT / "founder" / "mvp-scope.md"
OUT_JOURNEY = ROOT / "founder" / "user-journey.md"
LAYERS = ("Decision", "Orchestration", "Operations")
e = html.escape


# ---------------------------------------------------------------- sources


def load_stories() -> dict[str, dict[str, Any]]:
    raw = yaml.safe_load((ROOT / "backlog" / "stories.yaml").read_text())["stories"]
    return {s["id"]: s for s in raw}


def story_counts(stories: dict[str, dict[str, Any]], ids: list[str]) -> tuple[int, int]:
    done = sum(len(stories[i].get("done", [])) for i in ids)
    total = sum(len(stories[i]["ac"]) for i in ids)
    return done, total


def state(done: int, total: int) -> str:
    if total and done == total:
        return "built"
    return "partly" if done else "todo"


STATE_LABEL = {"built": "Built and tested", "partly": "Partly built", "todo": "Not built"}


def _section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def load_scope() -> dict[str, Any]:
    text = SPEC00.read_text()
    mvp = _section(text, "MVP definition")
    steps = [_clean(m) for m in re.findall(r"^\d+\.\s+(.*)$", mvp, re.M)]
    intro = next((ln for ln in mvp.splitlines() if ln.strip() and not ln[0].isdigit()), "")
    then = next((ln for ln in mvp.splitlines() if ln.startswith("Then ")), "")
    launch = _section(text, "Launch criteria (from mvp-scope)")
    criteria = [
        (c, _clean(t)[:1].upper() + _clean(t)[1:])
        for c, t in re.findall(r"^- \*\*(L\d+):\*\*\s+(.*)$", launch, re.M)
    ]
    rough_m = re.search(r"\*\*Can be rough:\*\*\s*(.*)", launch)
    rough = [_clean(x).rstrip(".") for x in re.split(r";\s*", rough_m.group(1))] if rough_m else []
    out = _section(text, "Out of scope for this MVP")
    out_items = [_clean(x).rstrip(".") for x in re.split(r";\s*", out.split("\n\n")[0])] if out else []
    return {
        "intro": _clean(intro),
        "steps": steps,
        "then": _clean(then),
        "criteria": criteria,
        "rough": rough,
        "out": out_items,
    }


def load_triage() -> list[tuple[str, str, str]]:
    items = yaml.safe_load((ROOT / "backlog" / "model-items.yaml").read_text())
    label = {
        "mvp": "In the MVP",
        "partly": "Partly in the MVP",
        "later": "Later",
        "non-software": "Not software",
    }
    return [
        (i["code"], i["item"], label.get(i["status"], i["status"]))
        for i in items
        if str(i["code"]).startswith("MVP.")
    ]


def load_results() -> dict[str, Any] | None:
    return json.loads(RESULTS.read_text()) if RESULTS.exists() else None


def evidence(code: str, r: dict[str, Any] | None) -> str:
    """The measured figure behind a launch criterion, from the last full evaluation run."""
    if not r:
        return ""
    a, f, i, rec = (r.get(k) or {} for k in ("attacks", "faults", "interpretation", "reconciliation"))
    figures = {
        "L1": i
        and f"Canonical invoice {i.get('canonical_correct')}/{i.get('canonical_runs')} runs correct; "
        f"{i.get('invented_values')} invented values across {i.get('count')} invoices",
        "L2": a
        and f"{a.get('unauthorised_executions')} unauthorised executions in {a.get('count')} attack scenarios",
        "L3": f and f"{f.get('duplicates')} duplicate payments in {f.get('count')} fault scenarios",
        "L4": f
        and f"Covered by the {f.get('count')} fault scenarios (timeouts, crashes, kill switch mid-batch)",
        "L5": f and "Covered by the fault suite (failover) and the attack suite's block-bypass scenarios",
        "L7": rec
        and f"{rec.get('match_rate')} matched on {rec.get('count')} items; {rec.get('designed_breaks')}",
    }
    return figures.get(code) or ""


def load_demo() -> list[dict[str, Any]]:
    rows = _table_rows(SPEC11.read_text(), "| Minute")
    out = []
    for c in rows:
        m = re.match(r"(\d+)\s*to\s*(\d+)", c[0])
        if not m or len(c) < 4:
            continue
        out.append(
            {
                "start": int(m.group(1)),
                "end": int(m.group(2)),
                "screen": c[1],
                "sees": c[2],
                "say": c[3].strip('"'),
            }
        )
    return out


def load_personas() -> list[tuple[str, str]]:
    rows = _table_rows(SPEC00.read_text(), "| Persona")
    return [(re.sub(r"\*", "", c[0]), c[1]) for c in rows if len(c) >= 2]


# ---------------------------------------------------------------- MVP scope and proof


def build_scope() -> tuple[str, dict[str, Any]]:
    stories = load_stories()
    scope = load_scope()
    results = load_results()
    crit = []
    for code, text in scope["criteria"]:
        ids = [s for s, st in stories.items() if code in (st.get("trace") or [])]
        d, t = story_counts(stories, ids)
        open_ = [(s, stories[s]["title"], *story_counts(stories, [s])) for s in ids]
        open_ = [x for x in open_ if x[2] < x[3]]
        crit.append(
            {
                "code": code,
                "text": text,
                "ids": ids,
                "done": d,
                "total": t,
                "state": state(d, t),
                "evidence": evidence(code, results),
                "open": open_,
            }
        )
    triage = load_triage()
    n_built = sum(c["state"] == "built" for c in crit)
    caveat = ""
    if results:
        caveat = (
            f"Test-network evaluation on synthetic data, {results['date']}. Agent answers: "
            f"{results.get('agent_answers', 'unknown')}. Not production results."
        )

    md = [
        "# MVP scope and proof",
        "",
        "Generated by `tools/build_pages.py` from `spec/00-product-context.md`, `backlog/stories.yaml`,",
        "`backlog/model-items.yaml` and `eval/results/latest.json`. Do not edit by hand: change a source and run",
        "`make pages`. CI fails if this page is out of date.",
        "",
        f"**{n_built} of {len(crit)} launch criteria fully built and tested.** {scope['intro']}",
        "",
    ]
    md += [f"{n}. {s}" for n, s in enumerate(scope["steps"], 1)]
    md += ["", scope["then"], "", "## Launch criteria", ""]
    md += ["| Code | Criterion | Status | Criteria done | Measured | Stories |", "|---|---|---|---|---|---|"]
    for c in crit:
        md.append(
            f"| {c['code']} | {c['text']} | {STATE_LABEL[c['state']]} | {c['done']}/{c['total']} | "
            f"{c['evidence'] or '–'} | {', '.join(c['ids'])} |"
        )
    gaps = [c for c in crit if c["open"]]
    if gaps:
        md += ["", "## What is left for launch", ""]
        for c in gaps:
            md.append(f"- **{c['code']}:** " + "; ".join(f"{s} {t} ({d}/{n})" for s, t, d, n in c["open"]))
    md += ["", "## Measured proof", ""]
    if results:
        md += [
            f"> {caveat}",
            "",
            f"- Release gate: **{'passed' if results.get('gate_passed') else 'failed'}**",
            f"- Run: {results.get('commit')} ({results.get('networks', '')})",
            f"- Source: {results.get('source', '')}",
        ]
        ag, lat = results.get("agreement") or {}, results.get("latency_p95_ms") or {}
        if ag:
            md.append(
                f"- Agreement with synthetic labels: rules {ag.get('rules')}, "
                f"investigation {ag.get('investigation')}"
            )
        if lat:
            md.append(
                f"- Latency p95: {lat.get('rules_only')} ms rules only, "
                f"{lat.get('with_investigation')} ms with the investigation"
            )
    else:
        md.append("_No evaluation snapshot yet: run `make eval` then `make eval-snapshot`._")
    md += ["", "## Scope triage", "", "| Item | Status |", "|---|---|"]
    md += [f"| {item} | {status} |" for _code, item, status in triage]
    md += ["", "## Can be rough", ""] + [f"- {x}" for x in scope["rough"]]
    md += ["", "## Out of scope for this MVP", ""] + [f"- {x}" for x in scope["out"]]
    md.append("")
    return "\n".join(md), {
        "scope": scope,
        "crit": crit,
        "results": results,
        "caveat": caveat,
        "triage": triage,
        "n_built": n_built,
    }


PAGE_CSS = """
.crit { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
.crit li { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; display: grid; gap: 8px; min-width: 0; }
.crit li.partly { border-color: var(--accent); }
.crit li.todo { background: transparent; }
.crit p { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.crit .meas { font-size: 13px; color: var(--fg); border-left: 2px solid var(--ok); padding-left: 10px; }
.crit .left { font-size: 13px; color: var(--muted); }
.built .pill, .pill.built { color: var(--ok); border-color: currentColor; }
.partly .pill, .pill.partly { color: var(--accent); border-color: currentColor; }
.caveat { font-size: 13px; color: var(--muted); background: var(--raised); border-radius: 8px; padding: 10px 12px; margin: 0; }
.figs { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 20px; }
.plain { margin: 0; padding-left: 18px; display: grid; gap: 4px; color: var(--muted); }
.plain li { overflow-wrap: anywhere; }
ol.steps { margin: 0; padding-left: 20px; display: grid; gap: 4px; }
/* journey */
.layer { display: grid; gap: 10px; }
.layer > h2 { display: flex; gap: 10px; align-items: baseline; }
.layer > h2 small { font: 500 13px/1.3 var(--font-body); color: var(--muted); }
.flow { list-style: none; padding: 0 0 0 18px; margin: 0; display: grid; gap: 10px; border-left: 2px solid var(--line); }
.flow > li { position: relative; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; display: grid; gap: 6px; min-width: 0; }
.flow > li::before { content: ""; position: absolute; left: -26px; top: 16px; width: 12px; height: 12px; border-radius: 50%; background: var(--bg); border: 2px solid var(--muted); }
.flow > li.built::before { border-color: var(--ok); background: var(--ok); }
.flow > li.partly::before { border-color: var(--accent); }
.flow p { margin: 0; color: var(--muted); font-size: 14px; min-width: 0; }
.who { font: 600 12px/1.2 var(--font-head); color: var(--blue); }
.branch { font-size: 13px; border-top: 1px dashed var(--line); padding-top: 8px; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.branch b { color: var(--fg); font-weight: 600; }
.ids { font: 500 11px/1.4 var(--font-mono); color: var(--muted); overflow-wrap: anywhere; }
.timeline { display: flex; gap: 3px; height: 34px; }
.timeline span { background: var(--raised); border-radius: 4px; display: grid; place-items: center; font: 600 11px/1 var(--font-mono); color: var(--muted); min-width: 0; overflow: hidden; }
.demo { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
.demo li { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 12px; }
.demo .min { font: 600 13px/1.4 var(--font-mono); color: var(--accent); }
.demo p { margin: 2px 0 0; font-size: 14px; color: var(--muted); }
.demo q { display: block; margin-top: 4px; font-size: 13px; color: var(--fg); font-style: italic; }
.people { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; }
.people li { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; font-size: 13px; color: var(--muted); }
.people b { display: block; color: var(--fg); font-size: 14px; }
"""


def _head(title: str) -> str:
    return (
        f"<title>{e(title)}</title>\n"
        '<meta name="claude:viewport-fit-sides" content="cover">\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600'
        '&family=JetBrains+Mono:wght@500;600&family=Space+Grotesk:wght@500;600&display=swap">\n'
        f"<style>{ROADMAP_CSS}{PAGE_CSS}</style>\n"
    )


def _footer(tool_src: str, md: str, stamp: str) -> str:
    return (
        f"<footer>Generated by <span class='mono'>tools/build_pages.py</span>{e(stamp)} from {tool_src}. "
        f"The same data as <span class='mono'>{md}</span>. Working name; prototype on test networks only."
        "</footer>"
    )


def render_scope(d: dict[str, Any], stamp: str = "") -> str:
    scope, crit, r = d["scope"], d["crit"], d["results"]
    items = []
    for c in crit:
        meas = f"<p class='meas'>{e(c['evidence'])}</p>" if c["evidence"] else ""
        left = ""
        if c["open"]:
            left = (
                "<p class='left'>Left: "
                + "; ".join(
                    f"<span class='mono'>{e(s)}</span> {e(t)} ({dd}/{n})" for s, t, dd, n in c["open"]
                )
                + "</p>"
            )
        items.append(
            f"<li class='{c['state']}'><div class='row'><span class='id'>{e(c['code'])}</span>"
            f"<span class='name'>{e(c['text'])}</span><span class='n'>{c['done']}/{c['total']}</span>"
            f"<span class='pill'>{STATE_LABEL[c['state']]}</span></div>{meas}{left}</li>"
        )
    proof = "<p class='caveat'>No evaluation snapshot yet.</p>"
    if r:
        a, f, i, rec = (r.get(k) or {} for k in ("attacks", "faults", "interpretation", "reconciliation"))
        figs = [
            (
                f"{a.get('unauthorised_executions')} / {a.get('count')}",
                "attacks led to an unauthorised execution",
            ),
            (f"{f.get('duplicates')} / {f.get('count')}", "faults led to a duplicate payment"),
            (
                f"{i.get('canonical_correct')}/{i.get('canonical_runs')}",
                "runs of the $18,500 invoice read correctly",
            ),
            (str(rec.get("match_rate")), f"reconciliation match rate on {rec.get('count')} items"),
        ]
        ag, lat = r.get("agreement") or {}, r.get("latency_p95_ms") or {}
        extra = []
        if ag:
            extra.append(
                f"Agreement with synthetic labels: rules {ag.get('rules')}, investigation "
                f"{ag.get('investigation')} (stand-in answers measure Detent's checks, not a model)."
            )
        if lat:
            extra.append(
                f"Latency p95: {lat.get('rules_only')} ms rules only, {lat.get('with_investigation')} ms "
                "with the investigation."
            )
        extra.append(
            f"Release gate {'passed' if r.get('gate_passed') else 'failed'}. Run: {r.get('commit')}, "
            f"{r.get('networks', '')}."
        )
        proof = (
            "<div class='figs'>"
            + "".join(f"<div class='stat'><b>{e(v)}</b><span>{e(c)}</span></div>" for v, c in figs)
            + "</div>"
            + f"<p class='caveat'>{e(d['caveat'])} {' '.join(e(x) for x in extra)}</p>"
        )
    triage = "".join(
        f"<li><span>{e(item)}</span><span class='tag'>{e(st)}</span></li>" for _c, item, st in d["triage"]
    )
    steps = "".join(f"<li>{e(s)}</li>" for s in scope["steps"])
    return f"""{_head("Detent MVP scope")}<main>
<header><div class="eyebrow">Agentic payment controls · prototype</div><h1>MVP scope and proof</h1>
<p class="lede">What the MVP must prove before launch, how much of each launch criterion is built, and the last measured result. Built from the repository on every handoff.</p></header>
<section class="summary">
<div class="stat"><b>{d["n_built"]} / {len(crit)}</b><span>launch criteria fully built</span></div>
<div class="stat"><b>{sum(c["done"] for c in crit)} / {sum(c["total"] for c in crit)}</b><span>criteria done in their stories</span></div>
<div class="stat"><b>{"Passed" if r and r.get("gate_passed") else "–"}</b><span>release gate, last run</span></div>
</section>
<section><h2>The MVP in one sitting</h2><p class="lede" style="margin:0">{e(scope["intro"])}</p><ol class="steps">{steps}</ol><p class="lede" style="margin:0">{e(scope["then"])}</p></section>
<section><h2>Launch criteria</h2><ul class="crit">{"".join(items)}</ul></section>
<section><h2>Measured proof</h2>{proof}</section>
<section><h2>Scope triage</h2><ul class="list">{triage}</ul></section>
<section class="cols"><div class="layer"><h2>Can be rough</h2><ul class="plain">{"".join(f"<li>{e(x)}</li>" for x in scope["rough"])}</ul></div>
<div class="layer"><h2>Out of scope</h2><ul class="plain">{"".join(f"<li>{e(x)}</li>" for x in scope["out"])}</ul></div></section>
{_footer("spec/00, backlog/stories.yaml, backlog/model-items.yaml and eval/results/latest.json", "founder/mvp-scope.md", stamp)}
</main>
"""


# ---------------------------------------------------------------- user journey


def build_journey() -> tuple[str, dict[str, Any]]:
    stories = load_stories()
    src = yaml.safe_load(JOURNEY.read_text())
    steps = []
    for s in src["steps"]:
        missing = [i for i in s["stories"] + s.get("branch_stories", []) if i not in stories]
        if missing:
            raise SystemExit(f"{JOURNEY.name}: unknown stories {missing}")
        d, t = story_counts(stories, s["stories"])
        bd, bt = story_counts(stories, s.get("branch_stories", []))
        steps.append(
            {
                **s,
                "done": d,
                "total": t,
                "state": state(d, t),
                "bdone": bd,
                "btotal": bt,
                "bstate": state(bd, bt) if bt else "",
            }
        )
    demo, personas = load_demo(), load_personas()
    n_built = sum(s["state"] == "built" for s in steps)

    md = [
        "# User journey",
        "",
        "Generated by `tools/build_pages.py` from `founder/pages/user-journey.yaml`, `backlog/stories.yaml`,",
        "`spec/11-demo-script.md` and `spec/00-product-context.md`. Do not edit by hand: change a source and run",
        "`make pages`. CI fails if this page is out of date.",
        "",
        f"{src['journey']} **{n_built} of {len(steps)} steps fully built and tested.**",
        "",
        "```mermaid",
        "flowchart LR",
    ]
    for layer in LAYERS:
        md.append(f'  subgraph {layer}["{layer}"]')
        for n, s in enumerate(steps, 1):
            if s["layer"] == layer:
                md.append(f'    s{n}["{n}. {s["title"]}"]')
        md.append("  end")
    md.append("  " + " --> ".join(f"s{n}" for n in range(1, len(steps) + 1)))
    md += [
        "```",
        "",
        "| # | Layer | Step | Who | Status | Criteria | Stories |",
        "|---|---|---|---|---|---|---|",
    ]
    for n, s in enumerate(steps, 1):
        md.append(
            f"| {n} | {s['layer']} | **{s['title']}.** {s['what']} | {s['actor']} | "
            f"{STATE_LABEL[s['state']]} | {s['done']}/{s['total']} | {', '.join(s['stories'])} |"
        )
        if s.get("branch"):
            md.append(
                f"| | | _Branch:_ {s['branch']} | | {STATE_LABEL[s['bstate']]} | "
                f"{s['bdone']}/{s['btotal']} | {', '.join(s['branch_stories'])} |"
            )
    md += ["", "## The 10-minute demo", "", "| Minute | Screen | What the viewer sees |", "|---|---|---|"]
    md += [f"| {x['start']} to {x['end']} | {x['screen']} | {x['sees']} |" for x in demo]
    md += ["", "## Who takes part", "", "| Persona | What they do |", "|---|---|"]
    md += [f"| {p} | {w} |" for p, w in personas]
    md.append("")
    return "\n".join(md), {"src": src, "steps": steps, "demo": demo, "personas": personas, "n_built": n_built}


def render_journey(d: dict[str, Any], stamp: str = "") -> str:
    steps = d["steps"]
    layers_html = []
    sub = {
        "Decision": "Should this payment happen?",
        "Orchestration": "How and where does it go?",
        "Operations": "What happens around it?",
    }
    for li, layer in enumerate(LAYERS, 1):
        cards = []
        for n, s in enumerate(steps, 1):
            if s["layer"] != layer:
                continue
            branch = ""
            if s.get("branch"):
                branch = (
                    f"<div class='branch'><b>If not:</b><span>{e(s['branch'])}</span>"
                    f"<span class='pill {s['bstate']}'>{STATE_LABEL[s['bstate']]}</span></div>"
                )
            cards.append(
                f"<li class='{s['state']}'><div class='row'><span class='id'>{n}</span>"
                f"<span class='name'>{e(s['title'])}</span><span class='pill {s['state']}'>"
                f"{STATE_LABEL[s['state']]}</span></div><div class='who'>{e(s['actor'])}</div>"
                f"<p>{e(s['what'])}</p>{branch}<div class='ids'>Demo minute {e(s['demo'])} · "
                f"{e(', '.join(s['workflows']))} · {e(', '.join(s['stories']))} · {s['done']}/{s['total']}</div></li>"
            )
        layers_html.append(
            f"<section class='layer'><div class='eyebrow'>Layer {li}</div><h2>{layer} "
            f"<small>{sub[layer]}</small></h2><ol class='flow'>{''.join(cards)}</ol></section>"
        )
    demo = d["demo"]
    total_min = max((x["end"] for x in demo), default=10)
    bar = "".join(
        f"<span style='flex:{x['end'] - x['start']}' title='{e(x['screen'])}'>{x['start']}</span>"
        for x in demo
    )
    demo_list = "".join(
        f"<li><span class='min'>{x['start']}–{x['end']}</span><div><b>{e(x['screen'])}</b>"
        f"<p>{e(x['sees'])}</p><q>{e(x['say'])}</q></div></li>"
        for x in demo
    )
    people = "".join(f"<li><b>{e(p)}</b>{e(w)}</li>" for p, w in d["personas"])
    return f"""{_head("Detent user journey")}<main>
<header><div class="eyebrow">Agentic payment controls · prototype</div><h1>One payment, start to finish</h1>
<p class="lede">{e(d["src"]["journey"])} Each step shows who acts and whether it is built, from the repository on every handoff.</p></header>
<section class="summary">
<div class="stat"><b>{d["n_built"]} / {len(steps)}</b><span>steps fully built</span></div>
<div class="stat"><b>3</b><span>layers: decision, orchestration, operations</span></div>
<div class="stat"><b>{total_min} min</b><span>to show it in the demo</span></div>
</section>
{"".join(layers_html)}
<section><h2>The {total_min}-minute demo</h2><div class="timeline">{bar}</div><ol class="demo">{demo_list}</ol></section>
<section><h2>Who takes part</h2><ul class="people">{people}</ul></section>
{_footer("founder/pages/user-journey.yaml, backlog/stories.yaml, spec/11 and spec/00", "founder/user-journey.md", stamp)}
</main>
"""


# ---------------------------------------------------------------- evaluation snapshot


def snapshot(results_path: Path) -> dict[str, Any]:
    """The few figures the MVP page shows, from a full `detent eval run` results.json."""
    r = json.loads(results_path.read_text())
    s = r.get("suites", {})
    att, flt, interp, rec = (
        s.get(k) or {} for k in ("attacks", "faults", "interpretation", "reconciliation")
    )
    canon = interp.get("canonical") or {}
    out: dict[str, Any] = {
        "date": r.get("date"),
        "commit": str(r.get("commit", ""))[:12],
        "source": f"detent eval run, results.json from {results_path.as_posix()}",
        "gate_passed": bool((r.get("gate") or {}).get("passed")),
        "agent_answers": r.get("agent_answers"),
        "networks": r.get("networks"),
        "attacks": {
            "count": att.get("count"),
            "unauthorised_executions": (att.get("safety") or {}).get("unauthorised_executions", 0),
        },
        "faults": {"count": flt.get("count"), "duplicates": (flt.get("safety") or {}).get("duplicates", 0)},
        "interpretation": {
            "count": interp.get("count"),
            "canonical_correct": canon.get("correct"),
            "canonical_runs": canon.get("runs"),
            "invented_values": interp.get("invented_values"),
        },
        "reconciliation": {
            "count": rec.get("count"),
            "match_rate": rec.get("match_rate"),
            "designed_breaks": rec.get("designed_breaks"),
        },
    }
    return out


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if a page is stale")
    ap.add_argument("--html", type=Path, help="also write the phone pages into this directory")
    ap.add_argument("--snapshot", type=Path, help="refresh eval/results/latest.json from a results.json")
    args = ap.parse_args()
    if args.snapshot:
        RESULTS.write_text(json.dumps(snapshot(args.snapshot), indent=2) + "\n")
        print(f"wrote {RESULTS.relative_to(ROOT)}")
    scope_md, scope_d = build_scope()
    journey_md, journey_d = build_journey()
    if args.html:
        args.html.mkdir(parents=True, exist_ok=True)
        stamp = _stamp()
        (args.html / "mvp-scope.html").write_text(render_scope(scope_d, stamp))
        (args.html / "user-journey.html").write_text(render_journey(journey_d, stamp))
    pages = ((OUT_SCOPE, scope_md), (OUT_JOURNEY, journey_md))
    if args.check:
        stale = [p for p, text in pages if (p.read_text() if p.exists() else "") != text]
        for p in stale:
            print(f"{p.relative_to(ROOT)} is out of date: run `make pages` and commit it", file=sys.stderr)
        if stale:
            return 1
        print("pages OK")
        return 0
    for p, text in pages:
        p.write_text(text)
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
