"""S8 findings from the attack suite: an attempt only for a READY payment. SQL in 0008_attempt_guard.sql.

Revision ID: 0008
Revises: 0007
"""

from pathlib import Path

from alembic import op


def run_sql(sql: str) -> None:
    # Raw driver cursor with no parameters, so '%' in RAISE messages is literal.
    op.get_bind().connection.driver_connection.cursor().execute(sql)  # type: ignore[union-attr]


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    # Forward-only. Local resets drop the schema: `make db-reset`.
    raise NotImplementedError("forward-only migrations")
