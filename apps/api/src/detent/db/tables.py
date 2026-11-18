"""SQLAlchemy Core definitions for the tables code uses so far.

The migration SQL (migrations/versions/*.sql) is the schema's source of truth. Tables are added here
as stories start using them; ``tests/integration/test_schema.py`` checks every column defined here
exists in the database with the same name.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData(schema="detent")


def _ts(name: str, nullable: bool = True) -> Column[object]:
    return Column(name, DateTime(timezone=True), nullable=nullable)


organisations = Table(
    "organisations",
    metadata,
    Column("id", Text, primary_key=True),
    Column("org_id", Text),  # generated: equals id
    Column("name", Text, nullable=False),
    Column("mode", Text, nullable=False),
    Column("fail_safe", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("api_version", Text, nullable=False),
    _ts("expires_at"),
    _ts("created_at", nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("id", Text, primary_key=True),
    Column("org_id", Text, nullable=False),
    Column("email", Text, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("password_hash", Text),
    _ts("created_at", nullable=False),
)

kill_switch = Table(
    "kill_switch",
    metadata,
    Column("org_id", Text, primary_key=True),
    Column("engaged", Boolean, nullable=False),
    Column("engaged_by", Text),
    _ts("engaged_at"),
    Column("released_by", Text),
    _ts("released_at"),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", Text, primary_key=True),
    Column("org_id", Text, nullable=False),
    Column("seq", BigInteger, nullable=False),
    _ts("at", nullable=False),
    Column("actor", Text, nullable=False),
    Column("actor_role", Text),
    Column("kind", Text, nullable=False),
    Column("subject_id", Text),
    Column("payload", JSONB, nullable=False),
    Column("prev_hash", Text, nullable=False),
    Column("hash", Text, nullable=False),
)

audit_heads = Table(
    "audit_heads",
    metadata,
    Column("org_id", Text, primary_key=True),
    Column("seq", BigInteger, nullable=False),
    Column("hash", Text, nullable=False),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", Text, primary_key=True),
    Column("org_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("dedupe_key", Text),
    Column("payment_id", Text),
    Column("payload", JSONB, nullable=False),
    _ts("run_at", nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("locked_by", Text),
    _ts("locked_until"),
    Column("last_error", Text),
    _ts("created_at", nullable=False),
    _ts("done_at"),
    _ts("dead_at"),
)

demo_clock = Table(
    "demo_clock",
    metadata,
    Column("org_id", Text, primary_key=True),
    Column("offset_seconds", BigInteger, nullable=False),
)

# Every table in the detent schema (from the migrations). The org-scope guard watches these.
ALL_TABLE_NAMES: frozenset[str] = frozenset(
    {
        "organisations", "users", "api_keys", "counterparties", "destinations", "mandates",
        "policy_versions", "payment_intents", "decisions", "rails", "attempts", "kill_switch",
        "counters", "mandate_usage", "exception_cases", "case_events", "deposit_intents",
        "inbound_transfers", "accounts", "journal_entries", "postings", "credits", "recon_runs",
        "recon_breaks", "agent_calls", "audit_events", "audit_heads", "outbox", "webhook_endpoints",
        "webhook_events", "webhook_deliveries", "request_logs", "idempotency_records", "jobs",
        "incidents", "invites", "leads", "demo_clock",
    }
)  # fmt: skip
