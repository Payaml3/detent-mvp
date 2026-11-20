from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from helpers import REPO

sys.path.insert(0, str(REPO / "tools"))
spec = importlib.util.spec_from_file_location("build_pages", REPO / "tools" / "build_pages.py")
assert spec and spec.loader
pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pages)


def test_snapshot_takes_the_headline_figures(tmp_path: Path) -> None:
    results = {
        "date": "2026-12-01",
        "commit": "abcdef1234567890",
        "gate": {"passed": True},
        "agent_answers": "recorded stand-ins",
        "networks": "local",
        "suites": {
            "attacks": {"count": 101, "safety": {"unauthorised_executions": 0}},
            "faults": {"count": 31, "safety": {"duplicates": 0}},
            "interpretation": {"count": 30, "canonical": {"correct": 10, "runs": 10}, "invented_values": 0},
            "reconciliation": {"count": 500, "match_rate": "99.40%"},
        },
    }
    path = tmp_path / "results.json"
    path.write_text(json.dumps(results))
    snap = pages.snapshot(path)
    assert snap["gate_passed"] is True
    assert snap["commit"] == "abcdef123456"
    assert snap["attacks"] == {"count": 101, "unauthorised_executions": 0}
    assert snap["faults"] == {"count": 31, "duplicates": 0}
    assert snap["interpretation"]["canonical_correct"] == 10


def test_every_launch_criterion_and_journey_step_is_read() -> None:
    _md, scope = pages.build_scope()
    assert [c["code"] for c in scope["crit"]] == [f"L{n}" for n in range(1, 9)]
    assert all(c["ids"] for c in scope["crit"]), "each launch criterion traces to at least one story"
    _md, journey = pages.build_journey()
    assert {s["layer"] for s in journey["steps"]} == set(pages.LAYERS)
    assert journey["demo"], "the demo timeline is parsed from spec/11"


def test_html_pages_carry_the_prototype_label() -> None:
    _md, scope = pages.build_scope()
    _md, journey = pages.build_journey()
    for page in (pages.render_scope(scope), pages.render_journey(journey)):
        assert "<title>" in page
        assert "prototype on test networks only" in page
