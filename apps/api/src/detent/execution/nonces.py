"""The nonce manager (EXE-04).

- ``assign`` takes the wallet's row lock and hands out the next nonce; concurrent sends from one
  wallet therefore get consecutive nonces. The caller writes it on the attempt, with the signed
  transaction, before broadcasting.
- ``reconcile`` (run when the worker starts) compares the stored next nonce with the chain's pending
  count. If they disagree it marks the wallet refused: no further sends until someone looks, because
  a gap or a reuse could mean a transaction we do not know about.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.rails.base import NonceRail, RailAdapter


class WalletRefused(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class NonceProblem:
    rail_id: str
    address: str
    stored: int
    chain: int


def assign(conn: Connection, org_id: str, rail: NonceRail) -> int:
    addr = rail.from_address.lower()
    row = conn.execute(
        text(
            "SELECT next_nonce, refused_reason FROM wallet_nonces "
            "WHERE org_id=:o AND rail_id=:r AND address=:a FOR UPDATE"
        ),
        {"o": org_id, "r": rail.rail_id, "a": addr},
    ).one_or_none()
    if row is None:
        # First use of this wallet: start from the chain. The insert takes the lock for later senders.
        n = rail.pending_nonce()
        inserted = conn.execute(
            text(
                "INSERT INTO wallet_nonces (org_id, rail_id, address, next_nonce) VALUES (:o, :r, :a, :n) "
                "ON CONFLICT (org_id, rail_id, address) DO NOTHING RETURNING next_nonce"
            ),
            {"o": org_id, "r": rail.rail_id, "a": addr, "n": n + 1},
        ).scalar_one_or_none()
        if inserted is not None:
            return n
        return assign(conn, org_id, rail)  # another sender created the row first
    if row.refused_reason:
        raise WalletRefused(row.refused_reason)
    n = int(row.next_nonce)
    conn.execute(
        text("UPDATE wallet_nonces SET next_nonce = :n WHERE org_id=:o AND rail_id=:r AND address=:a"),
        {"n": n + 1, "o": org_id, "r": rail.rail_id, "a": addr},
    )
    return n


def reconcile(
    engine: Engine, clock: Clock, org_id: str, adapters: Mapping[str, RailAdapter]
) -> list[NonceProblem]:
    problems: list[NonceProblem] = []
    for rail in adapters.values():
        if not hasattr(rail, "pending_nonce"):
            continue
        nr: NonceRail = rail  # type: ignore[assignment]
        addr = nr.from_address.lower()
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT next_nonce FROM wallet_nonces WHERE org_id=:o AND rail_id=:r AND address=:a "
                    "FOR UPDATE"
                ),
                {"o": org_id, "r": nr.rail_id, "a": addr},
            ).one_or_none()
            if row is None:
                continue  # never used: assign() starts from the chain
            chain = nr.pending_nonce()
            stored = int(row.next_nonce)
            reason = None if stored == chain else f"NONCE_MISMATCH stored={stored} chain_pending={chain}"
            conn.execute(
                text(
                    "UPDATE wallet_nonces SET refused_reason=:why, reconciled_at=:t "
                    "WHERE org_id=:o AND rail_id=:r AND address=:a"
                ),
                {"why": reason, "t": clock.now(), "o": org_id, "r": nr.rail_id, "a": addr},
            )
            if reason:
                problems.append(NonceProblem(nr.rail_id, addr, stored, chain))
                append(
                    conn,
                    clock,
                    org_id=org_id,
                    actor=Actor.system("nonce_manager"),
                    kind="wallet.refused",
                    subject_id=nr.rail_id,
                    payload={"address": addr, "stored_next_nonce": stored, "chain_pending": chain},
                )
    return problems
