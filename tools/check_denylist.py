"""Independence check (OPS-02): fail if any tracked file contains a denylisted term.

The denylist comes from the DENYLIST environment variable (one term per line), which CI fills from
the INDEPENDENCE_DENYLIST secret. It never lives in the repository. Matching is case-insensitive
and also checks file paths.

Output names the file and line only, never the matched term, so CI logs don't leak the list.
Exit codes: 0 clean, 1 match found, 2 denylist missing or empty (fails closed).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def load_terms(raw: str | None) -> list[str]:
    if not raw:
        return []
    return sorted({t.strip().lower() for t in raw.splitlines() if t.strip() and not t.startswith("#")})


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    return [root / p for p in out.decode().split("\0") if p]


def scan(files: list[Path], terms: list[str], root: Path) -> list[str]:
    hits: list[str] = []
    for f in files:
        rel = f.relative_to(root).as_posix()
        if any(t in rel.lower() for t in terms):
            hits.append(f"{rel}: path matches a denylisted term")
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue  # binary or removed
        for n, line in enumerate(text.splitlines(), start=1):
            low = line.lower()
            if any(t in low for t in terms):
                hits.append(f"{rel}:{n}: line matches a denylisted term")
    return hits


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    terms = load_terms(os.environ.get("DENYLIST"))
    if not terms:
        print(
            "denylist check: DENYLIST is empty or unset. Set the INDEPENDENCE_DENYLIST CI secret "
            "(one term per line). Failing closed.",
            file=sys.stderr,
        )
        return 2
    hits = scan(tracked_files(root), terms, root)
    if hits:
        print(f"denylist check: {len(hits)} match(es). Terms are not printed.", file=sys.stderr)
        for h in hits:
            print("  " + h, file=sys.stderr)
        return 1
    print(f"denylist check: clean ({len(terms)} terms, {len(tracked_files(root))} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
