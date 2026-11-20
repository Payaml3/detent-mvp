"""Demo data generations: "reset demo data" without deleting anything (CON-09, D-08 applied to the demo).

The first generation is the seeded demo organisation (``DEMO_ORG_ID``, default ``org_demo``). A reset seeds
a fresh fictional organisation from the same fixtures (``org_demo_g2``, ``org_demo_g3``, ...) and the console
switches to it. The earlier generation keeps its audit log, ledger and payments untouched (invariant 12);
its kill switch is engaged so it can never send again. A reset is refused while any attempt in the current
generation is in flight (CREATED, SUBMITTED or UNKNOWN): the same test wallet sends for every generation, so
the resolver must finish first (invariant 3).
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import SecretStr
from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.db.engine import transaction
from detent.domain.roles import Role
from detent.settings import Settings

if TYPE_CHECKING:
    from detent.runtime import Runtime

IN_FLIGHT = ("CREATED", "SUBMITTED", "UNKNOWN")
CROSS = {"cross_org": "demo generations are looked up by their base organisation"}


class ResetRefused(Exception):
    """The demo can't be reset right now (an attempt is in flight, or the actor isn't the payments lead)."""


@dataclass(frozen=True, slots=True)
class ResetResult:
    previous_org_id: str
    org_id: str
    generation: int


def generation_org_id(base_org_id: str, generation: int) -> str:
    return base_org_id if generation == 1 else f"{base_org_id}_g{generation}"


FIXTURE_ORG_ID = "org_demo"  # the organisation ID in fixtures/counterparties.yaml


def demo_user_id(fixture_user_id: str, org_id: str) -> str:
    """User IDs are global, so every demo organisation but the fixture's own suffixes them with its ID
    (``usr_pl_demo_g2``); names and roles are the same."""
    if org_id == FIXTURE_ORG_ID:
        return fixture_user_id
    return f"{fixture_user_id}_{org_id.removeprefix('org_')}"


def current_generation(conn: Connection, base_org_id: str) -> int:
    n = conn.execute(
        text("SELECT max(generation) FROM demo_generations WHERE base_org_id=:b").execution_options(**CROSS),
        {"b": base_org_id},
    ).scalar_one_or_none()
    return int(n or 1)


def active_org(conn: Connection, base_org_id: str) -> str:
    return generation_org_id(base_org_id, current_generation(conn, base_org_id))


def active_demo_org(engine: Engine, settings: Settings) -> str:
    """The organisation the console and the demo clock use: the newest demo generation."""
    with engine.connect() as conn:
        return active_org(conn, settings.demo_org_id)


def agent_key_for(settings: Settings, org_id: str) -> SecretStr | None:
    """The instruction agent's own test key for a generation. Generation 1 uses ``AGENT_API_KEY``;
    later generations derive theirs from it (key hashes are unique, so each organisation needs its own)."""
    key = settings.agent_api_key
    if key is None or org_id == settings.demo_org_id:
        return key
    from detent.api.auth import TEST_PREFIX

    digest = hmac.new(key.get_secret_value().encode(), org_id.encode(), hashlib.sha256).hexdigest()
    return SecretStr(f"{TEST_PREFIX}demo{digest[:40]}")


def _in_flight(conn: Connection, org_id: str) -> int:
    return int(
        conn.execute(
            text("SELECT count(*) FROM attempts WHERE org_id=:o AND status = ANY(:s)"),
            {"o": org_id, "s": list(IN_FLIGHT)},
        ).scalar_one()
    )


def reset_demo(rt: Runtime, *, actor: Actor) -> ResetResult:
    """Start a new demo generation. Only the payments lead may reset (they alone can release a kill switch,
    and a reset engages the old generation's switch for good)."""
    from detent.execution.kill_switch import engage_in
    from detent.seed import seed_demo

    if actor.role != Role.PAYMENTS_LEAD.value:
        raise ResetRefused("only the payments lead can reset the demo data")
    base = rt.settings.demo_org_id
    with transaction(rt.engine) as conn:
        gen = current_generation(conn, base)
        old = generation_org_id(base, gen)
        # Lock the old generation's kill switch row first. The send path reads it FOR SHARE in the same
        # transaction that creates an attempt, so no attempt can appear between this check and the engage.
        conn.execute(text("SELECT engaged FROM kill_switch WHERE org_id=:o FOR UPDATE"), {"o": old})
        busy = _in_flight(conn, old)
        if busy:
            # Raising rolls the transaction back: a refused reset leaves the kill switch as it was.
            raise ResetRefused(
                f"{busy} attempt(s) are still in flight (CREATED, SUBMITTED or UNKNOWN); wait for the "
                "resolver, then reset"
            )
        offset = conn.execute(
            text("SELECT offset_seconds FROM demo_clock WHERE org_id=:o"), {"o": old}
        ).scalar_one_or_none()
        engage_in(conn, rt.clock, org_id=old, actor=actor)
    new_gen = gen + 1
    new_org = generation_org_id(base, new_gen)
    seed_demo(rt, org_id=new_org)
    with transaction(rt.engine) as conn:
        # The demo clock never runs backwards across a reset: the new generation starts at the old offset.
        conn.execute(
            text("UPDATE demo_clock SET offset_seconds=:s WHERE org_id=:o"),
            {"s": int(offset or 0), "o": new_org},
        )
        if gen == 1:
            _record(conn, rt, base, 1, base, "system:seed")
        _record(conn, rt, base, new_gen, new_org, actor.id)
        for org, kind in ((old, "demo.reset_away"), (new_org, "demo.reset")):
            append(
                conn,
                rt.clock,
                org_id=org,
                actor=actor,
                kind=kind,
                subject_id=new_org,
                payload={"previous_org_id": old, "org_id": new_org, "generation": new_gen},
            )
    return ResetResult(old, new_org, new_gen)


def _record(conn: Connection, rt: Runtime, base: str, gen: int, org_id: str, by: str) -> None:
    conn.execute(
        text(
            "INSERT INTO demo_generations (base_org_id, generation, org_id, created_at, created_by) "
            "VALUES (:b, :g, :o, :t, :by) ON CONFLICT DO NOTHING"
        ),
        {"b": base, "g": gen, "o": org_id, "t": rt.clock.now(), "by": by},
    )
