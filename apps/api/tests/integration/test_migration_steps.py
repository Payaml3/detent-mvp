"""Each migration applies on its own, in a fresh run, as when a deployed database is upgraded.

The suite's database is migrated in one run from empty, where the session settings of an early migration carry
over to later ones. A deployed database is upgraded later, from its current revision, in a new connection: the
live demo failed exactly there (0016: relation "incidents" does not exist).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from conftest import TEST_DB_URL
from detent.settings import REPO_ROOT
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DB_NAME = "detent_migration_steps"


@pytest.fixture
def step_db_url() -> Iterator[str]:
    admin = create_engine(TEST_DB_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {DB_NAME}"))
    try:
        yield make_url(TEST_DB_URL).set(database=DB_NAME).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)"))
        admin.dispose()


def test_every_migration_applies_in_its_own_run(step_db_url: str) -> None:
    cfg = Config(str(REPO_ROOT / "apps" / "api" / "alembic.ini"))
    cfg.attributes["database_url"] = step_db_url
    revisions = [r.revision for r in reversed(list(ScriptDirectory.from_config(cfg).walk_revisions()))]
    assert len(revisions) > 5
    for rev in revisions:
        command.upgrade(cfg, rev)  # one revision per run, each in a new connection
    engine = create_engine(step_db_url)
    with engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM detent.alembic_version")).scalar_one()
    engine.dispose()
    assert current == revisions[-1]
