"""Engine, transactions and the organisation-scope guard (FND-03, invariant 16).

The guard inspects every SQL statement sent to Postgres. A SELECT, UPDATE or DELETE that touches a
``detent`` table must mention ``org_id``. A deliberate cross-organisation statement (for example the
worker claiming the next due job from any organisation) must say so with
``execution_options(cross_org="<reason>")``. The guard fails closed: it raises before the statement
runs.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, event

from detent.db.tables import ALL_TABLE_NAMES

_TABLE_RE = re.compile(r"\b(?:detent\.)?(" + "|".join(sorted(ALL_TABLE_NAMES)) + r")\b")
_VERB_RE = re.compile(r"^\s*(?:WITH\b.*?\)\s*)?(SELECT|UPDATE|DELETE)\b", re.IGNORECASE | re.DOTALL)


class OrgScopeViolation(RuntimeError):
    """A query touched organisation data without filtering by org_id."""


def _check_scope(statement: str, options: dict[str, Any]) -> None:
    if options.get("cross_org"):
        return
    if not _VERB_RE.match(statement):
        return
    if not _TABLE_RE.search(statement):
        return
    if "org_id" not in statement:
        tables = sorted(set(_TABLE_RE.findall(statement)))
        raise OrgScopeViolation(
            f"query on {tables} does not filter by org_id; scope it, or pass "
            f"execution_options(cross_org='<reason>') (invariant 16)"
        )


def make_engine(url: str, *, pool_size: int = 10, echo: bool = False) -> Engine:
    engine = create_engine(
        url,
        pool_size=pool_size,
        max_overflow=10,
        pool_pre_ping=True,
        echo=echo,
        connect_args={"options": "-c search_path=detent -c timezone=UTC"},
    )

    @event.listens_for(engine, "before_cursor_execute")
    def _guard(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        options = context.execution_options if context is not None else conn.get_execution_options()
        _check_scope(statement, dict(options))

    return engine


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """One database transaction. Commits on success, rolls back on any exception."""
    with engine.begin() as conn:
        yield conn
