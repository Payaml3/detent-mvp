"""Organisation-scoped repository base (invariant 16).

A repository is constructed for one organisation and adds ``org_id = :org`` to every statement it
builds. There is no way to construct one without an org_id.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, Delete, Select, Table, Update, delete, select, update

from detent.domain.ids import Prefix, is_valid


class OrgScoped:
    def __init__(self, conn: Connection, org_id: str) -> None:
        if not org_id or not is_valid(org_id, Prefix.ORG):
            raise ValueError(f"a repository needs a valid org_id, got {org_id!r}")
        self.conn = conn
        self.org_id = org_id

    def select(self, table: Table, *cols: Any) -> Select[Any]:
        stmt = select(*cols) if cols else select(table)
        return stmt.where(table.c.org_id == self.org_id)

    def update(self, table: Table) -> Update:
        return update(table).where(table.c.org_id == self.org_id)

    def delete(self, table: Table) -> Delete:
        return delete(table).where(table.c.org_id == self.org_id)

    def values(self, **kw: Any) -> dict[str, Any]:
        """Insert values with org_id filled in. Passing a different org_id is an error."""
        if "org_id" in kw and kw["org_id"] != self.org_id:
            raise ValueError("cannot insert a row for another organisation")
        return {**kw, "org_id": self.org_id}
