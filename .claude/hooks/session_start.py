"""SessionStart hook (startup, resume, compact): inject where the build is, in at most 25 lines."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c

MAX_LINES = 25
COMPACT_NOTE = "You were just compacted. Re-read HANDOFF.md and the current story before continuing."


def section(text: str, heading: str) -> list[str]:
    """Lines under the first `## <heading>...` up to the next `## `."""
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().lower().startswith(heading.lower())
            if inside:
                out.append(line)
            continue
        if inside:
            out.append(line)
    return out


def summary(root: Path, source: str) -> list[str]:
    cfg = c.load_config(root)
    try:
        handoff = (root / "HANDOFF.md").read_text(encoding="utf-8")
    except OSError:
        handoff = ""
    lines = ["Detent session context (from HANDOFF.md):"]
    lines += [ln for ln in section(handoff, "Where we are") if ln.startswith("|")]
    nxt = [ln for ln in section(handoff, "Next slice") if ln.strip()]
    if nxt:
        lines.append(nxt[0].lstrip("# ").strip())
    items: list[str] = []
    for ln in section(handoff, "Open founder items"):
        if re.match(r"^- ", ln):
            items.append(ln.strip())
        elif items and ln.startswith("  ") and ln.strip():
            items[-1] += " " + ln.strip()  # wrapped bullet
    if items:
        lines.append("Top open founder items:")
        lines += [ln if len(ln) <= 160 else ln[:157] + "..." for ln in items[:3]]
    lines.append(
        "Protocol: founder/operating-protocol.md. Context guard: warn at "
        f"{cfg['warn_pct']}% or {cfg['warn_tokens']:,} tokens, handoff at "
        f"{cfg['handoff_pct']}% or {cfg['handoff_tokens']:,} tokens."
    )
    if source == "compact":
        return [*lines[: MAX_LINES - 1], COMPACT_NOTE]
    return lines[:MAX_LINES]


def main() -> int:
    try:
        data = c.read_stdin_json(sys.stdin)
        text = "\n".join(summary(c.project_dir(), str(data.get("source") or "startup")))
        print(
            json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}})
        )
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
