"""Audit events are hash-chained per organisation and verify end to end (invariant 12)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import OrgFixture
from detent.audit.log import Actor, append, verify_chain
from detent.clock import FrozenClock
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


def test_chain_appends_and_verifies(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    with engine.begin() as c:
        for i in range(5):
            append(c, clock, org_id=org.id, actor=Actor("usr_x", "reviewer"), kind="t", payload={"i": i})
    with engine.connect() as c:
        st = verify_chain(c, org.id)
    assert st.ok and st.events == 5


def test_rolled_back_change_leaves_no_audit_event(
    engine: Engine, org: OrgFixture, clock: FrozenClock
) -> None:
    with pytest.raises(RuntimeError), engine.begin() as c:
        append(c, clock, org_id=org.id, actor=Actor.system("t"), kind="t")
        raise RuntimeError("the change failed")
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM audit_events WHERE org_id=:o"), {"o": org.id}).scalar() == 0
        )


def test_tampering_is_detected(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    with engine.begin() as c:
        for i in range(3):
            append(c, clock, org_id=org.id, actor=Actor.system("t"), kind="t", payload={"i": i})
    # Simulate an attacker with superuser rights bypassing the append-only trigger.
    with engine.begin() as c:
        c.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_append_only"))
        c.execute(
            text("UPDATE audit_events SET payload='{\"i\": 99}' WHERE org_id=:o AND seq=2"), {"o": org.id}
        )
        c.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_append_only"))
    with engine.connect() as c:
        st = verify_chain(c, org.id)
    assert not st.ok and st.first_bad_seq == 2


def test_floats_rejected_in_payload(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    with pytest.raises(TypeError, match="floats"), engine.begin() as c:
        append(c, clock, org_id=org.id, actor=Actor.system("t"), kind="t", payload={"amount": 18500.0})


def test_concurrent_appends_keep_a_gapless_chain(engine: Engine, org: OrgFixture, clock: FrozenClock) -> None:
    def one(i: int) -> None:
        with engine.begin() as c:
            append(c, clock, org_id=org.id, actor=Actor.system("t"), kind="t", payload={"i": i})

    with ThreadPoolExecutor(10) as ex:
        list(ex.map(one, range(40)))
    with engine.connect() as c:
        st = verify_chain(c, org.id)
    assert st.ok and st.events == 40
