"""Data generations (SBX-04, C-04, D-08): what a sandbox reset hides.

A reset raises `organisations.data_generation`. The root rows the API and dashboard list (payment and
deposit intents, exception cases, journal entries, request logs, webhook events, reconciliation runs and
breaks) are stamped with the generation when they are inserted, by a database trigger (migration 0014).
Reads for the API and dashboard keep only the current generation; nothing is deleted.

What a reset does not hide, on purpose:

- decision history: velocity counters, first-payment checks and the resubmission-after-block window read
  every generation, so a reset can't launder a block or a limit;
- idempotency keys: a key replayed after a reset returns its first response, so a retry across a reset
  never sends twice;
- quotas and the shared test-wallet caps (usage is metered per day, not per generation);
- account balances: they are what the rails moved, and a reset can't change what a wallet holds.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

GENERATED_TABLES = (
    "payment_intents",
    "deposit_intents",
    "exception_cases",
    "journal_entries",
    "request_logs",
    "webhook_events",
    "recon_runs",
    "recon_breaks",
)


# A WHERE fragment: the row belongs to the organisation's current generation (`:o` is its org_id). The
# subquery is uncorrelated, so Postgres evaluates it once per statement. Reads spell it out in full.
CURRENT = "generation = (SELECT data_generation FROM organisations WHERE org_id = :o)"


def current(conn: Connection, org_id: str) -> int:
    return int(
        conn.execute(
            text("SELECT data_generation FROM organisations WHERE org_id=:o"), {"o": org_id}
        ).scalar_one()
    )


def visible(conn: Connection, table: str, org_id: str, row_id: str) -> bool:
    """Whether the row exists for this organisation in its current generation."""
    if table not in GENERATED_TABLES:
        raise ValueError(f"{table} has no data generation")
    found = conn.execute(
        # `table` is checked against a fixed list above; values are bound parameters.
        text(f"SELECT 1 FROM {table} WHERE org_id=:o AND id=:i AND {CURRENT}"),  # noqa: S608
        {"o": org_id, "i": row_id},
    ).first()
    return found is not None
