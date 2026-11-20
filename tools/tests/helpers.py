"""Shared helpers for the hook and governance tests: run a script with JSON on stdin in a throwaway project."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude" / "hooks"


def run_script(
    script: Path, payload: Any, project: Path, raw: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    stdin = raw if raw is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal project: hooks, governance.json and a HANDOFF.md."""
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    shutil.copytree(HOOKS, root / ".claude" / "hooks")
    shutil.copy(REPO / ".claude" / "governance.json", root / ".claude" / "governance.json")
    return root


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
