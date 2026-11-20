"""Governance check for the operating protocol (run as `make governance` and in CI).

Fails if, between the base branch and HEAD:
  1. a slice is newly marked `status: done` in slices.yaml but HANDOFF.md did not change;
  2. a commit message or a changed Markdown file cites a D-xx or B-xx ID that no register defines;
  3. any register row has a status other than Approved, Proposed, Assumption, Open or Confirmed.
  4. the protocol's marker line appears in any tracked file other than founder/operating-protocol.md
     (the protocol lives in one place).
Warns (does not fail) if founder/status.md "Last updated" is more than 14 days old.

Python 3.12, standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

SLICES = "specs/001-detent-mvp/slices.yaml"
REGISTERS = ("specs/001-detent-mvp/decisions.md", "founder/decisions.md")
STATUS_FILE = "founder/status.md"
ALLOWED = {"Approved", "Proposed", "Assumption", "Open", "Confirmed"}
ROW_ID = re.compile(r"^[A-Z]-\d+$")
CITED = re.compile(r"\b([DB]-\d{2,})\b")
STALE_DAYS = 14
PROTOCOL = "founder/operating-protocol.md"
# Built from parts so this file doesn't contain the marker itself.
PROTOCOL_MARKER = " → ".join(["Define", "Analyse", "Decide"])


def git(root: Path, *args: str) -> str | None:
    out = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=False
    )
    return out.stdout if out.returncode == 0 else None


def done_slices(text: str | None) -> set[str]:
    done: set[str] = set()
    current = None
    for line in (text or "").splitlines():
        m = re.match(r"^-\s+id:\s*['\"]?([\w-]+)", line)
        if m:
            current = m.group(1)
        elif current and re.match(r"^\s+status:\s*['\"]?done\b", line):
            done.add(current)
    return done


def register_rows(text: str) -> list[tuple[str, str | None]]:
    """(ID, status cell or None) for every table row whose first cell is an ID like D-01 or B-01."""
    rows: list[tuple[str, str | None]] = []
    header: list[str] | None = None
    for line in text.splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if set(line.strip()) <= set("|-: "):
            continue
        first = cells[0].strip("*` ")
        if not ROW_ID.match(first):
            header = [x.strip("* ").lower() for x in cells]
            continue
        status = None
        if header and "status" in header and header.index("status") < len(cells):
            status = cells[header.index("status")]
        rows.append((first, status))
    return rows


def status_word(cell: str) -> str:
    words = cell.replace("*", " ").split()
    return words[0].strip(".,:;") if words else ""


def check(root: Path, base_ref: str, today: dt.date) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    known: set[str] = set()
    for reg in REGISTERS:
        path = root / reg
        if not path.exists():
            continue
        for rid, status in register_rows(path.read_text(encoding="utf-8")):
            known.add(rid)
            if status is not None and status_word(status) not in ALLOWED:
                errors.append(
                    f"{reg}: {rid} has status '{status_word(status) or '(empty)'}'; use one of {sorted(ALLOWED)}"
                )

    base = (git(root, "merge-base", base_ref, "HEAD") or "").strip()
    if not base:
        warnings.append(f"base '{base_ref}' not found; skipped the branch checks (fetch it first)")
    else:
        newly = done_slices(git(root, "show", f"HEAD:{SLICES}")) - done_slices(
            git(root, "show", f"{base}:{SLICES}")
        )
        handoff_changed = bool(
            (git(root, "diff", "--name-only", base, "HEAD", "--", "HANDOFF.md") or "").strip()
        )
        if newly and not handoff_changed:
            errors.append(
                f"slice {', '.join(sorted(newly))} marked done in {SLICES} but HANDOFF.md not changed"
            )

        sources: list[tuple[str, str]] = [
            ("commit messages", git(root, "log", "--format=%B", f"{base}..HEAD") or "")
        ]
        changed = (git(root, "diff", "--name-only", "--diff-filter=AMR", base, "HEAD") or "").split()
        for name in changed:
            if name.endswith(".md") and (root / name).exists():
                sources.append((name, (root / name).read_text(encoding="utf-8")))
        for where, text in sources:
            for rid in sorted(set(CITED.findall(text)) - known):
                errors.append(f"{where}: cites {rid}, which no register defines")

    for name in (git(root, "ls-files") or "").splitlines():
        if name == PROTOCOL:
            continue
        path = root / name
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if PROTOCOL_MARKER in text:
            errors.append(f"{name}: restates the protocol ('{PROTOCOL_MARKER}'); point to {PROTOCOL} instead")

    status_path = root / STATUS_FILE
    if status_path.exists():
        m = re.search(r"Last updated:\s*(\d{4}-\d{2}-\d{2})", status_path.read_text(encoding="utf-8"))
        if not m:
            warnings.append(f"{STATUS_FILE} has no 'Last updated: YYYY-MM-DD' line")
        elif (today - dt.date.fromisoformat(m.group(1))).days > STALE_DAYS:
            warnings.append(f"{STATUS_FILE} last updated {m.group(1)}, more than {STALE_DAYS} days ago")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=os.environ.get("GOVERNANCE_BASE", "origin/main"))
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args(argv)
    errors, warnings = check(args.root, args.base, dt.date.today())
    gha = os.environ.get("GITHUB_ACTIONS") == "true"
    for w in warnings:
        print(f"::warning::{w}" if gha else f"warning: {w}")
    for e in errors:
        print(f"::error::{e}" if gha else f"error: {e}")
    print("governance: FAILED" if errors else "governance: OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
