"""Alembic environment. Migrations are plain SQL files executed in order."""

from __future__ import annotations

from alembic import context
from detent.settings import get_settings
from sqlalchemy import create_engine, text

url = context.config.attributes.get("database_url") or get_settings().database_url


def run_migrations_online() -> None:
    # Every migration runs with search_path=detent. Only 0001 to 0005 set it themselves, so a run that starts
    # after 0005 (an upgrade of a deployed database) must not depend on it: the live deploy broke on 0016.
    engine = create_engine(url, connect_args={"options": "-c search_path=detent"})
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS detent"))
    with engine.connect() as conn:
        context.configure(connection=conn, version_table_schema="detent", transactional_ddl=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported")
run_migrations_online()
