"""AUD-01: `detent audit verify` reports an intact chain and detects a tampered row."""

from __future__ import annotations

import subprocess
import sys

import pytest
from conftest import OrgFixture, child_env
from detent.audit.log import Actor, append
from detent.clock import FrozenClock
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


def verify(org_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "detent", "audit", "verify", "--org", org_id],
        capture_output=True,
        text=True,
        env=child_env(),
        timeout=60,
    )


def test_verify_command(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    with engine.begin() as c:
        for i in range(3):
            append(c, clock, org_id=org.id, actor=Actor.system("t"), kind="t", payload={"i": i})
    ok = verify(org.id)
    assert ok.returncode == 0 and "OK" in ok.stdout and "3 events" in ok.stdout
    with engine.begin() as c:
        c.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_append_only"))
        c.execute(
            text("UPDATE audit_events SET actor='usr_mallory' WHERE org_id=:o AND seq=2"), {"o": org.id}
        )
        c.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_append_only"))
    bad = verify(org.id)
    assert bad.returncode == 1 and "seq 2" in bad.stdout


def test_trigger_rejects_update_and_delete(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    with engine.begin() as c:
        append(c, clock, org_id=org.id, actor=Actor.system("t"), kind="t")
    for stmt in [
        "UPDATE audit_events SET kind='x' WHERE org_id=:o",
        "DELETE FROM audit_events WHERE org_id=:o",
    ]:
        with pytest.raises(Exception, match="append-only"), engine.begin() as c:
            c.execute(text(stmt), {"o": org.id})
