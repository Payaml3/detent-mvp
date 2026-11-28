"""Slice L group 2: shadow imports, the shadow-phase report and mode gates (SHD-01 to SHD-04, DSH-13). SQL in 0017_shadow.sql.

Revision ID: 0017
Revises: 0016
"""

from pathlib import Path

from alembic import op


def run_sql(sql: str) -> None:
    # Raw driver cursor with no parameters, so '%' in RAISE messages is literal.
    op.get_bind().connection.driver_connection.cursor().execute(sql)  # type: ignore[union-attr]


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    # Forward-only. Local resets drop the schema: `make db-reset`.
    raise NotImplementedError("forward-only migrations")
