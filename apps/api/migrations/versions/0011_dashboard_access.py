"""P2 dashboard access (DSH-01 to DSH-03, DSH-11). SQL in 0011_dashboard_access.sql.

Revision ID: 0011
Revises: 0010
"""

from pathlib import Path

from alembic import op


def run_sql(sql: str) -> None:
    # Raw driver cursor with no parameters, so '%' in RAISE messages is literal.
    op.get_bind().connection.driver_connection.cursor().execute(sql)  # type: ignore[union-attr]


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    # Forward-only. Local resets drop the schema: `make db-reset`.
    raise NotImplementedError("forward-only migrations")
