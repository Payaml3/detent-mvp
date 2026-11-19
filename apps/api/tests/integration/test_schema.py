"""FND-03: the database enforces the invariants, not just the code."""

from __future__ import annotations

import pytest
from conftest import OrgFixture, make_org
from detent.clock import FrozenClock
from detent.db.tables import ALL_TABLE_NAMES, metadata
from detent.domain.states import TERMINAL, Status
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.db


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'detent' AND table_name <> 'alembic_version'"
            )
        )
        return {r[0] for r in rows}


def test_table_list_matches_code(engine: Engine) -> None:
    assert _tables(engine) == ALL_TABLE_NAMES


def test_every_table_has_org_id_not_null(engine: Engine) -> None:
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT table_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'detent' AND column_name = 'org_id'"
            )
        ).all()
    with_org = {r.table_name: r.is_nullable for r in rows}
    assert set(with_org) == ALL_TABLE_NAMES
    assert all(v == "NO" for v in with_org.values()), with_org


def test_no_floating_point_columns_anywhere(engine: Engine) -> None:
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'detent' AND data_type IN ('real','double precision','numeric','money')"
            )
        ).all()
    assert rows == []


def test_core_table_definitions_match_database(engine: Engine) -> None:
    with engine.connect() as c:
        for t in metadata.sorted_tables:
            cols = {
                r[0]
                for r in c.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='detent' AND table_name=:t"
                    ),
                    {"t": t.name},
                )
            }
            assert {col.name for col in t.columns} <= cols, t.name


# ---------------------------------------------------------------------------------- helpers


def _payment(
    c, org: str, clock: FrozenClock, pid: str, status: str = "RECEIVED", key: str | None = None
) -> None:  # type: ignore[no-untyped-def]
    c.execute(
        text(
            "INSERT INTO counterparties (id, org_id, name, kyb_status, created_at) "
            "VALUES (:cpt, :org, 'Fictional Ltd', 'verified', :now) ON CONFLICT DO NOTHING"
        ),
        {"cpt": f"cpt_{org[4:]}", "org": org, "now": clock.now()},
    )
    c.execute(
        text(
            "INSERT INTO payment_intents (id, org_id, source, counterparty_id, amount_minor, currency, status, "
            "idempotency_key, request_hash, created_at, updated_at) "
            "VALUES (:id, :org, 'platform', :cpt, 100, 'GBP', :st, :key, 'h', :now, :now)"
        ),
        {"id": pid, "org": org, "cpt": f"cpt_{org[4:]}", "st": status, "key": key or pid, "now": clock.now()},
    )


def _rail(c, org: str) -> None:  # type: ignore[no-untyped-def]
    c.execute(
        text(
            "INSERT INTO rails (id, org_id, kind, network, chain_id, currency) "
            "VALUES ('local-evm', :org, 'evm', 'local-evm', 31337, 'USDC') ON CONFLICT DO NOTHING"
        ),
        {"org": org},
    )


def _attempt(c, org: str, clock: FrozenClock, aid: str, pid: str, no: int, status: str, **kw: object) -> None:  # type: ignore[no-untyped-def]
    c.execute(
        text(
            "INSERT INTO attempts (id, org_id, payment_id, attempt_no, rail_id, status, failure_class, "
            "idempotency_key, from_address, nonce, created_at, evidence) VALUES "
            "(:id, :org, :pid, :no, 'local-evm', :st, :fc, :pid, :fa, :nonce, :now, CAST(:ev AS jsonb))"
        ),
        {
            "id": aid,
            "org": org,
            "pid": pid,
            "no": no,
            "st": status,
            "fc": kw.get("failure_class"),
            "fa": kw.get("from_address"),
            "nonce": kw.get("nonce"),
            "now": clock.now(),
            "ev": kw.get("evidence"),
        },
    )


# ---------------------------------------------------------------------------------- invariant 2


