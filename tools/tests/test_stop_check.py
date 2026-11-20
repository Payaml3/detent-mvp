from __future__ import annotations

from pathlib import Path

import pytest
from helpers import git, run_script, write

SLICES = "specs/001-detent-mvp/slices.yaml"
BASE_SLICES = '- id: S8\n  status: done\n\n- id: S9\n  name: "Demo"\n  stories: [A]\n'
DONE_SLICES = '- id: S8\n  status: done\n\n- id: S9\n  name: "Demo"\n  status: done\n  stories: [A]\n'
MESSAGE = "Slice marked done but HANDOFF.md not updated: run the handoff skill."


@pytest.fixture
def repo(project: Path) -> Path:
    git(project, "init", "-q", "-b", "main")
    write(project / SLICES, BASE_SLICES)
    write(project / "HANDOFF.md", "# HANDOFF\n")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "base")
    git(project, "checkout", "-qb", "s9")
    return project


def _run(repo: Path, payload: object, raw: str | None = None):
    return run_script(repo / ".claude" / "hooks" / "stop_check.py", payload, repo, raw)


def _commit(repo: Path, path: str, text: str, msg: str) -> None:
    write(repo / path, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)


def test_blocks_when_slice_done_without_handoff(repo: Path) -> None:
    _commit(repo, SLICES, DONE_SLICES, "S9 done")
    out = _run(repo, {"stop_hook_active": False})
    assert out.returncode == 2 and MESSAGE in out.stderr


def test_passes_when_handoff_updated(repo: Path) -> None:
    _commit(repo, SLICES, DONE_SLICES, "S9 done")
    _commit(repo, "HANDOFF.md", "# HANDOFF\nS9 done\n", "HANDOFF: S9")
    assert _run(repo, {}).returncode == 0


def test_passes_when_no_slice_changes(repo: Path) -> None:
    _commit(repo, "notes.md", "x\n", "notes")
    assert _run(repo, {}).returncode == 0


def test_respects_stop_hook_active(repo: Path) -> None:
    _commit(repo, SLICES, DONE_SLICES, "S9 done")
    assert _run(repo, {"stop_hook_active": True}).returncode == 0


def test_errors_are_safe(repo: Path, tmp_path: Path) -> None:
    assert _run(repo, None, raw="{oops").returncode == 0
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    out = run_script(repo / ".claude" / "hooks" / "stop_check.py", {}, not_a_repo)
    assert out.returncode == 0
