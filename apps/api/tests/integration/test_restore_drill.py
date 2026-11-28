"""OPS-03: the restore drill restores into a separate database, is timed, and verifies every hash chain."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator

import pytest
from conftest import TEST_DB_URL
from decision_helpers import setup_decision_org
from detent.audit.log import verify_chain
from detent.clock import FrozenClock
from detent.ops.restore_drill import TARGET_SECONDS, DrillRefused, check_target, run_drill
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.db

TARGET_DB = f"detent_restore_drill_{os.getpid()}"


@pytest.fixture
def target() -> Iterator[str]:
    if shutil.which("pg_dump") is None or shutil.which("pg_restore") is None:
        pytest.skip("pg_dump and pg_restore are needed for the restore drill")
    admin = create_engine(TEST_DB_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{TARGET_DB}"'))
        c.execute(text(f'CREATE DATABASE "{TARGET_DB}"'))
    try:
        yield make_url(TEST_DB_URL).set(database=TARGET_DB).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{TARGET_DB}" WITH (FORCE)'))
        admin.dispose()


def test_the_drill_restores_and_verifies_every_chain(target: str, engine: Engine, clock: FrozenClock) -> None:
    setup_decision_org(engine, clock)  # at least one organisation with audit events
    # The test database is shared: another test may have broken a chain on purpose (test_evidence). The drill
    # must report exactly those, and nothing the restore itself introduced.
    with engine.connect() as c:
        orgs = (
            c.execute(text("SELECT org_id FROM audit_heads").execution_options(cross_org="test"))
            .scalars()
            .all()
        )
        broken = {o for o in orgs if not verify_chain(c, o).ok}
    res = run_drill(TEST_DB_URL, target)
    assert res.organisations == len(orgs) and res.chains_verified == len(orgs) - len(broken)
    assert all(any(o in m for o in broken) for m in res.mismatches), res.mismatches
    assert res.ok == (not broken)
    assert set(res.seconds) == {
        "fingerprint source", "backup (pg_dump)", "restore (pg_restore)", "verify (hash chains, heads, counts)",
    }  # fmt: skip
    assert 0 < res.total_seconds < TARGET_SECONDS
    assert ("PASSED" if not broken else "FAILED") in res.summary()[0]


def test_a_drill_never_targets_the_live_database() -> None:
    with pytest.raises(DrillRefused, match="separate database"):
        check_target(TEST_DB_URL, TEST_DB_URL)
    other = make_url(TEST_DB_URL).set(database="detent_prod").render_as_string(hide_password=False)
    with pytest.raises(DrillRefused, match="restore' or 'drill'"):
        check_target(TEST_DB_URL, other)
