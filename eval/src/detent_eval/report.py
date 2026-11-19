"""EVL-06: the dated results report (HTML and Markdown) from ``results.json``, and the website's file.

The report is generated, never hand-edited: every figure comes from ``results.json``. Each page carries the
caveat "Test-network evaluation on synthetic data, <date>. Not production results." and says where agent
answers came from (recorded stand-ins unless the run was live).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from detent.settings import REPO_ROOT
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

TEMPLATES = REPO_ROOT / "eval" / "templates"
SITE_RESULTS = REPO_ROOT / "apps" / "site" / "src" / "data" / "results.json"


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def view(results: dict[str, Any]) -> dict[str, Any]:
    """The figures the templates show, in reading order."""
    s = results.get("suites", {})
    att, flt = s.get("attacks") or {}, s.get("faults") or {}
    interp, agr = s.get("interpretation") or {}, s.get("agreement") or {}
    lat, rec = s.get("latency") or {}, s.get("reconciliation") or {}
    safety = results.get("safety_summary") or {}
    headline = []
    if att:
        headline.append(
            (
                f"{att.get('safety', {}).get('unauthorised_executions', 0)} of {att.get('count', 0)}",
                "attack scenarios led to an unauthorised execution",
            )
        )
    if flt:
        headline.append(
            (
                f"{flt.get('safety', {}).get('duplicates', 0)} of {flt.get('count', 0)}",
                "fault scenarios led to a duplicate payment",
            )
        )
    if interp.get("canonical"):
        c = interp["canonical"]
        headline.append(
            (f"{c.get('correct')}/{c.get('runs')}", "runs of the canonical invoice read correctly")
        )
    if interp:
        headline.append(
            (str(interp.get("invented_values", 0)), "invented values across the interpretation set")
        )
    if rec:
        headline.append(
            (rec.get("match_rate", "n/a"), f"reconciliation match rate on {rec.get('count')} items")
        )
    return {
        "r": results,
        "gate": results.get("gate") or {"passed": False, "reasons": ["no gate result"]},
        "safety": safety,
        "headline": headline,
        "att": att,
        "flt": flt,
        "interp": interp,
        "agr": agr,
        "lat": lat,
        "rec": rec,
        "pct": _pct,
    }


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def write_reports(results: dict[str, Any], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    v = view(results)
    env = _env()
    (out / "report.html").write_text(env.get_template("report.html.j2").render(**v))
    (out / "report.md").write_text(env.get_template("report.md.j2").render(**v))


def site_figures(results: dict[str, Any]) -> dict[str, Any]:
    """The website's Measured results file: a date and captioned figures (apps/site/src/lib/results.mjs)."""
    return {
        "date": results["date"],
        "commit": results.get("commit"),
        "figures": [{"value": value, "caption": caption} for value, caption in view(results)["headline"]],
    }


def publish(results: dict[str, Any], target: Path = SITE_RESULTS) -> str:
    """Write the site's results file. Refuses a run whose gate failed or that didn't run every suite."""
    if not (results.get("gate") or {}).get("passed"):
        raise SystemExit("refusing to publish: the release gate did not pass for this run")
    missing = {"attacks", "faults", "interpretation"} - set(results.get("suites", {}))
    if missing:
        raise SystemExit(f"refusing to publish: suites missing from this run: {', '.join(sorted(missing))}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(site_figures(results), indent=2) + "\n")
    return f"wrote {target}"
