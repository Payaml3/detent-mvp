"""Backup and restore drill (OPS-03, spec/10 Runbooks).

The drill restores a copy of the database into a separate target database, times each step, and proves nothing
was lost: every organisation's audit hash chain verifies on the target, and its chain head (seq and hash)
and the row counts of the decision, audit and ledger tables match the source. In production the copy is the
provider's point-in-time restore to a new branch (Neon); locally and in tests it is ``pg_dump`` and
``pg_restore``.

Safety: the target must be a different database whose name contains ``restore`` or ``drill``, so a drill can
never overwrite the live database. Durations use a monotonic timer (they are not timestamps).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import make_url

from detent.audit.log import verify_chain

TARGET_SECONDS = 3600
COUNTED = ("decisions", "audit_events", "journal_entries", "postings", "payment_intents", "attempts")
CROSS = {"cross_org": "the restore drill compares every organisation"}


class DrillRefused(ValueError):
    pass


@dataclass
class DrillResult:
    ok: bool
    seconds: dict[str, float] = field(default_factory=dict)
    organisations: int = 0
    chains_verified: int = 0
    mismatches: list[str] = field(default_factory=list)

    @property
    def total_seconds(self) -> float:
        return round(sum(self.seconds.values()), 2)

    def summary(self) -> list[str]:
        lines = [f"restore drill {'PASSED' if self.ok else 'FAILED'} in {self.total_seconds:.1f} s "
                 f"(target under {TARGET_SECONDS // 60} minutes)"]  # fmt: skip
        lines += [f"  {step}: {secs:.2f} s" for step, secs in self.seconds.items()]
        lines.append(f"  organisations: {self.organisations}; hash chains verified: {self.chains_verified}")
        lines += [f"  mismatch: {m}" for m in self.mismatches]
        return lines


def _libpq(url: str) -> str:
    """A SQLAlchemy URL as a libpq one, for pg_dump and pg_restore."""
    u = make_url(url)
    return u.set(drivername="postgresql").render_as_string(hide_password=False)


def fingerprint(conn: Connection) -> dict[str, Any]:
    heads = {
        str(r.org_id): (int(r.seq), str(r.hash))
        for r in conn.execute(text("SELECT org_id, seq, hash FROM audit_heads").execution_options(**CROSS))
    }
    counts = {
        t: int(conn.execute(text(f"SELECT count(*) FROM {t}").execution_options(**CROSS)).scalar_one())  # noqa: S608
        for t in COUNTED
    }
    return {"heads": heads, "counts": counts}


def check_target(source_url: str, target_url: str) -> None:
    s, t = make_url(source_url), make_url(target_url)
    if (s.host, s.port, s.database) == (t.host, t.port, t.database):
        raise DrillRefused("the target is the source database; a drill restores into a separate database")
    name = (t.database or "").lower()
    if "restore" not in name and "drill" not in name:
        raise DrillRefused(
            "the target database's name must contain 'restore' or 'drill', so a drill never overwrites it"
        )


def run_drill(source_url: str, target_url: str) -> DrillResult:
    check_target(source_url, target_url)
    for tool in ("pg_dump", "pg_restore"):
        if shutil.which(tool) is None:
            raise DrillRefused(f"{tool} is not installed")
    res = DrillResult(ok=False)
    src = create_engine(source_url)
    tgt = create_engine(target_url)
    try:
        t0 = time.monotonic()
        with src.connect() as conn:
            before = fingerprint(conn)
        res.seconds["fingerprint source"] = round(time.monotonic() - t0, 2)
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "drill.dump"
            t0 = time.monotonic()
            subprocess.run(  # noqa: S603 (fixed arguments)
                ["pg_dump", "--format=custom", "--no-owner", "--file", str(dump), _libpq(source_url)],  # noqa: S607
                check=True, capture_output=True,
            )  # fmt: skip
            res.seconds["backup (pg_dump)"] = round(time.monotonic() - t0, 2)
            t0 = time.monotonic()
            subprocess.run(  # noqa: S603
                ["pg_restore", "--clean", "--if-exists", "--no-owner",  # noqa: S607
                 "--dbname", _libpq(target_url), str(dump)],
                check=True, capture_output=True,
            )  # fmt: skip
            res.seconds["restore (pg_restore)"] = round(time.monotonic() - t0, 2)
        t0 = time.monotonic()
        with tgt.connect() as conn:
            after = fingerprint(conn)
            res.organisations = len(before["heads"])
            for org in sorted(before["heads"]):
                st = verify_chain(conn, org)
                if st.ok:
                    res.chains_verified += 1
                else:
                    res.mismatches.append(f"{org}: hash chain broken ({st.problem})")
                if after["heads"].get(org) != before["heads"][org]:
                    res.mismatches.append(f"{org}: chain head differs after restore")
        for t, n in before["counts"].items():
            if after["counts"].get(t) != n:
                res.mismatches.append(f"{t}: {n} rows before, {after['counts'].get(t)} after")
        res.seconds["verify (hash chains, heads, counts)"] = round(time.monotonic() - t0, 2)
    finally:
        src.dispose()
        tgt.dispose()
    res.ok = not res.mismatches and res.total_seconds < TARGET_SECONDS
    return res
