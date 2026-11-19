"""Rule changes with two approvers (POL-07, spec/04 "Rule changes").

1. The payments lead or the compliance lead proposes a draft: a complete rule set whose version is
   the next number. The active version does not change.
2. ``diff`` lists every changed setting; ``loosening_reasons`` marks the change as loosening if it
   does anything on either list (C-08, the union of spec/04 and POL-07): raises a limit, cap or
   threshold; removes or disables a check; shrinks ``block_on`` or ``escalate_on``; raises the
   travel-rule threshold or drops a required field; widens the allowed networks; shortens a
   look-back window or lengthens the decision age; or changes the screening list.
3. A second, different person approves. The compliance lead is one of the two on every activation
   (C-06), and records the attestation: the client approves these rules and keeps AML accountability.
4. On activation the previous version becomes ``superseded``. Nothing is deleted: a draft nobody
   approves is ``withdrawn``. Decisions keep the version they were made under (``decisions``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.domain.money import Money
from detent.domain.roles import Role, allowed
from detent.policy.schema import MoneyMap, RuleSet, RuleSetError, load_ruleset
from detent.policy.store import active_policy

DEFAULT_ATTESTATION = (
    "The client approves these rules and keeps its AML accountability. Detent applies them as written."
)


class ChangeError(Exception):
    status = 409
    code = "policy_change_refused"

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code


class AttestationRequired(ChangeError):
    status, code = 422, "attestation_required"


@dataclass(frozen=True, slots=True)
class Draft:
    id: str
    version: int
    loosening: bool
    reasons: list[dict[str, str]]
    diff: list[dict[str, Any]]


# ----------------------------------------------------------------------------------------------- diff
def _flatten(value: Any, path: str, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        if set(value) == {"amounts"}:  # MoneyMap: show amounts by currency
            value = value["amounts"]
        for k, v in value.items():
            _flatten(v, f"{path}.{k}" if path else str(k), out)
    else:
        out[path] = value


def _settings(rules: RuleSet) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _flatten(rules.model_dump(mode="json", exclude={"content_hash", "text"}), "", out)
    return out


def diff(old: RuleSet, new: RuleSet) -> list[dict[str, Any]]:
    """Every setting whose value differs, as {path, old, new}; a missing side is None."""
    a, b = _settings(old), _settings(new)
    return [
        {"path": p, "old": a.get(p), "new": b.get(p)} for p in sorted(set(a) | set(b)) if a.get(p) != b.get(p)
    ]


# ---------------------------------------------------------------------------------------- loosening
def _r(code: str, path: str, detail: str) -> dict[str, str]:
    return {"code": code, "path": path, "detail": detail}


def _raised(old: MoneyMap | None, new: MoneyMap | None, path: str, code: str) -> list[dict[str, str]]:
    if old is None:
        return []  # adding a limit where there was none is tightening
    if new is None:
        return [_r(code, path, "removed")]
    out = []
    for cur, raw in old.amounts.items():
        if cur not in new.amounts:
            out.append(_r(code, f"{path}.{cur}", f"removed (was {raw})"))
        elif Money.parse(new.amounts[cur], cur) > Money.parse(raw, cur):
            out.append(_r(code, f"{path}.{cur}", f"{raw} -> {new.amounts[cur]}"))
    return out


def _shrunk(old: list[Any], new: list[Any], path: str) -> list[dict[str, str]]:
    gone = sorted(str(x) for x in set(old) - set(new))
    return [_r("LIST_SHRUNK", path, f"no longer listed: {', '.join(gone)}")] if gone else []


def _check_changes(o: Any, n: Any) -> list[dict[str, str]]:  # noqa: PLR0912 - one rule per line
    out: list[dict[str, str]] = []
    for name in (
        "kyb_status",
        "allowlist",
        "screening",
        "travel_rule",
        "daily_caps",
        "unusual",
        "resubmission_after_block",
    ):
        if getattr(o, name) is not None and getattr(n, name) is None:
            out.append(_r("CHECK_REMOVED", f"checks.{name}", "check removed"))
    if o.mandate_scope.enabled and not n.mandate_scope.enabled:
        out.append(_r("CHECK_DISABLED", "checks.mandate_scope.enabled", "true -> false"))
    if (
        o.allowlist
        and n.allowlist
        and o.allowlist.escalate_if_not_listed
        and not n.allowlist.escalate_if_not_listed
    ):
        out.append(_r("CHECK_DISABLED", "checks.allowlist.escalate_if_not_listed", "true -> false"))
    if o.screening and n.screening:
        if o.screening.block_on_hit and not n.screening.block_on_hit:
            out.append(_r("CHECK_DISABLED", "checks.screening.block_on_hit", "true -> false"))
        if (o.screening.provider, o.screening.list) != (n.screening.provider, n.screening.list):
            out.append(
                _r(
                    "SCREENING_SCOPE_CHANGED",
                    "checks.screening.list",
                    f"{o.screening.list} -> {n.screening.list} (the new scope may be shorter)",
                )
            )
    if o.kyb_status and n.kyb_status:
        out += _shrunk(o.kyb_status.block_on, n.kyb_status.block_on, "checks.kyb_status.block_on")
        out += _shrunk(o.kyb_status.escalate_on, n.kyb_status.escalate_on, "checks.kyb_status.escalate_on")
    if o.travel_rule and n.travel_rule:
        out += _raised(
            o.travel_rule.threshold,
            n.travel_rule.threshold,
            "checks.travel_rule.threshold",
            "TRAVEL_RULE_LOOSENED",
        )
        dropped = sorted(set(o.travel_rule.required) - set(n.travel_rule.required))
        if dropped:
            out.append(
                _r("TRAVEL_RULE_LOOSENED", "checks.travel_rule.required", f"dropped: {', '.join(dropped)}")
            )
    for cur, nets in n.allowed_networks.items():
        added = sorted(set(nets) - set(o.allowed_networks.get(cur, [])))
        if added:
            out.append(_r("NETWORKS_WIDENED", f"checks.allowed_networks.{cur}", f"added: {', '.join(added)}"))
    out += _raised(o.limits.auto_limit, n.limits.auto_limit, "checks.limits.auto_limit", "LIMIT_RAISED")
    out += _raised(o.limits.hard_max, n.limits.hard_max, "checks.limits.hard_max", "LIMIT_RAISED")
    if o.daily_caps and n.daily_caps:
        out += _raised(
            o.daily_caps.platform, n.daily_caps.platform, "checks.daily_caps.platform", "LIMIT_RAISED"
        )
        out += _raised(
            o.daily_caps.per_counterparty,
            n.daily_caps.per_counterparty,
            "checks.daily_caps.per_counterparty",
            "LIMIT_RAISED",
        )
    if o.unusual and n.unusual:
        u, v = o.unusual, n.unusual
        for f in ("new_wallet_days", "changed_details_days"):
            if getattr(v, f) < getattr(u, f):  # a shorter look-back lets a destination pass sooner
                out.append(_r("WINDOW_CHANGED", f"checks.unusual.{f}", f"{getattr(u, f)} -> {getattr(v, f)}"))
        if u.first_payment == "escalate" and v.first_payment == "off":
            out.append(_r("CHECK_DISABLED", "checks.unusual.first_payment", "escalate -> off"))
        if v.above_norm_multiplier > u.above_norm_multiplier:
            out.append(
                _r(
                    "THRESHOLD_RAISED",
                    "checks.unusual.above_norm_multiplier",
                    f"{u.above_norm_multiplier} -> {v.above_norm_multiplier}",
                )
            )
        if v.above_norm_min_history > u.above_norm_min_history:
            out.append(
                _r(
                    "THRESHOLD_RAISED",
                    "checks.unusual.above_norm_min_history",
                    f"{u.above_norm_min_history} -> {v.above_norm_min_history}",
                )
            )
    if o.resubmission_after_block and n.resubmission_after_block:
        a, b = o.resubmission_after_block.window_hours, n.resubmission_after_block.window_hours
        if b < a:
            out.append(_r("WINDOW_CHANGED", "checks.resubmission_after_block.window_hours", f"{a} -> {b}"))
    return out


def loosening_reasons(old: RuleSet, new: RuleSet) -> list[dict[str, str]]:
    out = _check_changes(old.checks, new.checks)
    if old.execution and new.execution:
        a, b = old.execution.max_decision_age_seconds, new.execution.max_decision_age_seconds
        if b > a:  # an older decision is trusted at send time
            out.append(_r("WINDOW_CHANGED", "execution.max_decision_age_seconds", f"{a} -> {b}"))
    elif old.execution and not new.execution:
        out.append(_r("CHECK_REMOVED", "execution", "pre-send settings removed"))
    return out


# --------------------------------------------------------------------------------------------- flow
def _role(actor: Actor, action: str) -> Role:
    try:
        role = Role(actor.role or "")
    except ValueError:
        raise ChangeError(f"{actor.id} has no console role", status=403, code="insufficient_role") from None
    if not allowed(action, role):
        raise ChangeError(
            f"{role.value} may not {action.replace('.', ' ')}", status=403, code="insufficient_role"
        )
    return role


def _parse(yaml_text: str) -> RuleSet:
    try:
        return load_ruleset(yaml_text)
    except RuleSetError as exc:
        raise ChangeError(str(exc), status=422, code="invalid_rule_set") from exc


def _user_role(conn: Connection, org_id: str, user_id: str) -> Role | None:
    r = conn.execute(
        text("SELECT role FROM users WHERE org_id=:o AND id=:u"), {"o": org_id, "u": user_id}
    ).scalar_one_or_none()
    return Role(r) if r else None


def propose_draft(
    engine: Engine, clock: Clock, *, org_id: str, actor: Actor, yaml_text: str, attest: bool = False
) -> Draft:
    role = _role(actor, "policy.propose")
    rules = _parse(yaml_text)
    if role is Role.COMPLIANCE_LEAD and not attest:
        raise AttestationRequired("the compliance lead attests to the rules when proposing them")
    with transaction(engine) as conn:
        conn.execute(text("SELECT id FROM organisations WHERE org_id=:o FOR UPDATE"), {"o": org_id})
        open_draft = conn.execute(
            text("SELECT version FROM policy_versions WHERE org_id=:o AND status='draft'"), {"o": org_id}
        ).scalar_one_or_none()
        if open_draft is not None:
            raise ChangeError(
                f"there is already a draft (version {open_draft}) under review; approve or withdraw it"
            )
        latest = int(
            conn.execute(
                text("SELECT coalesce(max(version), 0) FROM policy_versions WHERE org_id=:o"), {"o": org_id}
            ).scalar_one()
        )
        if rules.version != latest + 1:
            raise ChangeError(f"the draft must be version {latest + 1}", status=422, code="invalid_rule_set")
        active = active_policy(conn, org_id)
        reasons = loosening_reasons(active.rules, rules)
        changes = diff(active.rules, rules)
        now = clock.now()
        pol_id = new_id(Prefix.POL, now)
        conn.execute(
            text(
                "INSERT INTO policy_versions (id, org_id, version, content_hash, yaml, status, proposed_by, "
                "loosening, loosening_reasons, attestation, attested_by, base_version, created_at) VALUES "
                "(:id, :o, :v, :h, :y, 'draft', :p, :l, CAST(:lr AS jsonb), :att, :ab, :base, :t)"
            ),
            {
                "id": pol_id,
                "o": org_id,
                "v": rules.version,
                "h": rules.content_hash,
                "y": rules.text,
                "p": actor.id,
                "l": bool(reasons),
                "lr": json.dumps(reasons),
                "att": rules.attestation or DEFAULT_ATTESTATION,
                "ab": actor.id if role is Role.COMPLIANCE_LEAD else None,
                "base": active.version,
                "t": now,
            },
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="policy.proposed",
            subject_id=pol_id,
            payload={
                "version": rules.version,
                "base_version": active.version,
                "content_hash": rules.content_hash,
                "loosening": bool(reasons),
                "loosening_reasons": reasons,
                "changes": len(changes),
            },
        )
    return Draft(pol_id, rules.version, bool(reasons), reasons, changes)


def _lock_draft(conn: Connection, org_id: str, draft_id: str) -> Any:
    d = conn.execute(
        text("SELECT * FROM policy_versions WHERE org_id=:o AND id=:i FOR UPDATE"),
        {"o": org_id, "i": draft_id},
    ).one_or_none()
    if d is None:
        raise ChangeError(f"no rule version {draft_id}", status=404, code="not_found")
    if d.status != "draft":
        raise ChangeError(f"version {d.version} is {d.status}, not a draft under review")
    return d


def approve_draft(
    engine: Engine, clock: Clock, *, org_id: str, draft_id: str, actor: Actor, attest: bool = False
) -> None:
    role = _role(actor, "policy.approve")
    with transaction(engine) as conn:
        d = _lock_draft(conn, org_id, draft_id)
        if d.proposed_by == actor.id:
            raise ChangeError(
                "a second, different person must approve the draft",
                status=403,
                code="self_approval_forbidden",
            )
        proposer_role = _user_role(conn, org_id, d.proposed_by)
        if Role.COMPLIANCE_LEAD not in {proposer_role, role}:
            raise ChangeError(
                "the compliance lead must be one of the two people on every rule activation (C-06)",
                status=403,
                code="compliance_lead_required",
            )
        if role is Role.COMPLIANCE_LEAD and not attest:
            raise AttestationRequired("the compliance lead attests to the rules when approving them")
        active = active_policy(conn, org_id)
        if active.version != d.base_version:
            raise ChangeError(
                f"the draft was based on version {d.base_version}, but version {active.version} is now active"
            )
        rules = load_ruleset(d.yaml)
        reasons = loosening_reasons(active.rules, rules)
        now = clock.now()
        attested_by = d.attested_by or (actor.id if role is Role.COMPLIANCE_LEAD else None)
        conn.execute(
            text("UPDATE policy_versions SET status='superseded' WHERE org_id=:o AND id=:i"),
            {"o": org_id, "i": active.id},
        )
        conn.execute(
            text(
                "UPDATE policy_versions SET status='active', approved_by=:ab, approver_roles=:ar, "
                "attested_by=:att, activated_at=:t WHERE org_id=:o AND id=:i"
            ),
            {
                "ab": [actor.id],
                "ar": [proposer_role.value if proposer_role else "unknown", role.value],
                "att": attested_by,
                "t": now,
                "o": org_id,
                "i": d.id,
            },
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="policy.superseded",
            subject_id=active.id,
            payload={"version": active.version, "superseded_by": d.version},
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="policy.activated",
            subject_id=d.id,
            payload={
                "version": d.version,
                "content_hash": d.content_hash,
                "approvers": [d.proposed_by, actor.id],
                "approver_roles": [proposer_role.value if proposer_role else None, role.value],
                "loosening": bool(reasons),
                "loosening_reasons": reasons,
                "attestation": d.attestation,
                "attested_by": attested_by,
            },
        )


def withdraw_draft(engine: Engine, clock: Clock, *, org_id: str, draft_id: str, actor: Actor) -> None:
    _role(actor, "policy.propose")
    with transaction(engine) as conn:
        d = _lock_draft(conn, org_id, draft_id)
        conn.execute(
            text("UPDATE policy_versions SET status='withdrawn' WHERE org_id=:o AND id=:i"),
            {"o": org_id, "i": d.id},
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="policy.withdrawn",
            subject_id=d.id,
            payload={"version": d.version},
        )


_COLS = (
    "id, version, status, proposed_by, approved_by, approver_roles, loosening, loosening_reasons, "
    "attestation, attested_by, base_version, content_hash, created_at, activated_at"
)


def _row(r: Any) -> dict[str, Any]:
    d = dict(r._mapping)
    for k in ("created_at", "activated_at"):
        d[k] = d[k].isoformat().replace("+00:00", "Z") if d[k] else None
    d["approved_by"] = list(d["approved_by"] or [])
    d["approver_roles"] = list(d["approver_roles"] or [])
    return d


def list_versions(engine: Engine | Connection, org_id: str) -> list[dict[str, Any]]:
    sql = text(f"SELECT {_COLS} FROM policy_versions WHERE org_id=:o ORDER BY version DESC")  # noqa: S608
    if isinstance(engine, Connection):
        return [_row(r) for r in engine.execute(sql, {"o": org_id})]
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(sql, {"o": org_id})]


def get_version(conn: Connection, org_id: str, version: int) -> dict[str, Any] | None:
    r = conn.execute(
        text(f"SELECT {_COLS}, yaml FROM policy_versions WHERE org_id=:o AND version=:v"),  # noqa: S608
        {"o": org_id, "v": version},
    ).one_or_none()
    return _row(r) if r else None


def draft_diff(conn: Connection, org_id: str, draft: dict[str, Any]) -> list[dict[str, Any]]:
    """The draft against the active version, for the console."""
    active = active_policy(conn, org_id)
    return diff(active.rules, load_ruleset(draft["yaml"]))