def test_one_inflight_attempt_per_payment(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    pid = f"pay_{org.id[4:]}a"
    with engine.begin() as c:
        _rail(c, org.id)
        _payment(c, org.id, clock, pid)
        _attempt(c, org.id, clock, f"att_{org.id[4:]}1", pid, 1, "SUBMITTED")
    for status in ("CREATED", "SUBMITTED", "UNKNOWN"):
        with pytest.raises(IntegrityError, match="one_inflight_attempt"), engine.begin() as c:
            _attempt(c, org.id, clock, f"att_{org.id[4:]}x", pid, 2, status)


def test_retry_allowed_only_after_definitive_failure(
    engine: Engine, org: OrgFixture, clock: FrozenClock
) -> None:
    pid = f"pay_{org.id[4:]}b"
    with engine.begin() as c:
        _rail(c, org.id)
        _payment(c, org.id, clock, pid)
        _attempt(c, org.id, clock, f"att_{org.id[4:]}1", pid, 1, "FAILED", failure_class="TECHNICAL_FINAL")
        _attempt(c, org.id, clock, f"att_{org.id[4:]}2", pid, 2, "SUBMITTED")  # same payment ID


def test_one_confirmed_attempt_per_payment(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    pid = f"pay_{org.id[4:]}c"
    with engine.begin() as c:
        _rail(c, org.id)
        _payment(c, org.id, clock, pid)
        _attempt(c, org.id, clock, f"att_{org.id[4:]}1", pid, 1, "CONFIRMED")
    with pytest.raises(IntegrityError, match="one_confirmed_attempt"), engine.begin() as c:
        _attempt(c, org.id, clock, f"att_{org.id[4:]}2", pid, 2, "CONFIRMED")


def test_one_tx_per_nonce(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    p1, p2 = f"pay_{org.id[4:]}n1", f"pay_{org.id[4:]}n2"
    with engine.begin() as c:
        _rail(c, org.id)
        _payment(c, org.id, clock, p1)
        _payment(c, org.id, clock, p2)
        _attempt(c, org.id, clock, f"att_{org.id[4:]}1", p1, 1, "SUBMITTED", from_address="0xabc", nonce=7)
    with pytest.raises(IntegrityError, match="one_tx_per_nonce"), engine.begin() as c:
        _attempt(c, org.id, clock, f"att_{org.id[4:]}2", p2, 1, "SUBMITTED", from_address="0xabc", nonce=7)


def test_idempotency_key_unique_per_org_not_global(engine: Engine, clock: FrozenClock) -> None:
    a, b = make_org(engine, clock), make_org(engine, clock)
    with engine.begin() as c:
        _payment(c, a.id, clock, f"pay_{a.id[4:]}1", key="same-key")
        _payment(c, b.id, clock, f"pay_{b.id[4:]}1", key="same-key")  # other org: fine
    with pytest.raises(IntegrityError, match="idem_payment"), engine.begin() as c:
        _payment(c, a.id, clock, f"pay_{a.id[4:]}2", key="same-key")


# ---------------------------------------------------------------------------------- invariants 3, 4


@pytest.mark.parametrize("terminal", sorted(TERMINAL))
def test_terminal_payment_status_is_frozen(
    engine: Engine, org: OrgFixture, clock: FrozenClock, terminal: Status
) -> None:
    pid = f"pay_{org.id[4:]}{terminal.value.lower()}"
    with engine.begin() as c:
        _payment(c, org.id, clock, pid, status=terminal.value)
    for target in ("READY", "SUBMITTED", "ESCALATED"):
        with pytest.raises(DBAPIError, match="is terminal"), engine.begin() as c:
            c.execute(
                text("UPDATE payment_intents SET status = :s WHERE org_id = :o AND id = :id"),
                {"s": target, "o": org.id, "id": pid},
            )


def test_trigger_terminal_list_matches_code(engine: Engine) -> None:
    with engine.connect() as c:
        src = c.execute(
            text("SELECT prosrc FROM pg_proc WHERE proname = 'forbid_terminal_status_change'")
        ).scalar_one()
    listed = set(src.split("IN (", 1)[1].split(")", 1)[0].replace("'", "").replace(" ", "").split(","))
    assert listed == {s.value for s in TERMINAL}


def test_non_terminal_status_can_change(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    pid = f"pay_{org.id[4:]}ok"
    with engine.begin() as c:
        _payment(c, org.id, clock, pid, status="ESCALATED")
        c.execute(
            text("UPDATE payment_intents SET status='READY' WHERE org_id=:o AND id=:id"),
            {"o": org.id, "id": pid},
        )


def test_unknown_attempt_needs_evidence_to_fail(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    pid, aid = f"pay_{org.id[4:]}u", f"att_{org.id[4:]}u"
    with engine.begin() as c:
        _rail(c, org.id)
        _payment(c, org.id, clock, pid)
        _attempt(c, org.id, clock, aid, pid, 1, "UNKNOWN", failure_class="TIMEOUT")
    sql = text(
        "UPDATE attempts SET status='FAILED', failure_class='TECHNICAL_FINAL' WHERE org_id=:o AND id=:id"
    )
    with pytest.raises(DBAPIError, match="without evidence"), engine.begin() as c:
        c.execute(sql, {"o": org.id, "id": aid})
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE attempts SET status='FAILED', failure_class='TECHNICAL_FINAL', "
                "evidence='{\"receipt_status\": 0}' WHERE org_id=:o AND id=:id"
            ),
            {"o": org.id, "id": aid},
        )


def test_timeout_never_stored_as_failed(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    pid = f"pay_{org.id[4:]}t"
    with engine.begin() as c:
        _rail(c, org.id)
        _payment(c, org.id, clock, pid)
    with pytest.raises(IntegrityError), engine.begin() as c:
        _attempt(
            c, org.id, clock, f"att_{org.id[4:]}t", pid, 1, "FAILED", failure_class="TIMEOUT", evidence="{}"
        )


def test_confirmed_attempt_is_final(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    pid, aid = f"pay_{org.id[4:]}f", f"att_{org.id[4:]}f"
    with engine.begin() as c:
        _rail(c, org.id)
        _payment(c, org.id, clock, pid)
        _attempt(c, org.id, clock, aid, pid, 1, "CONFIRMED")
    with pytest.raises(DBAPIError, match="is final"), engine.begin() as c:
        c.execute(
            text(
                "UPDATE attempts SET status='FAILED', failure_class='TECHNICAL_FINAL', evidence='{}' "
                "WHERE org_id=:o AND id=:id"
            ),
            {"o": org.id, "id": aid},
        )


# ---------------------------------------------------------------------------------- invariant 12, ledger


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE audit_events SET kind='x' WHERE org_id=:o",
        "DELETE FROM audit_events WHERE org_id=:o",
    ],
)
def test_audit_is_append_only(engine: Engine, org: OrgFixture, clock: FrozenClock, stmt: str) -> None:
    from detent.audit.log import Actor, append

    with engine.begin() as c:
        append(c, clock, org_id=org.id, actor=Actor.system("test"), kind="test.event")
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as c:
        c.execute(text(stmt), {"o": org.id})


@pytest.mark.parametrize("table", ["audit_events", "journal_entries", "postings"])
def test_append_only_tables_cannot_be_truncated(engine: Engine, table: str) -> None:
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as c:
        c.execute(text(f"TRUNCATE {table} CASCADE"))


def test_ledger_rows_cannot_be_edited(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    j = f"jrn_{org.id[4:]}"
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO journal_entries (id, org_id, kind, payment_id, created_at) "
                "VALUES (:j, :o, 'test', 'pay_test', :n)"
            ),
            {"j": j, "o": org.id, "n": clock.now()},
        )
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as c:
        c.execute(
            text("UPDATE journal_entries SET memo='edited' WHERE org_id=:o AND id=:j"), {"o": org.id, "j": j}
        )


# ---------------------------------------------------------------------------------- invariants 14, 16


def test_cross_org_reference_rejected(engine: Engine, clock: FrozenClock) -> None:
    a, b = make_org(engine, clock), make_org(engine, clock)
    pid = f"pay_{a.id[4:]}x"
    with engine.begin() as c:
        _payment(c, a.id, clock, pid)
        _rail(c, b.id)
    # An attempt in org B pointing at org A's payment violates the composite foreign key.
    with pytest.raises(IntegrityError, match="foreign key"), engine.begin() as c:
        _attempt(c, b.id, clock, f"att_{b.id[4:]}x", pid, 1, "CREATED")


def test_mainnet_rail_cannot_be_stored(engine: Engine, org: OrgFixture) -> None:
    with pytest.raises(IntegrityError, match="chain_id"), engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO rails (id, org_id, kind, network, chain_id, currency) "
                "VALUES ('base', :o, 'evm', 'base', 8453, 'USDC')"
            ),
            {"o": org.id},
        )


