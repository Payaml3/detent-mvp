"""Slice L group 3: rail health, the circuit breaker and rail connections (RAL-08, RAL-09). SQL in 0018_rails.sql.

Revision ID: 0018
Revises: 0017
"""

from pathlib import Path

from alembic import op


def run_sql(sql: str) -> None:
    # Raw driver cursor with no parameters, so '%' in RAISE messages is literal.
    op.get_bind().connection.driver_connection.cursor().execute(sql)  # type: ignore[union-attr]


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    # Forward-only. Local resets drop the schema: `make db-reset`.
    raise NotImplementedError("forward-only migrations")
