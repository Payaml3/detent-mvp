from __future__ import annotations

import json
from pathlib import Path

from helpers import run_script

SCRIPT_NAME = "statusline.py"


def _run(project: Path, payload: object, raw: str | None = None):
    return run_script(project / ".claude" / "hooks" / SCRIPT_NAME, payload, project, raw)


def _payload(pct: float | None, size: int = 200_000, **extra: object) -> dict[str, object]:
    return {
        "session_id": "s1",
        "model": {"display_name": "Opus"},
        "context_window": {"used_percentage": pct, "context_window_size": size, **extra},
    }


def _state(project: Path) -> dict[str, object]:
    return json.loads((project / ".claude" / "state" / "context-s1.json").read_text(encoding="utf-8"))


def test_below_warn_shows_percentage_and_no_tag(project: Path) -> None:
    out = _run(project, _payload(42.0))
    assert out.returncode == 0
    assert "Opus" in out.stdout and "ctx 42%" in out.stdout
    assert "WARN" not in out.stdout and "HANDOFF" not in out.stdout


def test_warn_and_handoff_tags(project: Path) -> None:
    assert "WARN" in _run(project, _payload(61.0)).stdout
    assert "HANDOFF" in _run(project, _payload(76.0)).stdout


def test_tokens_trigger_first_on_a_large_window(project: Path) -> None:
    # 12% of 1M is 120k tokens: above warn_tokens (100k) although far below warn_pct.
    out = _run(project, _payload(12.0, size=1_000_000))
    assert "WARN" in out.stdout
    assert _state(project)["used_tokens"] == 120_000


def test_writes_state_file(project: Path) -> None:
    _run(project, _payload(50.0))
    state = _state(project)
    assert state["session_id"] == "s1"
    assert state["used_pct"] == 50.0 and state["used_tokens"] == 100_000 and state["window_tokens"] == 200_000
    assert isinstance(state["ts"], float)


def test_null_percentage(project: Path) -> None:
    out = _run(project, _payload(None))
    assert out.returncode == 0 and "ctx --" in out.stdout
    assert _state(project)["used_pct"] is None


def test_state_keeps_fired_levels(project: Path) -> None:
    path = project / ".claude" / "state" / "context-s1.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"fired": ["warn"]}), encoding="utf-8")
    _run(project, _payload(30.0))
    assert _state(project)["fired"] == ["warn"]


def test_bad_input_is_safe(project: Path) -> None:
    out = _run(project, None, raw="not json")
    assert out.returncode == 0 and out.stdout.strip() == "Claude"
