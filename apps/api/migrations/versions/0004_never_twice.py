"""S4 never paid twice: unknown resolution, retries, bank rail (EXE-05 to EXE-08, RAL-03 to RAL-07). SQL in 0004_never_twice.sql.

Revision ID: 0004
Revises: 0003
"""

from pathlib import Path

from alembic import op


def run_sql(sql: str) -> None:
    # Raw driver cursor with no parameters, so '%' in RAISE messages is literal.
    op.get_bind().connection.driver_connection.cursor().execute(sql)  # type: ignore[union-attr]


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    # Forward-only. Local resets drop the schema: `make db-reset`.
    raise NotImplementedError("forward-only migrations")
