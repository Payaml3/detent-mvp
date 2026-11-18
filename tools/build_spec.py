"""Build the Spec Kit documents for specs/001-detent-mvp from data, and check coverage.

Usage: python tools/build_spec.py
Reads:  backlog/stories.yaml, backlog/model-items.yaml, specs/001-detent-mvp/{requirements,slices,test-map}.yaml,
        spec/*.md and CLAUDE.md (for anchors), apps/api/tests/**/*.py (for test IDs)
Writes: specs/001-detent-mvp/{inventory,traceability,tasks}.md
Fails (exit 1) if:
  - a requirement cites an unknown story, an unknown decision ID, or a source anchor that doesn't exist
  - a story is covered by no requirement, or an mvp/partly model item is reached by no requirement
  - a slice misses a story, repeats one, or puts a story before one of its dependencies
  - test-map.yaml cites a test that doesn't exist, or a ticked criterion has no evidence
"""

from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FEAT = ROOT / "specs" / "001-detent-mvp"
TESTS = ROOT / "apps" / "api" / "tests"
SPEC_FILES = {p.name[:2]: p for p in (ROOT / "spec").glob("[0-9][0-9]-*.md")}
INVARIANTS_ANCHOR = "../../CLAUDE.md#non-negotiable-invariants"

EPIC_LEVEL = {
    "FND": "integration",
    "INT": "integration",
    "POL": "unit",
    "MND": "unit",
    "AGT": "unit",
    "EXE": "integration",
    "RAL": "contract",
    "EXC": "integration",
    "LED": "integration",
    "AUD": "integration",
    "CON": "console",
    "EVL": "eval",
    "DEM": "scenario",
    "SHD": "integration",
    "OPS": "manual",
    "API": "contract",
    "WHK": "integration",
    "DSH": "console",
    "SBX": "integration",
    "DOC": "docs-ci",
    "SDK": "sdk",
    "WEB": "site",
}
KEYWORD_LEVEL = [
    (re.compile(r"concurren|parallel|race"), "concurrency"),
    (re.compile(r"hypothesis|property|always balances|deterministic"), "property"),
    (re.compile(r"\bfault(s|-injection)?\b|\btime(s)? ?out\b|\bcrash|connection drop|dropped"), "fault"),
    (re.compile(r"playwright|screenshot|clickable"), "e2e"),
    (re.compile(r"founder|signed off|honesty checklist|legal"), "manual"),
    (re.compile(r"10 of 10|\bruns? \d+ times|make eval"), "eval"),
]
EPIC_PATH = {
    "FND": "apps/api/src/detent/",
    "INT": "apps/api/src/detent/intents/",
    "POL": "apps/api/src/detent/policy/",
    "MND": "apps/api/src/detent/mandates/",
    "AGT": "apps/api/src/detent/agents/",
    "EXE": "apps/api/src/detent/execution/",
    "RAL": "apps/api/src/detent/rails/ (+ apps/banksim, apps/faultproxy)",
    "EXC": "apps/api/src/detent/exceptions/",
    "LED": "apps/api/src/detent/ledger/ + reconciliation/",
    "AUD": "apps/api/src/detent/audit/",
    "CON": "apps/api/src/detent/console/",
    "EVL": "eval/ + apps/api/src/detent/eval/",
    "DEM": "fixtures/ + apps/api/src/detent/demo/",
    "SHD": "apps/api/src/detent/shadow/",
    "OPS": "tools/ + docs/runbooks/",
    "API": "apps/api/src/detent/api/",
    "WHK": "apps/api/src/detent/webhooks/",
    "DSH": "apps/api/src/detent/dashboard/",
    "SBX": "apps/api/src/detent/sandbox/",
    "DOC": "docs/",
    "SDK": "sdks/python + sdks/typescript",
    "WEB": "apps/site/",
}


