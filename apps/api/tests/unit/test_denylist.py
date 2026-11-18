"""OPS-02: the independence check fails on any denylisted term and never prints the term."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from detent.settings import REPO_ROOT

SCRIPT = REPO_ROOT / "tools" / "check_denylist.py"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('hello')\n")
    (tmp_path / "docs.md").write_text("# Docs\nWe built this ourselves.\n")
    (tmp_path / "fixtures.yaml").write_text("name: Fictional Ltd\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _run(repo: Path, denylist: str | None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin"}
    if denylist is not None:
        env["DENYLIST"] = denylist
    return subprocess.run([sys.executable, str(SCRIPT), str(repo)], env=env, capture_output=True, text=True)


def test_clean_repo_passes(repo: Path) -> None:
    r = _run(repo, "acmecorp\nwidgetco\n")
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("where", ["src/a.py", "docs.md", "fixtures.yaml"])
def test_term_in_code_docs_or_fixtures_fails(repo: Path, where: str) -> None:
    (repo / where).write_text("This mentions AcmeCorp by name.\n")
    r = _run(repo, "acmecorp")
    assert r.returncode == 1
    assert f"{where}:1" in r.stderr
    assert "acmecorp" not in (r.stdout + r.stderr).lower(), "the term itself must never be printed"


def test_term_in_a_path_fails(repo: Path) -> None:
    (repo / "acmecorp_notes.txt").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    r = _run(repo, "acmecorp")
    assert r.returncode == 1 and "path matches" in r.stderr


@pytest.mark.parametrize("value", [None, "", "\n  \n", "# only a comment\n"])
def test_missing_denylist_fails_closed(repo: Path, value: str | None) -> None:
    r = _run(repo, value)
    assert r.returncode == 2 and "Failing closed" in r.stderr
