from __future__ import annotations

import json
import time
from pathlib import Path

from helpers import run_script, write


def _run(project: Path, payload: object, raw: str | None = None):
    return run_script(project / ".claude" / "hooks" / "context_guard.py", payload, project, raw)


def _state_path(project: Path) -> Path:
    return project / ".claude" / "state" / "context-s1.json"


def _set_state(project: Path, pct: float | None, tokens: int | None, age: float = 0, **extra: object) -> None:
    state = {
        "session_id": "s1",
        "used_pct": pct,
        "used_tokens": tokens,
        "window_tokens": 200_000,
        "ts": time.time() - age,
        **extra,
    }
    write(_state_path(project), json.dumps(state))


def _context(out) -> str | None:
    if not out.stdout.strip():
        return None
    return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def _transcript(tmp: Path, tokens: tuple[int, int, int]) -> Path:
    path = tmp / "t.jsonl"
    inp, create, read = tokens
    lines = [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {"type": "assistant", "message": {"usage": {"input_tokens": 10, "cache_read_input_tokens": 10}}},
        {
            "type": "assistant",
            "message": {
                "usage": {
                    "input_tokens": inp,
                    "cache_creation_input_tokens": create,
                    "cache_read_input_tokens": read,
                    "output_tokens": 999_999,
                }
            },
        },
        {"type": "user", "message": {"role": "user", "content": "next"}},
    ]
    write(path, "\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    return path


PROMPT = {"session_id": "s1", "hook_event_name": "UserPromptSubmit", "prompt": "go"}


def test_silent_below_warn(project: Path) -> None:
    _set_state(project, 40.0, 80_000)
    out = _run(project, PROMPT)
    assert out.returncode == 0 and _context(out) is None


def test_warn_fires_once(project: Path) -> None:
    _set_state(project, 62.0, 124_000)
    first = _context(_run(project, PROMPT))
    assert first == (
        "Context at 62% (124,000 tokens). Finish the current step, start nothing large, "
        "and keep answers short."
    )
    assert _context(_run(project, PROMPT)) is None
    assert json.loads(_state_path(project).read_text(encoding="utf-8"))["fired"] == ["warn"]


def test_handoff_fires_once_after_warn(project: Path) -> None:
    _set_state(project, 62.0, 90_000)
    assert "Finish the current step" in (_context(_run(project, PROMPT)) or "")
    _set_state(project, 76.0, 152_000, fired=["warn"])
    text = _context(_run(project, PROMPT)) or ""
    assert text.startswith("Context at 76% (152,000 tokens). Stop new work. Run the handoff skill now")
    assert _context(_run(project, PROMPT)) is None


def test_tokens_fire_before_percentage(project: Path) -> None:
    _set_state(project, 15.0, 150_000)  # a 1M window: 15% but past handoff_tokens
    assert "Stop new work" in (_context(_run(project, PROMPT)) or "")


def test_transcript_fallback_when_state_missing(project: Path, tmp_path: Path) -> None:
    t = _transcript(tmp_path, (1_000, 20_000, 110_000))  # 131k of 200k = 65.5%
    text = _context(_run(project, {**PROMPT, "transcript_path": str(t)})) or ""
    assert text.startswith("Context at 66% (131,000 tokens). Finish the current step")


def test_transcript_fallback_when_state_stale(project: Path, tmp_path: Path) -> None:
    _set_state(project, 10.0, 20_000, age=11 * 60)
    t = _transcript(tmp_path, (0, 0, 150_000))
    assert "Stop new work" in (_context(_run(project, {**PROMPT, "transcript_path": str(t)})) or "")


def test_transcript_fallback_when_percentage_null(project: Path, tmp_path: Path) -> None:
    _set_state(project, None, None)
    t = _transcript(tmp_path, (0, 0, 125_000))
    assert "Finish the current step" in (_context(_run(project, {**PROMPT, "transcript_path": str(t)})) or "")


def test_fresh_state_wins_over_transcript(project: Path, tmp_path: Path) -> None:
    _set_state(project, 20.0, 40_000)
    t = _transcript(tmp_path, (0, 0, 150_000))
    assert _context(_run(project, {**PROMPT, "transcript_path": str(t)})) is None


def test_errors_are_silent(project: Path, tmp_path: Path) -> None:
    for out in (
        _run(project, None, raw="{broken"),
        _run(project, {**PROMPT, "transcript_path": str(tmp_path / "missing.jsonl")}),
    ):
        assert out.returncode == 0 and out.stdout == "" and out.stderr == ""
    write(project / ".claude" / "governance.json", "not json")
    _set_state(project, 80.0, 160_000)
    assert _run(project, PROMPT).returncode == 0  # falls back to the default limits