def test_live_api_key_cannot_be_stored(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    with pytest.raises(IntegrityError, match="prefix"), engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO api_keys (id, org_id, prefix, hash, scopes, created_at) "
                "VALUES ('key_x', :o, 'sk_live_abc', 'h', '{read}', :n)"
            ),
            {"o": org.id, "n": clock.now()},
        )


def test_money_columns_reject_non_positive_amounts(
    engine: Engine, org: OrgFixture, clock: FrozenClock
) -> None:
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO counterparties (id, org_id, name, kyb_status, created_at) "
                "VALUES ('cpt_neg', :o, 'x', 'verified', :n)"
            ),
            {"o": org.id, "n": clock.now()},
        )
        c.execute(
            text(
                "INSERT INTO payment_intents (id, org_id, source, counterparty_id, amount_minor, currency, "
                "status, idempotency_key, request_hash, created_at, updated_at) VALUES ('pay_neg', :o, "
                "'platform', 'cpt_neg', -5, 'GBP', 'RECEIVED', 'k', 'h', :n, :n)"
            ),
            {"o": org.id, "n": clock.now()},
        )


def test_engine_guard_blocks_unscoped_query(engine: Engine) -> None:
    from detent.db.engine import OrgScopeViolation

    with pytest.raises(OrgScopeViolation), engine.connect() as c:
        c.execute(text("SELECT id FROM payment_intents"))
