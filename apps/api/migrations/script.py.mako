"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""

from pathlib import Path

from alembic import op


def run_sql(sql: str) -> None:
    # Raw driver cursor with no parameters, so '%' in RAISE messages is literal.
    op.get_bind().connection.driver_connection.cursor().execute(sql)  # type: ignore[union-attr]

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql((Path(__file__).with_suffix(".sql")).read_text())


def downgrade() -> None:
    raise NotImplementedError("forward-only migrations")
