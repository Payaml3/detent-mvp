"""Stop hook: a slice marked done on this branch needs HANDOFF.md updated too.

Exits 2 (Claude keeps going and reads the message) only when the branch's commits mark a slice
`status: done` in slices.yaml and HANDOFF.md is unchanged since main. Respects stop_hook_active, so it
can't loop. Any error exits 0.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c

SLICES = "specs/001-detent-mvp/slices.yaml"
MESSAGE = "Slice marked done but HANDOFF.md not updated: run the handoff skill."


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


def needs_handoff(root: Path, base_ref: str = "origin/main") -> bool:
    base = c.git(root, "merge-base", base_ref, "HEAD") or c.git(root, "merge-base", "main", "HEAD")
    if not base:
        return False
    newly = done_slices(c.git(root, "show", f"HEAD:{SLICES}")) - done_slices(
        c.git(root, "show", f"{base}:{SLICES}")
    )
    if not newly:
        return False
    changed = c.git(root, "diff", "--name-only", base, "HEAD", "--", "HANDOFF.md")
    return changed == ""


def main() -> int:
    try:
        data = c.read_stdin_json(sys.stdin)
        if data.get("stop_hook_active"):
            return 0
        if needs_handoff(c.project_dir()):
            print(MESSAGE, file=sys.stderr)
            return 2
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
