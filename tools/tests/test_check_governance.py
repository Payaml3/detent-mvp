from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pytest
from helpers import REPO, git, write

spec = importlib.util.spec_from_file_location("check_governance", REPO / "tools" / "check_governance.py")
assert spec and spec.loader
gov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gov)

TODAY = dt.date(2026, 11, 20)
SPECS_REG = """# Decisions

| ID | Conflict | Status |
|---|---|---|
| C-01 | x | **Confirmed** 2026-11-18 (founder, D-01) |
| G-01 | y | **Proposed** |

## Decision log

| ID | Decision | Date | Source |
|---|---|---|---|
| D-01 | something | 2026-11-18 | founder |
"""
FOUNDER_REG = """# Company

| ID | Decision | Status | Date | Source | Affected layers |
|---|---|---|---|---|---|
| B-01 | price | Open | 2026-11-20 | founder | Business |
"""
SLICES_BASE = "- id: S9\n  name: x\n"
SLICES_DONE = "- id: S9\n  name: x\n  status: done\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root / "specs/001-detent-mvp/decisions.md", SPECS_REG)
    write(root / "founder/decisions.md", FOUNDER_REG)
    write(root / "specs/001-detent-mvp/slices.yaml", SLICES_BASE)
    write(root / "founder/status.md", "# Status\n\nLast updated: 2026-11-19\n")
    write(root / "HANDOFF.md", "# HANDOFF\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    git(root, "checkout", "-qb", "work")
    return root


def commit(root: Path, path: str, text: str, msg: str = "change") -> None:
    write(root / path, text)
    git(root, "add", "-A")
    git(root, "commit", "-qm", msg)


def run(root: Path, today: dt.date = TODAY) -> tuple[list[str], list[str]]:
    return gov.check(root, "main", today)


def test_clean_branch_passes(repo: Path) -> None:
    commit(repo, "notes.md", "See D-01 and B-01.\n", "Cite D-01")
    assert run(repo) == ([], [])


def test_slice_done_without_handoff_fails(repo: Path) -> None:
    commit(repo, "specs/001-detent-mvp/slices.yaml", SLICES_DONE)
    errors, _ = run(repo)
    assert any("S9 marked done" in e for e in errors)


def test_slice_done_with_handoff_passes(repo: Path) -> None:
    commit(repo, "specs/001-detent-mvp/slices.yaml", SLICES_DONE)
    commit(repo, "HANDOFF.md", "# HANDOFF\nS9 done\n")
    assert run(repo)[0] == []


def test_unknown_id_in_doc_fails(repo: Path) -> None:
    commit(repo, "spec/x.md", "Per D-99, and B-07.\n")
    errors, _ = run(repo)
    assert any("spec/x.md: cites D-99" in e for e in errors)
    assert any("spec/x.md: cites B-07" in e for e in errors)


def test_unknown_id_in_commit_message_fails(repo: Path) -> None:
    commit(repo, "a.txt", "x\n", "Implements B-42")
    assert any("commit messages: cites B-42" in e for e in run(repo)[0])


def test_unchanged_docs_are_not_scanned(repo: Path) -> None:
    write(repo / "old.md", "D-77\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "old")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--ff-only", "work")
    git(repo, "checkout", "-qb", "next")
    commit(repo, "a.txt", "x\n")
    assert run(repo)[0] == []


def test_bad_status_fails(repo: Path) -> None:
    commit(repo, "founder/decisions.md", FOUNDER_REG.replace("| Open |", "| Agreed |"))
    errors, _ = run(repo)
    assert any("B-01 has status 'Agreed'" in e for e in errors)


def test_empty_status_fails(repo: Path) -> None:
    commit(repo, "founder/decisions.md", FOUNDER_REG.replace("| Open |", "|  |"))
    assert any("B-01 has status '(empty)'" in e for e in run(repo)[0])


@pytest.mark.parametrize("word", ["Approved", "Proposed", "Assumption", "Open", "Confirmed"])
def test_allowed_statuses(repo: Path, word: str) -> None:
    commit(repo, "founder/decisions.md", FOUNDER_REG.replace("| Open |", f"| **{word}** |"))
    assert run(repo)[0] == []


def test_stale_status_warns_only(repo: Path) -> None:
    errors, warnings = run(repo, today=dt.date(2026, 12, 10))
    assert errors == []
    assert any("more than 14 days ago" in w for w in warnings)


def test_missing_base_warns(repo: Path) -> None:
    errors, warnings = gov.check(repo, "no-such-branch", TODAY)
    assert errors == [] and any("not found" in w for w in warnings)


def test_main_exit_codes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert gov.main(["--root", str(repo), "--base", "main"]) == 0
    commit(repo, "x.md", "D-55\n")
    assert gov.main(["--root", str(repo), "--base", "main"]) == 1
    assert "governance: FAILED" in capsys.readouterr().out


def test_protocol_copy_elsewhere_fails(repo: Path) -> None:
    marker = gov.PROTOCOL_MARKER
    write(repo / gov.PROTOCOL, f"# Protocol\n\n{marker} → Execute\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "protocol")
    assert run(repo)[0] == []
    commit(repo, "founder/claude-project/instructions.md", f"Lifecycle: {marker}\n")
    errors, _ = run(repo)
    assert any("founder/claude-project/instructions.md: restates the protocol" in e for e in errors)


def test_untracked_copy_is_ignored(repo: Path) -> None:
    write(repo / "scratch.md", gov.PROTOCOL_MARKER)
    assert run(repo)[0] == []


def test_real_registers_have_valid_statuses() -> None:
    for reg in gov.REGISTERS:
        rows = gov.register_rows((REPO / reg).read_text(encoding="utf-8"))
        bad = [r for r, s in rows if s is not None and gov.status_word(s) not in gov.ALLOWED]
        assert bad == [], f"{reg}: {bad}"
