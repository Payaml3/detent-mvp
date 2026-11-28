"""Seed the fictional demo organisation and console users from fixtures (FND-04).

Idempotent: running it twice changes nothing. Counterparties, destinations and the rule set are
seeded for slice S1 (INT-04, POL-01); rails and the mandate arrive with RAL-01 and MND-01.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Connection, text

from detent.audit.log import Actor, append
from detent.db.engine import transaction
from detent.intents.registry import seed_registry
from detent.policy.schema import load_ruleset
from detent.policy.store import install_ruleset
from detent.rails.registry import seed_rails
from detent.runtime import Runtime
from detent.settings import REPO_ROOT

FIXTURE = REPO_ROOT / "fixtures" / "counterparties.yaml"
POLICY = REPO_ROOT / "fixtures" / "policy" / "default-policy.yaml"
OPERATOR_ORG = "org_detent"  # owns website access requests (leads)


def ensure_org(conn: Connection, rt: Runtime, org_id: str, name: str, **kw: Any) -> bool:
    created = conn.execute(
        text(
            "INSERT INTO organisations (id, name, mode, fail_safe, kind, created_at) "
            "VALUES (:id, :name, :mode, :fail_safe, :kind, :now) ON CONFLICT (id) DO NOTHING RETURNING id"
        ),
        {
            "id": org_id,
            "name": name,
            "mode": kw.get("mode", "shadow"),
            "fail_safe": kw.get("fail_safe", "manual_queue"),
            "kind": kw.get("kind", "demo"),
            "now": rt.clock.now(),
        },
    ).scalar_one_or_none()
    conn.execute(
        text("INSERT INTO kill_switch (org_id, engaged) VALUES (:o, false) ON CONFLICT (org_id) DO NOTHING"),
        {"o": org_id},
    )
    conn.execute(
        text(
            "INSERT INTO demo_clock (org_id, offset_seconds) VALUES (:o, 0) ON CONFLICT (org_id) DO NOTHING"
        ),
        {"o": org_id},
    )
    return created is not None


def seed_demo(
    rt: Runtime, fixture: Path = FIXTURE, *, org_id: str | None = None, policy: str | None = None
) -> dict[str, int]:
    """Seed the fictional demo platform. ``org_id`` seeds another organisation from the same fixtures (a
    later demo generation, CON-09 reset); its user IDs carry the organisation's suffix (DEM-01). A scenario
    pack (DEM-06) passes its own fixture and rule-set text."""
    from detent.demo.generations import demo_user_id

    data = yaml.safe_load(fixture.read_text())
    plat = data["platform"]
    org_id = org_id or plat["org_id"]
    plat = {"mode": "auto", "fail_safe": "manual_queue", **plat}
    users_added = 0
    with transaction(rt.engine) as conn:
        orgs_added = int(
            ensure_org(conn, rt, org_id, plat["name"], mode=plat["mode"], fail_safe=plat["fail_safe"])
        )
        orgs_added += int(ensure_org(conn, rt, OPERATOR_ORG, "DekernAI operator (internal)", kind="demo"))
        for fixture_user in data["users"]:
            u = {**fixture_user, "id": demo_user_id(fixture_user["id"], org_id)}
            added = conn.execute(
                text(
                    "INSERT INTO users (id, org_id, email, display_name, role, created_at) "
                    "VALUES (:id, :org_id, :email, :name, :role, :now) "
                    "ON CONFLICT (id) DO NOTHING RETURNING id"
                ),
                {
                    "id": u["id"],
                    "org_id": org_id,
                    "email": f"{u['id']}@demo.invalid",
                    "name": u["name"],
                    "role": u["role"],
                    "now": rt.clock.now(),
                },
            ).scalar_one_or_none()
            users_added += int(added is not None)
        conn.execute(
            text(
                "UPDATE organisations SET registered_name = coalesce(registered_name, :n), "
                "registered_account = coalesce(registered_account, :a) WHERE org_id = :o"
            ),
            {"n": plat["name"], "a": plat.get("registered_account"), "o": org_id},
        )
        seed_registry(conn, rt.clock, org_id, fixture)
        seed_rails(conn, org_id, rt.settings)
        _seed_agent(conn, rt, org_id)
        has_policy = conn.execute(
            text("SELECT 1 FROM policy_versions WHERE org_id=:o AND status='active'"), {"o": org_id}
        ).first()
        if has_policy is None:
            install_ruleset(
                conn, rt.clock, org_id, load_ruleset(policy or POLICY.read_text()), proposed_by="system:seed"
            )
        if orgs_added or users_added:
            append(
                conn,
                rt.clock,
                org_id=org_id,
                actor=Actor.system("seed"),
                kind="seed.demo_applied",
                payload={"orgs_added": orgs_added, "users_added": users_added},
            )
    return {"orgs_added": orgs_added, "users_added": users_added}


def _seed_agent(conn: Connection, rt: Runtime, org_id: str) -> None:
    """The demo accounts-payable agent: its signed mandate and its own key (S5). Needs the mandate signing
    key and, for the key, the API pepper and AGENT_API_KEY; without them the agent is simply not set up."""
    from detent.api.auth import issue_key
    from detent.demo.generations import agent_key_for, demo_user_id
    from detent.mandates.store import fixture_mandate, issue_mandate

    s = rt.settings
    if s.mandate_signing_key_demo is None:
        return
    exists = conn.execute(
        text("SELECT 1 FROM mandates WHERE org_id=:o AND id='mnd_demo_ap_agent'"), {"o": org_id}
    ).first()
    if exists is None:
        issue_mandate(
            conn,
            rt.clock,
            org_id,
            fixture_mandate(rt.clock, org_id),
            s.mandate_signing_key_demo,
            actor=Actor.system("seed"),
        )
    agent_key = agent_key_for(s, org_id)
    if agent_key is not None and s.api_key_pepper is not None:
        from detent.api.auth import hash_key

        h = hash_key(agent_key.get_secret_value(), s.api_key_pepper.get_secret_value())
        known = conn.execute(
            text("SELECT 1 FROM api_keys WHERE org_id=:o AND hash=:h"), {"o": org_id, "h": h}
        ).first()
        if known is None:
            issue_key(
                conn,
                rt.clock,
                org_id,
                demo_user_id("usr_pl", org_id),
                ["intents:create"],
                s.api_key_pepper.get_secret_value(),
                mandate_id="mnd_demo_ap_agent",
                key=agent_key.get_secret_value(),
            )
