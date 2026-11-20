"""Shared helpers for the context guard hooks. Python 3.12, standard library only."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "warn_pct": 60,
    "handoff_pct": 75,
    "warn_tokens": 100_000,
    "handoff_tokens": 140_000,
    "context_window_tokens": None,
}
FALLBACK_WINDOW = 200_000  # used only when neither the config nor Claude Code gives a size
STALE_SECONDS = 600


def project_dir() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def load_config(root: Path) -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads((root / ".claude" / "governance.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def read_stdin_json(stream: Any) -> dict[str, Any]:
    data = json.loads(stream.read() or "{}")
    return data if isinstance(data, dict) else {}


def state_path(root: Path, session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
    return root / ".claude" / "state" / f"context-{safe}.json"


def read_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(path: Path, updates: dict[str, Any]) -> None:
    """Merge `updates` into the state file, keeping keys other writers own (for example `fired`)."""
    state = read_state(path)
    state.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(path)


def now() -> float:
    return time.time()


def level(pct: float | None, tokens: int | None, cfg: dict[str, Any]) -> str | None:
    """'handoff', 'warn' or None. Each level fires at whichever comes first: the percentage or the tokens."""

    def hit(pct_key: str, tok_key: str) -> bool:
        p, t = cfg.get(pct_key), cfg.get(tok_key)
        return (pct is not None and p is not None and pct >= p) or (
            tokens is not None and t is not None and tokens >= t
        )

    if hit("handoff_pct", "handoff_tokens"):
        return "handoff"
    if hit("warn_pct", "warn_tokens"):
        return "warn"
    return None


def git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None
