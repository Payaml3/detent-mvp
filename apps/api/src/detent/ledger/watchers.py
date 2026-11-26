"""Deposit watchers (LED-04).

- Chain rails: token Transfer logs into the organisation's deposit addresses ("in") and out of its
  sending wallet ("out"). Each is stored once: ``inbound_transfers`` is unique on (rail, transaction
  hash, log index) and ``rail_records`` on (organisation, rail, external ID), so a restart or a rescan
  never duplicates. Blocks not yet past the confirmation threshold are scanned again next time, which
  updates their confirmation count.
- The simulated bank rail: inbound credits after the stored cursor.

Watching only records what the rail says. Deciding and crediting is ``credit.process_inbound``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.clock import Clock
from detent.domain.ids import Prefix, new_id
from detent.rails.base import ObservedTransfer

SCAN_BACK_BLOCKS = 5000  # first scan of a chain rail starts this far behind the head


def _cursor(conn: Connection, org_id: str, rail_id: str) -> str | None:
    return conn.execute(
        text("SELECT position FROM watch_cursors WHERE org_id=:o AND rail_id=:r"), {"o": org_id, "r": rail_id}
    ).scalar_one_or_none()


def _set_cursor(conn: Connection, clock: Clock, org_id: str, rail_id: str, position: str) -> None:
    conn.execute(
        text(
            "INSERT INTO watch_cursors (org_id, rail_id, position, updated_at) VALUES (:o, :r, :p, :t) "
            "ON CONFLICT (org_id, rail_id) DO UPDATE SET position = EXCLUDED.position, updated_at = "
            "EXCLUDED.updated_at"
        ),
        {"o": org_id, "r": rail_id, "p": position, "t": clock.now()},
    )


def record_inbound(conn: Connection, clock: Clock, org_id: str, rail: Any, t: ObservedTransfer) -> bool:
    """Store an inbound transfer once. Returns True if it was new."""
    row = conn.execute(
        text(
            "INSERT INTO inbound_transfers (id, org_id, rail_id, tx_hash, log_index, from_address, "
            "to_address, "
            "amount_minor, token, confirmations, seen_at, currency, network, block_number) VALUES "
            "(:id, :o, :r, :h, "
            ":li, :f, :to, :a, :tok, :c, :t, :cur, :n, :b) ON CONFLICT (rail_id, tx_hash, log_index) "
            "DO UPDATE SET "
            "confirmations = GREATEST(inbound_transfers.confirmations, EXCLUDED.confirmations) "
            "WHERE inbound_transfers.org_id = EXCLUDED.org_id RETURNING (xmax = 0) AS inserted"
        ),
        {
            "id": new_id(Prefix.INB, clock.now()),
            "o": org_id,
            "r": rail.id,
            "h": t.tx_hash,
            "li": t.log_index,
            "f": t.from_party,
            "to": t.to_party,
            "a": t.amount_minor,
            "tok": rail.currency,
            "c": t.confirmations,
            "t": clock.now(),
            "cur": rail.currency,
            "n": rail.network,
            "b": t.block_number,
        },
    ).scalar_one_or_none()
    return bool(row)


def record_rail_record(
    conn: Connection, clock: Clock, org_id: str, rail_id: str, currency: str, t: ObservedTransfer, source: str
) -> None:
    conn.execute(
        text(
            "INSERT INTO rail_records (id, org_id, rail_id, external_id, direction, amount_minor, "
            "currency, party, "
            "source, occurred_at) VALUES (:id, :o, :r, :e, :d, :a, :c, :p, :s, :t) "
            "ON CONFLICT (org_id, rail_id, external_id) DO NOTHING"
        ),
        {
            "id": f"rr_{rail_id}_{t.external_id}"[:200],
            "o": org_id,
            "r": rail_id,
            "e": t.external_id,
            "d": t.direction,
            "a": t.amount_minor,
            "c": currency,
            "p": t.to_party if t.direction == "out" else t.from_party,
            "s": source,
            "t": clock.now(),
        },
    )


def _rail(conn: Connection, org_id: str, rail_id: str) -> Any:
    return conn.execute(
        text(
            "SELECT id, kind, network, currency, confirmations, from_address FROM rails WHERE "
            "org_id=:o AND id=:r"
        ),
        {"o": org_id, "r": rail_id},
    ).one()


def watch_evm(engine: Engine, clock: Clock, org_id: str, rail_id: str, adapter: Any) -> int:
    """Scan new blocks. Returns how many new inbound transfers were stored."""
    with engine.connect() as conn:
        rail = _rail(conn, org_id, rail_id)
        addrs = [
            str(a)
            for a in conn.execute(
                text(
                    "SELECT DISTINCT deposit_address FROM deposit_intents WHERE org_id=:o AND network=:n "
                    "AND deposit_address IS NOT NULL"
                ),
                {"o": org_id, "n": rail.network},
            ).scalars()
        ]
        cur = _cursor(conn, org_id, rail_id)
    head = adapter.head_block()
    start = int(cur) if cur is not None else max(0, head - SCAN_BACK_BLOCKS)
    if start > head:
        return 0
    seen = adapter.transfers(
        start, head, to_addresses=addrs, from_addresses=[rail.from_address] if rail.from_address else []
    )
    new = 0
    with engine.begin() as conn:
        for t in seen:
            record_rail_record(conn, clock, org_id, rail_id, rail.currency, t, "chain")
            if t.direction == "in":
                new += int(record_inbound(conn, clock, org_id, rail, t))
        # Rescan the blocks that are not final yet, so their confirmation counts update.
        _set_cursor(conn, clock, org_id, rail_id, str(max(start, head - int(rail.confirmations) + 1)))
    return new


def watch_bank(engine: Engine, clock: Clock, org_id: str, rail_id: str, adapter: Any) -> int:
    with engine.connect() as conn:
        rail = _rail(conn, org_id, rail_id)
        cur = int(_cursor(conn, org_id, rail_id) or 0)
    seen, nxt = adapter.inbound(cur)
    new = 0
    with engine.begin() as conn:
        for t in seen:
            new += int(record_inbound(conn, clock, org_id, rail, t))
        _set_cursor(conn, clock, org_id, rail_id, str(nxt))
    return new


def watch_all(engine: Engine, clock: Clock, settings: Any) -> dict[str, int]:
    """Worker tick: every organisation with deposit intents is watched on each connected rail, then its
    new inbound transfers are decided. One rail's failure never stops the others."""
    import logging

    from detent.ledger.credit import process_pending
    from detent.policy.screening import MockScreening
    from detent.rails.registry import build_adapters

    log = logging.getLogger("detent.deposits")
    with engine.connect() as conn:
        orgs = [
            str(o)
            for o in conn.execute(
                text("SELECT DISTINCT org_id FROM deposit_intents").execution_options(
                    cross_org="deposit watcher: finds organisations that expect deposits"
                )
            ).scalars()
        ]
    out: dict[str, int] = {}
    for org in orgs:
        new = 0
        for rail_id, adapter in build_adapters(settings, engine, org, clock=clock).items():
            try:
                if hasattr(adapter, "transfers"):
                    new += watch_evm(engine, clock, org, rail_id, adapter)
                elif hasattr(adapter, "inbound"):
                    new += watch_bank(engine, clock, org, rail_id, adapter)
            except Exception:
                log.exception("deposit watcher failed", extra={"org_id": org, "rail": rail_id})
        process_pending(engine, clock, org_id=org, screening=MockScreening.from_fixture())
        out[org] = new
    return out
