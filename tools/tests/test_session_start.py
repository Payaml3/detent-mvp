from __future__ import annotations

import json
from pathlib import Path

from helpers import REPO, run_script, write

HANDOFF = """# HANDOFF

## Where we are

| Slice | Status | Branch |
|---|---|---|
| S8 Proof | done | `main` |
| **S9 Demo** | **next** | branch from `main` |

## Next slice: S9 Demo-ready prototype in the EU

Read slices.yaml.

## Open founder items

- First item.
- Second item, which wraps
  onto a second line.
- Third item.
- Fourth item.
"""


def _run(project: Path, source: str) -> str:
    out = run_script(project / ".claude" / "hooks" / "session_start.py", {"source": source}, project)
    assert out.returncode == 0
    data = json.loads(out.stdout)["hookSpecificOutput"]
    assert data["hookEventName"] == "SessionStart"
    return str(data["additionalContext"])


def test_startup_summary(project: Path) -> None:
    write(project / "HANDOFF.md", HANDOFF)
    text = _run(project, "startup")
    assert "| **S9 Demo** | **next** | branch from `main` |" in text
    assert "Next slice: S9 Demo-ready prototype in the EU" in text
    assert "- Second item, which wraps onto a second line." in text
    assert "Fourth item" not in text
    assert "warn at 60% or 100,000 tokens, handoff at 75% or 140,000 tokens" in text
    assert "compacted" not in text


def test_compact_adds_reread_note(project: Path) -> None:
    write(project / "HANDOFF.md", HANDOFF)
    assert _run(project, "compact").endswith(
        "You were just compacted. Re-read HANDOFF.md and the current story before continuing."
    )


def test_at_most_25_lines_on_the_real_handoff(project: Path) -> None:
    write(project / "HANDOFF.md", (REPO / "HANDOFF.md").read_text(encoding="utf-8"))
    for source in ("startup", "resume", "compact"):
        assert len(_run(project, source).splitlines()) <= 25


def test_long_table_is_capped_and_keeps_compact_note(project: Path) -> None:
    rows = "\n".join(f"| S{i} | done | x |" for i in range(40))
    write(project / "HANDOFF.md", f"## Where we are\n\n| Slice | Status | Branch |\n|---|---|---|\n{rows}\n")
    text = _run(project, "compact").splitlines()
    assert len(text) == 25 and text[-1].startswith("You were just compacted")


def test_missing_handoff_and_bad_input_are_safe(project: Path) -> None:
    assert "Protocol:" in _run(project, "startup")
    out = run_script(project / ".claude" / "hooks" / "session_start.py", None, project, raw="[not json")
    assert out.returncode == 0 and out.stdout == ""
