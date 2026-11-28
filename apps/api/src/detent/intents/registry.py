"""Counterparty registry with destination history (INT-04).

Each destination keeps ``first_seen_at`` and ``last_changed_at``: the policy's NEW_WALLET and
CHANGED_DETAILS checks read them as facts. Editing a destination writes an audit event with the old
and new values in the same transaction.

Payment count and median come from confirmed payments (``refresh_stats``, called when a payment is
confirmed from slice S2 on). The seed loads the fixture's imported history into the same columns.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Connection, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.domain.money import Currency, Money
from detent.settings import REPO_ROOT

FIXTURE = REPO_ROOT / "fixtures" / "counterparties.yaml"


def placeholder_wallet(name: str) -> str:
    """A stable, fictional address for a fixture placeholder until slice S2 seeds real test wallets."""
    return "0x" + hashlib.sha256(f"detent-fixture:{name}".encode()).hexdigest()[:40]


def _fill(value: Any, wallets: dict[str, str]) -> Any:
    if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
        name = value[2:-2]
        wallets.setdefault(name, placeholder_wallet(name))
        return wallets[name]
    return value


def seed_registry(conn: Connection, clock: Clock, org_id: str, fixture: Path = FIXTURE) -> dict[str, str]:
    """Load the fictional counterparties and destinations. Idempotent per organisation."""
    data = yaml.safe_load(fixture.read_text())
    now = clock.now()
    wallets: dict[str, str] = {}
    added = 0
    for cp in data["counterparties"]:
        hist = cp.get("history") or {}
        median = hist.get("median_amount")
        m = Money.parse(median["amount"], median["currency"]) if median else None
        res = conn.execute(
            text(
                "INSERT INTO counterparties (id, org_id, name, kyb_status, allowlisted, jurisdiction, "
                "payment_count, "
                "median_amount_minor, median_currency, contact_email, created_at) VALUES (:id, :o, "
                ":n, :k, :a, "
                ":j, :c, :mm, :mc, :ce, :t) "
                "ON CONFLICT (org_id, id) DO NOTHING RETURNING id"
            ),
            {
                "id": cp["id"],
                "o": org_id,
                "n": cp["name"],
                "k": cp["kyb_status"],
                "a": cp["allowlisted"],
                "j": cp.get("jurisdiction"),
                "c": hist.get("payment_count", 0),
                "mm": m.amount_minor if m else None,
                "mc": m.currency.value if m else None,
                "ce": cp.get("contact_email"),
                "t": now,
            },
        ).scalar_one_or_none()
        added += int(res is not None)
        for d in cp.get("destinations") or []:
            masked = d.get("iban_masked") or d.get("sort_code_masked")
            conn.execute(
                text(
                    "INSERT INTO destinations (id, org_id, counterparty_id, kind, network, address, "
                    "iban_masked, "
                    "account_masked, verified, first_seen_at, last_changed_at) VALUES (:id, :o, :c, :k, "
                    ":n, :a, :i, "
                    ":m, true, :fs, :lc) ON CONFLICT (org_id, id) DO NOTHING"
                ),
                {
                    "id": d["id"],
                    "o": org_id,
                    "c": cp["id"],
                    "k": d["kind"],
                    "n": d["network"],
                    "a": _fill(d.get("address"), wallets),
                    "i": d.get("iban_masked"),
                    "m": masked,
                    "fs": now - timedelta(days=d["first_seen_days_ago"]),
                    "lc": now - timedelta(days=d["last_changed_days_ago"]),
                },
            )
    users_added = _seed_users(conn, now, org_id, data.get("user_accounts") or [], wallets)
    if added or users_added:
        append(
            conn,
            clock,
            org_id=org_id,
            actor=Actor.system("seed"),
            kind="registry.seeded",
            payload={"counterparties_added": added, "user_accounts_added": users_added},
        )
    return wallets


def _seed_users(
    conn: Connection, now: Any, org_id: str, users: list[dict[str, Any]], wallets: dict[str, str]
) -> int:
    """The fictional end users and their one destination each (slice U test values). Idempotent."""
    added = 0
    for u in users:
        d = u.get("destination")
        if d is None or "user_verified" not in u:
            continue
        res = conn.execute(
            text(
                "INSERT INTO user_accounts (org_id, ref, holder_name, user_verified, verified_set_by, "
                "verified_set_at, created_at) VALUES (:o, :r, :n, :v, 'system:seed', :t, :t) "
                "ON CONFLICT (org_id, ref) DO NOTHING RETURNING ref"
            ),
            {"o": org_id, "r": u["account_ref"], "n": u.get("name"), "v": bool(u["user_verified"]), "t": now},
        ).scalar_one_or_none()
        if res is None:
            continue
        added += 1
        conn.execute(
            text(
                "INSERT INTO destinations (id, org_id, user_account_ref, kind, network, address, "
                "account_masked, verified, first_seen_at, last_changed_at, last_changed_by) VALUES (:id, :o, "
                ":r, :k, :n, :a, :m, true, :fs, :lc, 'system:seed') ON CONFLICT (org_id, id) DO NOTHING"
            ),
            {
                "id": d["id"],
                "o": org_id,
                "r": u["account_ref"],
                "k": d["kind"],
                "n": d["network"],
                "a": _fill(d.get("address"), wallets),
                "m": d.get("account_masked"),
                "fs": now - timedelta(days=d["first_seen_days_ago"]),
                "lc": now - timedelta(days=d["last_changed_days_ago"]),
            },
        )
    return added


def update_destination(
    conn: Connection,
    clock: Clock,
    org_id: str,
    destination_id: str,
    *,
    actor: Actor,
    address: str | None = None,
    account_masked: str | None = None,
) -> None:
    old = conn.execute(
        text(
            "SELECT counterparty_id, kind, address, account_masked FROM destinations "
            "WHERE org_id=:o AND id=:d FOR UPDATE"
        ),
        {"o": org_id, "d": destination_id},
    ).one_or_none()
    if old is None:
        raise LookupError(destination_id)
    new_address = address if old.kind == "evm_wallet" and address else old.address
    new_masked = account_masked if old.kind == "bank_account" and account_masked else old.account_masked
    now = clock.now()
    conn.execute(
        text(
            "UPDATE destinations SET address=:a, account_masked=:m, last_changed_at=:t, last_changed_by=:by "
            "WHERE org_id=:o AND id=:d"
        ),
        {"a": new_address, "m": new_masked, "t": now, "by": actor.id, "o": org_id, "d": destination_id},
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=actor,
        kind="destination.changed",
        subject_id=destination_id,
        payload={
            "counterparty_id": old.counterparty_id,
            "old": {"address": old.address, "account_masked": old.account_masked},
            "new": {"address": new_address, "account_masked": new_masked},
        },
    )


@dataclass(frozen=True, slots=True)
class Stats:
    payment_count: int
    median: Money | None


def _median(values: list[int]) -> int:
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) // 2


def refresh_stats(conn: Connection, org_id: str, counterparty_id: str) -> None:
    rows = conn.execute(
        text(
            "SELECT amount_minor, currency FROM payment_intents "
            "WHERE org_id=:o AND counterparty_id=:c AND status='CONFIRMED'"
        ),
        {"o": org_id, "c": counterparty_id},
    ).all()
    if not rows:
        return  # keep imported history until DekernAI has confirmed payments of its own
    # The median is per currency (G-13); store the currency with the most confirmed payments.
    cur = Counter(r.currency for r in rows).most_common(1)[0][0]
    median = _median([r.amount_minor for r in rows if r.currency == cur])
    conn.execute(
        text(
            "UPDATE counterparties SET payment_count=:n, median_amount_minor=:m, median_currency=:c "
            "WHERE org_id=:o AND id=:id"
        ),
        {"n": len(rows), "m": median, "c": cur, "o": org_id, "id": counterparty_id},
    )


def counterparty_stats(conn: Connection, org_id: str, counterparty_id: str) -> Stats:
    r = conn.execute(
        text(
            "SELECT payment_count, median_amount_minor, median_currency FROM counterparties WHERE "
            "org_id=:o AND id=:c"
        ),
        {"o": org_id, "c": counterparty_id},
    ).one()
    median = (
        Money(int(r.median_amount_minor), Currency(r.median_currency))
        if r.median_amount_minor is not None
        else None
    )
    return Stats(int(r.payment_count), median)
