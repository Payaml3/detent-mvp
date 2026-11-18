"""Invariant 16: the engine refuses unscoped queries on organisation tables."""

import pytest
from detent.db.engine import OrgScopeViolation, _check_scope


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM payment_intents WHERE id = %(id)s",
        "UPDATE attempts SET status = 'FAILED' WHERE id = %(id)s",
        "DELETE FROM outbox WHERE id = 1",
        "select count(*) from detent.users",
    ],
)
def test_unscoped_queries_raise(sql: str) -> None:
    with pytest.raises(OrgScopeViolation):
        _check_scope(sql, {})


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM payment_intents WHERE org_id = %(o)s AND id = %(id)s",
        "SELECT 1",
        "INSERT INTO users (id, org_id) VALUES (1, 2)",
        "SELECT * FROM information_schema.columns",
    ],
)
def test_scoped_or_unrelated_queries_pass(sql: str) -> None:
    _check_scope(sql, {})


def test_explicit_cross_org_option_passes() -> None:
    _check_scope("SELECT id FROM jobs", {"cross_org": "worker claim"})
