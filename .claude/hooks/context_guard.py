"""UserPromptSubmit hook: warn, then ask for a handoff, as context fills up.

Reads usage from the status line's state file; if that is missing or older than 10 minutes, reads the
last assistant message's usage from the transcript. Each level fires once per session. Never blocks:
any error exits 0 with no output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c

WARN = (
    "Context at {pct}% ({tokens} tokens). Finish the current step, start nothing large, "
    "and keep answers short."
)
HANDOFF = (
    "Context at {pct}% ({tokens} tokens). Stop new work. Run the handoff skill (full mode if mid-slice), "
    "then tell the founder to start a new session."
)


def from_transcript(path: str | None) -> int | None:
    if not path:
        return None
    last: int | None = None
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            msg = entry.get("message") if isinstance(entry, dict) else None
            if entry.get("type") != "assistant" or not isinstance(msg, dict):
                continue
            u = msg.get("usage")
            if isinstance(u, dict):
                keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
                last = sum(int(u.get(k) or 0) for k in keys)
    return last


def current_usage(
    data: dict[str, Any], state: dict[str, Any], cfg: dict[str, Any]
) -> tuple[float | None, int | None]:
    fresh = isinstance(state.get("ts"), int | float) and c.now() - state["ts"] <= c.STALE_SECONDS
    if fresh and (state.get("used_pct") is not None or state.get("used_tokens") is not None):
        return state.get("used_pct"), state.get("used_tokens")
    tokens = from_transcript(data.get("transcript_path"))
    if tokens is None:
        return None, None
    window = int(cfg.get("context_window_tokens") or state.get("window_tokens") or c.FALLBACK_WINDOW)
    return tokens / window * 100, tokens


def main() -> int:
    try:
        data = c.read_stdin_json(sys.stdin)
        root = c.project_dir()
        cfg = c.load_config(root)
        path = c.state_path(root, str(data.get("session_id") or "unknown"))
        state = c.read_state(path)
        pct, tokens = current_usage(data, state, cfg)
        lvl = c.level(pct, tokens, cfg)
        fired = list(state.get("fired") or [])
        if lvl is None or lvl in fired:
            return 0
        fired = sorted({*fired, lvl, "warn"})  # a handoff also retires the warning
        c.write_state(path, {"fired": fired})
        if pct is None and tokens is not None:
            pct = tokens / c.FALLBACK_WINDOW * 100
        text = (HANDOFF if lvl == "handoff" else WARN).format(
            pct=f"{pct:.0f}" if pct is not None else "?", tokens=f"{tokens:,}" if tokens is not None else "?"
        )
        out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}
        print(json.dumps(out))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
