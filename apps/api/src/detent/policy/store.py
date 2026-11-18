"""Rule-set versions in the database (POL-01).

``install_ruleset`` stores a validated rule set as the active version; it is used by the seed and
tests. Changing rules through the console with two approvers is POL-07 (slice S6). A stored version is
immutable once active (database trigger in migration 0001).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import Connection, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.domain.ids import Prefix, new_id
from detent.policy.schema import RuleSet, load_ruleset


@dataclass(frozen=True, slots=True)
class ActivePolicy:
    id: str
    version: int
    rules: RuleSet


class NoActivePolicy(RuntimeError):
    pass


def install_ruleset(conn: Connection, clock: Clock, org_id: str, rules: RuleSet, *, proposed_by: str) -> str:
    now = clock.now()
    conn.execute(
        text("UPDATE policy_versions SET status='superseded' WHERE org_id=:o AND status='active'"),
        {"o": org_id},
    )
    pol_id = new_id(Prefix.POL, now)
    conn.execute(
        text(
            "INSERT INTO policy_versions (id, org_id, version, content_hash, yaml, status, proposed_by, "
            "attestation, created_at, activated_at) VALUES (:id, :o, :v, :h, :y, 'active', :p, :att, :t, :t)"
        ),
        {
            "id": pol_id,
            "o": org_id,
            "v": rules.version,
            "h": rules.content_hash,
            "y": rules.text,
            "p": proposed_by,
            "att": rules.attestation,
            "t": now,
        },
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=Actor.system("seed") if proposed_by.startswith("system:") else Actor(proposed_by),
        kind="policy.activated",
        subject_id=pol_id,
        payload={
            "version": rules.version,
            "content_hash": rules.content_hash,
            "attestation": rules.attestation,
        },
    )
    return pol_id


@lru_cache(maxsize=64)
def _parse(content_hash: str, yaml_text: str) -> RuleSet:
    rules = load_ruleset(yaml_text)
    if rules.content_hash != content_hash:
        raise NoActivePolicy("stored rule set does not match its content hash")
    return rules


def active_policy(conn: Connection, org_id: str) -> ActivePolicy:
    row = conn.execute(
        text(
            "SELECT id, version, content_hash, yaml FROM policy_versions WHERE org_id=:o AND status='active'"
        ),
        {"o": org_id},
    ).one_or_none()
    if row is None:
        raise NoActivePolicy(f"organisation {org_id} has no active rule set")
    return ActivePolicy(row.id, row.version, _parse(row.content_hash, row.yaml))