def slug(heading: str) -> str:
    """GitHub's heading anchor algorithm (close enough for ASCII headings)."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    out: set[str] = set()
    in_code = False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and line.startswith("#"):
            out.add(slug(line.lstrip("#")))
    return out


def resolve_src(ref: str, errors: list[str], where: str) -> str:
    """Turn a source reference into a markdown link relative to FEAT, checking it exists."""
    if ref.startswith("inv:"):
        return f"[Invariant {ref[4:]}]({INVARIANTS_ANCHOR})"
    if ref.startswith("story:"):
        sid = ref[6:]
        return f"[{sid} criteria](../../backlog/user-stories.md#{slug(sid)})"
    if ref.startswith("fixture:"):
        p = ref[8:]
        if not (ROOT / p).exists():
            errors.append(f"{where}: fixture {p} not found")
        return f"[{p}](../../{p})"
    path_part, _, anchor = ref.partition("#")
    m = re.fullmatch(r"spec/(\d\d)", path_part)
    if m:
        file = SPEC_FILES.get(m.group(1))
        label = f"spec/{m.group(1)}"
    else:
        file = ROOT / path_part
        label = path_part
    if file is None or not file.exists():
        errors.append(f"{where}: source file for {ref!r} not found")
        return ref
    if anchor and anchor not in anchors(file):
        errors.append(f"{where}: anchor #{anchor} not found in {file.relative_to(ROOT)}")
    rel = "../../" + file.relative_to(ROOT).as_posix()
    return f"[{label}{(' §' + anchor) if anchor else ''}]({rel}{('#' + anchor) if anchor else ''})"


def test_ids() -> set[str]:
    """Every test function and fixture name, as 'relative/path.py::name'."""
    ids: set[str] = set()
    for p in TESTS.rglob("*.py"):
        rel = p.relative_to(TESTS).as_posix()
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node, ast.FunctionDef):
                ids.add(f"{rel}::{node.name}")
    return ids


def planned_level(story_id: str, ac: str) -> str:
    low = re.sub(r"\S+\.(md|ya?ml|json|py)\b", "", ac.lower())  # file names are not test hints
    for rx, level in KEYWORD_LEVEL:
        if rx.search(low):
            return level
    return EPIC_LEVEL[story_id.split("-", maxsplit=1)[0]]


def planned_location(story_id: str, level: str) -> str:
    name = story_id.lower().replace("-", "_")
    if level in {"unit", "integration", "concurrency", "property", "fault", "contract", "console"}:
        folder = {"fault": "integration", "contract": "integration", "console": "integration"}.get(
            level, level
        )
        return f"apps/api/tests/{folder}/test_{name}.py"
    return {
        "eval": f"eval/scenarios (runner: detent eval) for {story_id}",
        "e2e": f"apps/api/tests/e2e/test_{name}.py (Playwright)",
        "scenario": f"detent demo run ({story_id})",
        "manual": "manual check, recorded in the PR description",
        "docs-ci": "docs snippet runner in CI",
        "sdk": "SDK test suite against the sandbox",
        "site": "site build check + manual honesty checklist",
    }[level]


def main() -> int:
    errors: list[str] = []
    stories_doc = yaml.safe_load((ROOT / "backlog" / "stories.yaml").read_text())
    stories = {s["id"]: s for s in stories_doc["stories"]}
    items = {i["code"]: i for i in yaml.safe_load((ROOT / "backlog" / "model-items.yaml").read_text())}
    reqs = yaml.safe_load((FEAT / "requirements.yaml").read_text())["requirements"]
    slices = yaml.safe_load((FEAT / "slices.yaml").read_text())["slices"]
    test_map = yaml.safe_load((FEAT / "test-map.yaml").read_text()) or {}
    decisions_text = (FEAT / "decisions.md").read_text()
    known_tests = test_ids()

    # ---------------------------------------------------------------- requirements
    req_stories: dict[str, list[str]] = {}
    req_models: dict[str, list[str]] = {}
    req_links: dict[str, list[str]] = {}
    story_reqs: dict[str, list[str]] = defaultdict(list)
    seen_ids: set[str] = set()
    for r in reqs:
        rid = r["id"]
        if rid in seen_ids:
            errors.append(f"duplicate requirement {rid}")
        seen_ids.add(rid)
        if r["status"] not in {"confirmed", "proposed", "open"}:
            errors.append(f"{rid}: bad status {r['status']}")
        if r["status"] in {"proposed", "open"} and not r.get("decision"):
            errors.append(f"{rid}: {r['status']} requirements must cite a decision ID")
        for d in r.get("decision", []):
            if not re.search(rf"\|\s*{re.escape(d)}\s*\|", decisions_text):
                errors.append(f"{rid}: decision {d} not found in decisions.md")
        for sid in r["stories"]:
            if sid not in stories:
                errors.append(f"{rid}: unknown story {sid}")
            else:
                story_reqs[sid].append(rid)
        req_stories[rid] = r["stories"]
        req_models[rid] = sorted({c for sid in r["stories"] if sid in stories for c in stories[sid]["trace"]})
        req_links[rid] = [resolve_src(s, errors, rid) for s in r["src"]]

    for sid in stories:
        if sid not in story_reqs:
            errors.append(f"story {sid} is covered by no requirement")
    item_reqs: dict[str, list[str]] = defaultdict(list)
    for rid, codes in req_models.items():
        for c in codes:
            item_reqs[c].append(rid)
    for code, it in items.items():
        if it["status"] in {"mvp", "partly"} and not item_reqs.get(code):
            errors.append(f"model item {code} ({it['status']}) is reached by no requirement")

    inv_reqs: dict[int, list[str]] = defaultdict(list)
    for r in reqs:
        for s in r["src"]:
            if s.startswith("inv:"):
                inv_reqs[int(s[4:])].append(r["id"])

    # ---------------------------------------------------------------- slices
    slice_of: dict[str, str] = {}
    order = {s["id"]: i for i, s in enumerate(slices)}
    for s in slices:
        for sid in s["stories"]:
            if sid in slice_of:
                errors.append(f"story {sid} is in slices {slice_of[sid]} and {s['id']}")
            if sid not in stories:
                errors.append(f"slice {s['id']}: unknown story {sid}")
            slice_of[sid] = s["id"]
    for sid in stories:
        if sid not in slice_of:
            errors.append(f"story {sid} is in no slice")
    for sid, sl in slice_of.items():
        for dep in stories.get(sid, {}).get("deps", []):
            if dep in slice_of and order[slice_of[dep]] > order[sl]:
                errors.append(f"{sid} ({sl}) depends on {dep} in a later slice ({slice_of[dep]})")

    # ---------------------------------------------------------------- tests
    for sid, acs in test_map.items():
        if sid not in stories:
            errors.append(f"test-map: unknown story {sid}")
            continue
        for idx, refs in acs.items():
            if not 0 <= idx < len(stories[sid]["ac"]):
                errors.append(f"test-map: {sid} has no criterion {idx}")
            for ref in refs:
                if not ref.startswith(("ci:", "manual:")) and ref not in known_tests:
                    errors.append(f"test-map: {sid}[{idx}] cites missing test {ref}")
    for sid, s in stories.items():
        for idx in s.get("done", []):
            if not test_map.get(sid, {}).get(idx):
                errors.append(f"{sid} criterion {idx} is ticked but has no evidence in test-map.yaml")

    if errors:
        print("build_spec: FAILED", file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        return 1

    write_inventory(reqs, req_links, req_models, items, item_reqs, inv_reqs, stories)
    write_traceability(reqs, req_links, stories, test_map, slice_of)
    write_tasks(slices, stories, story_reqs, test_map)
    inject_fr_list(reqs)

    n_ac = sum(len(s["ac"]) for s in stories.values())
    n_done = sum(len(s.get("done", [])) for s in stories.values())
    by_status = defaultdict(int)
    for r in reqs:
        by_status[r["status"]] += 1
    covered = sum(1 for c, it in items.items() if it["status"] in {"mvp", "partly"} and item_reqs.get(c))
    total_mvp = sum(1 for it in items.values() if it["status"] in {"mvp", "partly"})
    print(
        f"OK: {len(reqs)} requirements ({dict(by_status)}); {len(stories)} stories, all covered; "
        f"{covered}/{total_mvp} mvp/partly model items reached; {len(slices)} slices; "
        f"{n_done}/{n_ac} criteria done with evidence"
    )
    return 0


# -------------------------------------------------------------------- writers


def inject_fr_list(reqs) -> None:  # type: ignore[no-untyped-def]
    spec = FEAT / "spec.md"
    text = spec.read_text()
    begin, end = "<!-- FR:BEGIN (generated by tools/build_spec.py; do not edit) -->", "<!-- FR:END -->"
    if begin not in text or end not in text:
        raise SystemExit("spec.md is missing the FR markers")
    lines, area = [], None
    for r in reqs:
        if r["area"] != area:
            area = r["area"]
            lines += ["", f"**{area}**", ""]
        tag = "" if r["status"] == "confirmed" else f" *({r['status']}: {', '.join(r['decision'])})*"
        lines.append(f"- **{r['id']}**: {r['text']}{tag}")
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    spec.write_text(head + begin + "\n" + "\n".join(lines).strip() + "\n" + end + tail)


def _story_link(sid: str) -> str:
    return f"[{sid}](../../backlog/user-stories.md#{slug(sid)})"


def write_inventory(reqs, req_links, req_models, items, item_reqs, inv_reqs, stories) -> None:  # type: ignore[no-untyped-def]
    out = [
        "# Requirements inventory: Detent MVP",
        "",
        "Generated by `python tools/build_spec.py` from [requirements.yaml](requirements.yaml), "
        "`backlog/model-items.yaml` and `backlog/stories.yaml`. Do not edit by hand.",
        "",
        "**Status** of each requirement: **confirmed** (stated in a source, or approved by the founder), "
        "**proposed** (my decision, pending approval), **open** (the founder decides). "
        "See [decisions.md](decisions.md). Sources are linked to the exact section.",
        "",
        "## 1. Functional requirements",
        "",
        "| ID | Area | Layer | Status | Requirement | Sources | Stories | Model items |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in reqs:
        dec = f" ({', '.join(r['decision'])})" if r.get("decision") else ""
        out.append(
            f"| {r['id']} | {r['area']} | {r['layer']} | {r['status']}{dec} | {r['text']} | "
            f"{'<br>'.join(req_links[r['id']])} | {', '.join(_story_link(s) for s in r['stories'])} | "
            f"{', '.join(req_models[r['id']])} |"
        )
    out += [
        "",
        "## 2. Product model, operating model, MVP scope and portal items",
        "",
        "Every item from `backlog/model-items.yaml` (the extract of the founder's documents) with the requirements "
        "that cover it. Items marked *later* or *non-software* are out of scope for code by definition.",
        "",
        "| Code | Source | Item | Status | Requirements |",
        "|---|---|---|---|---|",
    ]
    for code, it in items.items():
        reqs_for = ", ".join(sorted(set(item_reqs.get(code, [])))) or (
            "- (out of scope: " + it["status"] + ")"
            if it["status"] in {"later", "non-software"}
            else "**none**"
        )
        out.append(f"| {code} | {it['source']} | {it['item']} | {it['status']} | {reqs_for} |")
    out += [
        "",
        "## 3. Non-negotiable invariants (CLAUDE.md)",
        "",
        "| Invariant | Requirements |",
        "|---|---|",
    ]
    for n in range(1, 18):
        out.append(
            f"| [{n}]({INVARIANTS_ANCHOR}) | {', '.join(inv_reqs.get(n, [])) or '(enforced in M0 code; see traceability)'} |"
        )
    counts = defaultdict(int)
    for r in reqs:
        counts[(r["layer"], r["status"])] += 1
    out += ["", "## 4. Totals", "", "| Layer | Confirmed | Proposed | Open |", "|---|---|---|---|"]
    for layer in ["decision", "orchestration", "operations", "cross-cutting", "portal"]:
        out.append(
            f"| {layer} | {counts[(layer, 'confirmed')]} | {counts[(layer, 'proposed')]} | {counts[(layer, 'open')]} |"
        )
    (FEAT / "inventory.md").write_text("\n".join(out) + "\n")


def write_traceability(reqs, req_links, stories, test_map, slice_of) -> None:  # type: ignore[no-untyped-def]
    out = [
        "# Traceability: requirement → story → acceptance criterion → test",
        "",
        "Generated by `python tools/build_spec.py`. Do not edit by hand.",
        "",
        "- **Done** criteria cite their evidence from [test-map.yaml](test-map.yaml); the build fails if a cited "
        "test doesn't exist.",
        "- **Planned** criteria get a test level and location from the story's epic and the criterion's wording "
        "(concurrency, property, fault, Playwright, eval or manual). Write those tests first (constitution, Principle VI).",
        "",
    ]
    for r in reqs:
        out += [
            f"## {r['id']} · {r['area']} ({r['status']})",
            "",
            r["text"],
            "",
            "Sources: " + "; ".join(req_links[r["id"]]),
            "",
        ]
        out += ["| Story | Slice | # | Acceptance criterion | State | Test |", "|---|---|---|---|---|---|"]
        for sid in r["stories"]:
            s = stories[sid]
            done = set(s.get("done", []))
            for i, ac in enumerate(s["ac"]):
                ev = test_map.get(sid, {}).get(i)
                if i in done:
                    state, test = "done", "<br>".join(f"`{e}`" for e in ev)
                elif ev:
                    state, test = "partial", "<br>".join(f"`{e}`" for e in ev) + " (criterion not fully met)"
                else:
                    level = planned_level(sid, ac)
                    state, test = "planned", f"{level}: `{planned_location(sid, level)}`"
                out.append(
                    f"| {_story_link(sid)} | {slice_of[sid]} | {i} | {ac.replace('|', '/')} | {state} | {test} |"
                )
        out.append("")
    (FEAT / "traceability.md").write_text("\n".join(out) + "\n")


def write_tasks(slices, stories, story_reqs, test_map) -> None:  # type: ignore[no-untyped-def]
    out = [
        "---",
        'description: "Task list for the Detent MVP, by end-to-end slice"',
        "---",
        "",
        "# Tasks: Detent MVP",
        "",
        "**Input**: [plan.md](plan.md), [spec.md](spec.md), [data-model.md](data-model.md), [contracts/](contracts/), "
        "[slices.yaml](slices.yaml) (**proposed** order, decision C-17)",
        "",
        "Generated by `python tools/build_spec.py`. Tests are mandatory (constitution, Principle VI): each story has a "
        "test task before its implementation task. `[P]` = no dependency on another story in the same slice.",
        "",
        "## Format: `[ID] [P?] [Slice] Description`",
        "",
    ]
    n = 0
    for sl in slices:
        ids = sl["stories"]
        days = sum(stories[s]["est"] for s in ids)
        out += [
            f"## {sl['id']}: {sl['name']}" + (" ✅" if sl.get("status") == "done" else ""),
            "",
            f"**Goal**: {sl['goal']}",
            "",
            f"**Independent test (exit check)**: {sl['exit'].strip()}",
            "",
            f"**Size**: {len(ids)} stories, {days:g} days (backlog estimates).",
            "",
        ]
        for sid in ids:
            s = stories[sid]
            same_slice_deps = [d for d in s["deps"] if d in ids]
            par = "[P] " if not same_slice_deps else ""
            all_done = len(s.get("done", [])) == len(s["ac"])
            some_done = bool(s.get("done"))
            box_t = "x" if some_done else " "
            box_i = "x" if all_done else " "
            levels = sorted({planned_level(sid, a) for a in s["ac"]})
            n += 1
            out.append(
                f"- [{box_t}] T{n:03d} {par}[{sl['id']}] Tests first for {sid} ({s['title']}): one test per "
                f"criterion ({len(s['ac'])}), levels: {', '.join(levels)}. Covers {', '.join(story_reqs[sid])}"
            )
            n += 1
            deps = f"; after {', '.join(same_slice_deps)}" if same_slice_deps else ""
            note = ""
            if some_done and not all_done:
                pending = [str(i) for i in range(len(s["ac"])) if i not in s.get("done", [])]
                note = f" (criteria {', '.join(pending)} pending)"
            out.append(
                f"- [{box_i}] T{n:03d} {par}[{sl['id']}] Implement {sid} in `{EPIC_PATH[sid.split('-')[0]]}`"
                f"{deps}; run `make lint typecheck test`{' and `make eval`' if sid.split('-')[0] in {'POL', 'EXE', 'RAL', 'EXC', 'LED'} else ''}"
                f"{note}"
            )
        out += [
            "",
            f"**Checkpoint**: run the {sl['id']} exit check above and record the evidence before moving on.",
            "",
        ]
    out += [
        "## Dependencies",
        "",
        "Slices run in order. Inside a slice, follow each story's `deps` in `backlog/stories.yaml`; the build fails if a "
        "story depends on a later slice. P1 to P4 (portal) need S1 for the API shape; WEB-01 and WEB-02 can start at "
        "any time (backlog/milestones.md, Parallel work).",
        "",
        "## Implementation strategy",
        "",
        "1. Finish each slice to its exit check; each one is demonstrable on its own.",
        "2. S1 to S5 together are the demo's first six minutes; S6 to S9 complete the prototype.",
        "3. Per story: Superpowers test-driven development (red, green, refactor), then verification before completion.",
        "",
    ]
    (FEAT / "tasks.md").write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
