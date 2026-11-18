"""Build the backlog documents from backlog/stories.yaml and backlog/model-items.yaml.

Usage: python tools/build_backlog.py
Writes: backlog/user-stories.md, backlog/epics.md, backlog/traceability.md, backlog/backlog.csv
Fails (exit 1) if: a story traces to an unknown code, an mvp/partly item has no story,
a dependency is unknown, a dependency sits in a later milestone, or there is a dependency cycle.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BL = ROOT / "backlog"
MS_ORDER = [f"M{i}" for i in range(13)]
MS_NAMES = {
    "M0": "Foundation", "M1": "Decide", "M2": "Agent and mandates", "M3": "Exactly-once execution and rails",
    "M4": "Exceptions and console", "M5": "Ledger, deposits, reconciliation, replay", "M6": "Evaluation and release gate",
    "M7": "Demo-ready prototype", "M8": "Public sandbox API and webhooks", "M9": "Dashboard and sandbox",
    "M10": "Docs and SDKs", "M11": "Website launch", "M12": "Should and could haves after launch",
}


def main() -> int:
    data = yaml.safe_load((BL / "stories.yaml").read_text())
    items = yaml.safe_load((BL / "model-items.yaml").read_text())
    epics, stories = data["epics"], data["stories"]
    codes = {i["code"]: i for i in items}
    by_id = {s["id"]: s for s in stories}
    errors: list[str] = []

    if len(by_id) != len(stories):
        errors.append("duplicate story IDs")
    for s in stories:
        bad = [i for i in s.get("done", []) if not (isinstance(i, int) and 0 <= i < len(s["ac"]))]
        if bad:
            errors.append(f"{s['id']}: 'done' lists unknown acceptance-criterion indices {bad}")
    for s in stories:
        for c in s["trace"]:
            if c not in codes:
                errors.append(f"{s['id']}: unknown trace code {c}")
        if s["epic"] not in epics:
            errors.append(f"{s['id']}: unknown epic {s['epic']}")
        for d in s["deps"]:
            if d not in by_id:
                errors.append(f"{s['id']}: unknown dependency {d}")
            elif MS_ORDER.index(by_id[d]["ms"]) > MS_ORDER.index(s["ms"]):
                errors.append(f"{s['id']} ({s['ms']}) depends on {d} in later milestone {by_id[d]['ms']}")

    # cycle check
    state: dict[str, int] = {}

    def visit(n: str, path: list[str]) -> None:
        if state.get(n) == 1:
            errors.append("dependency cycle: " + " -> ".join(path + [n]))
            return
        if state.get(n) == 2:
            return
        state[n] = 1
        for d in by_id[n]["deps"]:
            if d in by_id:
                visit(d, path + [n])
        state[n] = 2

    for sid in by_id:
        visit(sid, [])

    traced = defaultdict(list)
    for s in stories:
        for c in s["trace"]:
            traced[c].append(s["id"])
    for i in items:
        if i["status"] in ("mvp", "partly") and not traced[i["code"]]:
            errors.append(f"model item {i['code']} ({i['status']}) has no story")

    if errors:
        print("\n".join(errors))
        return 1

    # ---------- user-stories.md ----------
    out = ["# User stories", "",
           "Generated from `backlog/stories.yaml` by `tools/build_backlog.py`. Edit the YAML, not this file.", "",
           "Estimates are ideal developer-days for one developer working with Claude Code (Estimate).", ""]
    for code, e in epics.items():
        es = [s for s in stories if s["epic"] == code]
        out += [f"## {code} · {e['name']}", "", f"_{e['goal']}_ · layer: {e.get('layer','-')} · track: {e['track']} · "
                f"{len(es)} stories · {sum(s['est'] for s in es):g} days", ""]
        for s in es:
            out += [f"### {s['id']} · {s['title']}", "",
                    f"**As a** {s['as']}, **I want** {s['want']}, **so that** {s['so']}.", "",
                    "**Acceptance criteria**", ""]
            done = set(s.get("done", []))  # indices of ticked acceptance criteria
            out += [f"- [{'x' if i in done else ' '}] {a}" for i, a in enumerate(s["ac"])]
            out += ["", f"**Priority:** {s['pri']} · **Estimate:** {s['est']:g} d · **Milestone:** "
                    f"{s['ms']} {MS_NAMES[s['ms']]} · **Depends on:** {', '.join(s['deps']) or 'none'} · "
                    f"**Traces to:** {', '.join(s['trace'])}", ""]
    (BL / "user-stories.md").write_text("\n".join(out))

    # ---------- epics.md ----------
    out = ["# Epics", "", "Product: agentic payment controls in three layers (decision, orchestration, operations). Each epic's layer is shown.", "",
           "| Epic | Layer | Track | Goal | Stories | Must | Should | Could | Days |",
           "|---|---|---|---|---|---|---|---|---|"]
    tot = defaultdict(float)
    for code, e in epics.items():
        es = [s for s in stories if s["epic"] == code]
        cnt = {p: sum(1 for s in es if s["pri"] == p) for p in ("Must", "Should", "Could")}
        days = sum(s["est"] for s in es)
        tot[e["track"]] += days
        out.append(f"| {code} {e['name']} | {e.get('layer','-')} | {e['track']} | {e['goal']} | {len(es)} | {cnt['Must']} | "
                   f"{cnt['Should']} | {cnt['Could']} | {days:g} |")
    must = [s for s in stories if s["pri"] == "Must"]
    out += ["", "## Totals (Estimate)", "",
            "| | Stories | Days |", "|---|---|---|",
            f"| All stories | {len(stories)} | {sum(s['est'] for s in stories):g} |",
            f"| Must only | {len(must)} | {sum(s['est'] for s in must):g} |"]
    for track in ("prototype", "portal"):
        tm = [s for s in must if epics[s["epic"]]["track"] == track]
        out.append(f"| Must, {track} track | {len(tm)} | {sum(s['est'] for s in tm):g} |")
    out += ["", "## By milestone", "", "| Milestone | Stories | Must days | All days |", "|---|---|---|---|"]
    for m in MS_ORDER:
        ms = [s for s in stories if s["ms"] == m]
        out.append(f"| {m} {MS_NAMES[m]} | {len(ms)} | {sum(s['est'] for s in ms if s['pri']=='Must'):g} | "
                   f"{sum(s['est'] for s in ms):g} |")
    (BL / "epics.md").write_text("\n".join(out) + "\n")

    # ---------- traceability.md ----------
    out = ["# Traceability: every model item to the stories that deliver it", "",
           "Status: **mvp** built in this MVP · **partly** software part built now, rest later or manual · "
           "**later** a later roadmap phase · **non-software** business, legal or hiring work.", "",
           "| Code | Source | Item | Status | Stories |", "|---|---|---|---|---|"]
    for i in items:
        out.append(f"| {i['code']} | {i['source']} | {i['item']} | {i['status']} | "
                   f"{', '.join(traced[i['code']]) or '—'} |")
    counts = defaultdict(int)
    for i in items:
        counts[i["status"]] += 1
    out += ["", "Coverage check: every **mvp** and **partly** item has at least one story (enforced by the build script). "
            + ", ".join(f"{k}: {v}" for k, v in counts.items()), ""]
    (BL / "traceability.md").write_text("\n".join(out))

    # ---------- backlog.csv ----------
    with (BL / "backlog.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Epic", "Title", "User story", "Acceptance criteria", "Priority", "Estimate (days)",
                    "Milestone", "Depends on", "Traces to"])
        for s in stories:
            w.writerow([s["id"], f"{s['epic']} {epics[s['epic']]['name']}", s["title"],
                        f"As a {s['as']}, I want {s['want']}, so that {s['so']}.",
                        "\n".join(f"- {a}" for a in s["ac"]), s["pri"], s["est"],
                        f"{s['ms']} {MS_NAMES[s['ms']]}", ", ".join(s["deps"]), ", ".join(s["trace"])])

    print(f"OK: {len(stories)} stories, {sum(s['est'] for s in stories):g} days; "
          f"Must {len(must)} stories, {sum(s['est'] for s in must):g} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
