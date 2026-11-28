"""CON-11: the client's AI team. Each DekernAI agent shown as a team member, with its limits, its work and
what people and the rules did with it. Read-only: this module writes nothing and never calls a model.

The agents propose; the client's rules and people decide (invariant 5). The page shows both sides of every
item: what the agent proposed (from ``agent_calls``) and what followed (from the append-only audit log):
who resolved its flags, what the policy decided, who approved or rejected the case or the fix.

Only typed fields are shown (amounts, IDs, enums, flag codes). Untrusted text the agents read (invoice text,
names, notes) and the agents' own free text stay on the detail screens, which mark it as data (invariant 11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from detent.views.display import group_amount


@dataclass(frozen=True, slots=True)
class AgentProfile:
    kind: str  # agent_calls.kind
    actor: str  # the audit actor the agent writes as
    name: str
    layer: str
    job: str
    reads: tuple[str, ...]
    may: tuple[str, ...]
    never: tuple[str, ...]
    decides: str
    short: str = ""
    task: str = ""  # a few words for the team map


ROSTER: tuple[AgentProfile, ...] = (
    AgentProfile(
        kind="instruction",
        task="prepares payments",
        short="Ins",
        actor="system:instruction_agent",
        name="Instruction agent",
        layer="Decision",
        job="Reads an invoice and proposes a payment intent, only inside a signed mandate.",
        reads=("The invoice, as untrusted data", "The counterparty registry", "The mandates in force"),
        may=("Propose a payment intent (its one write tool)",),
        never=("Approve, send, retry or re-route a payment", "Change a rule, a mandate or a counterparty"),
        decides="A person resolves any flag first; then your policy decides execute, escalate or block.",
    ),
    AgentProfile(
        kind="investigation",
        task="gathers evidence",
        short="Inv",
        actor="system:investigation_agent",
        name="Investigation agent",
        layer="Operations",
        job="Gathers cited evidence for a held case so the reviewer can decide faster.",
        reads=("The case and its payment", "Counterparty and destination history", "Earlier decisions"),
        may=("Record evidence and a recommendation; uncited claims are removed",),
        never=("Approve or reject a case", "Send, retry or re-route a payment"),
        decides="The case owner approves or rejects; approval re-runs your policy before anything is sent.",
    ),
    AgentProfile(
        kind="reconciliation",
        task="proposes fixes",
        short="Rec",
        actor="system:reconciliation_agent",
        name="Reconciliation agent",
        layer="Operations",
        job="Proposes a fix when the ledger and a rail disagree.",
        reads=("The break and its evidence", "Candidate intents and accounts"),
        may=("Propose a ledger fix (match or credit)",),
        never=("Apply a fix or post to the ledger", "Edit or delete an entry"),
        decides="Only your payments lead applies or rejects a fix; an applied fix is a new ledger entry.",
    ),
)

# The audit events that answer an agent's work: the human (and policy) side of the interaction.
_FOLLOW_UPS = (
    "agent.flags_resolved",
    "decision.made",
    "case.resolved",
    "reconciliation.fix_applied",
    "reconciliation.fix_rejected",
    "payment.cancelled",
)

_LABEL = {
    ("investigation", "recorded"): "Evidence ready",
    ("reconciliation", "recorded"): "Fix proposed",
}
_STATUS = {
    "recorded": "Proposed",
    "needs_human": "Needs a person",
    "submitted": "Submitted",
}


@dataclass
class Interaction:
    at: datetime
    who: str
    role: str | None
    what: str
    outcome: str  # accepted | rejected | decided | neutral
    is_person: bool


@dataclass
class Activity:
    id: str
    kind: str
    at: datetime
    subject_id: str | None
    payment_id: str | None
    status: str
    status_label: str
    summary: str
    flags: list[str]
    source: str
    interactions: list[Interaction] = field(default_factory=list)


@dataclass
class TeamMember:
    profile: AgentProfile
    total: int
    needs_person: int
    accepted: int
    rejected: int
    last_at: datetime | None
    source: str | None  # the latest call's source: model | recording | replay
    activity: list[Activity]
    limits: list[tuple[str, str]]


def _amount(v: Any) -> str:
    return group_amount(v) if v not in (None, "") else "?"


def _summary(kind: str, parsed: dict[str, Any] | None) -> tuple[str, list[str]]:
    """A one-line summary from typed fields only (never invoice text or the model's free text)."""
    p = parsed or {}
    flags = [str(f.get("code")) for f in p.get("flags") or [] if isinstance(f, dict)]
    if kind == "instruction":
        v = {k: (x or {}).get("value") for k, x in (p.get("proposal") or {}).items()}
        payee = v.get("counterparty_id") or "an unmatched payee"
        line = f"Proposed {_amount(v.get('amount'))} {v.get('currency') or ''} to {payee}"
        if v.get("invoice_number"):
            line += f" for invoice {v['invoice_number']}"
        return line.replace("  ", " "), flags
    if kind == "investigation":
        rec = p.get("recommendation")
        n = len(p.get("claims") or [])
        if rec is None:
            return "Could not investigate; the case stays with the reviewer", flags
        return (
            f"Gathered {n} cited claim{'s' if n != 1 else ''}; recommends {str(rec).replace('_', ' ')}",
            flags,
        )
    fix = p.get("fix") or {}
    action = str(fix.get("action") or "needs_investigation")
    if action == "match_to":
        return f"Proposed matching the break to {fix.get('target')}", flags
    if action == "credit_account":
        return f"Proposed crediting account {fix.get('target')}", flags
    return "Could not propose a fix; asks a person to investigate", flags


def _interaction(row: Any) -> Interaction:
    p = row.payload or {}
    person = not str(row.actor).startswith("system:")
    who = row.display_name or (row.actor if person else "Your rules")
    if row.kind == "decision.made":
        outcome = str(p.get("outcome") or "").lower()
        return Interaction(
            row.at,
            f"Your rules (policy v{p.get('policy_version')})",
            None,
            f"decided {outcome}",
            "decided",
            False,
        )
    if row.kind == "agent.flags_resolved":
        return Interaction(row.at, who, row.actor_role, "resolved the flags", "neutral", person)
    if row.kind == "case.resolved":
        res = str(p.get("resolution") or "resolved")
        outcome = "accepted" if res == "approved" else "rejected" if res == "rejected" else "neutral"
        return Interaction(row.at, who, row.actor_role, f"{res} the case", outcome, person)
    if row.kind == "reconciliation.fix_applied":
        return Interaction(row.at, who, row.actor_role, "approved and applied the fix", "accepted", person)
    if row.kind == "reconciliation.fix_rejected":
        return Interaction(row.at, who, row.actor_role, "rejected the fix", "rejected", person)
    return Interaction(row.at, who, row.actor_role, "cancelled the payment", "rejected", person)


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def ai_team(
    conn: Connection, org_id: str, now: datetime, *, daily_token_budget: int, limit: int = 15
) -> list[TeamMember]:
    """Every agent on the roster, with its latest ``limit`` items and what followed each one."""
    calls = conn.execute(
        text(
            "SELECT id, kind, subject_id, payment_id, status, parsed, source, created_at FROM ("
            " SELECT *, row_number() OVER (PARTITION BY kind ORDER BY created_at DESC, id DESC) AS n"
            " FROM agent_calls WHERE org_id=:o AND kind IN ('instruction','investigation','reconciliation')"
            ") a WHERE n <= :lim ORDER BY created_at DESC, id DESC"
        ),
        {"o": org_id, "lim": limit},
    ).all()
    totals = {
        r.kind: (int(r.total), int(r.waiting))
        for r in conn.execute(
            text(
                "SELECT kind, count(*) AS total, count(*) FILTER (WHERE status='needs_human') AS waiting "
                "FROM agent_calls WHERE org_id=:o GROUP BY kind"
            ),
            {"o": org_id},
        )
    }
    tokens_today = int(
        conn.execute(
            text(
                "SELECT coalesce(sum(coalesce(tokens_in, 0) + coalesce(tokens_out, 0)), 0) FROM agent_calls "
                "WHERE org_id=:o AND created_at >= :d"
            ),
            {"o": org_id, "d": _day_start(now)},
        ).scalar_one()
    )
    items = []
    for c in calls:
        summary, flags = _summary(c.kind, c.parsed)
        items.append(
            Activity(
                id=c.id,
                kind=c.kind,
                at=c.created_at,
                subject_id=c.subject_id,
                payment_id=c.payment_id,
                status=c.status,
                status_label=_LABEL.get((c.kind, c.status), _STATUS.get(c.status, c.status)),
                summary=summary,
                flags=flags,
                source=c.source,
            )
        )
    # The instruction agent's subject is its own proposal; what follows it happens on the payment.
    subjects = sorted(
        {i.subject_id or i.id for i in items} | {i.id for i in items if i.kind == "instruction"}
    )
    payments = sorted({i.payment_id for i in items if i.payment_id})
    follow = conn.execute(
        text(
            "SELECT e.at, e.seq, e.actor, e.actor_role, e.kind, e.subject_id, e.payload, u.display_name "
            "FROM audit_events e LEFT JOIN users u ON u.org_id = e.org_id AND u.id = e.actor "
            "WHERE e.org_id=:o AND e.kind = ANY(CAST(:k AS text[])) "
            "AND (e.subject_id = ANY(CAST(:s AS text[])) OR e.subject_id = ANY(CAST(:p AS text[])) "
            "OR (e.kind='case.resolved' "
            "AND e.payload->>'payment_id' = ANY(CAST(:p AS text[])))) ORDER BY e.seq"
        ),
        {"o": org_id, "k": list(_FOLLOW_UPS), "s": subjects, "p": payments},
    ).all()
    for e in follow:
        keys = {e.subject_id, (e.payload or {}).get("payment_id")}
        for i in items:
            ours = (i.subject_id or i.id) in keys or i.id in keys or (i.payment_id and i.payment_id in keys)
            if ours and e.at >= i.at:
                i.interactions.append(_interaction(e))
    mandates = conn.execute(
        text(
            "SELECT id, payload FROM mandates WHERE org_id=:o AND revoked_at IS NULL "
            "AND valid_from <= :t AND expires_at >= :t ORDER BY created_at, id"
        ),
        {"o": org_id, "t": now},
    ).all()
    budget = f"{tokens_today:,} of {daily_token_budget:,} tokens used today (shared by the team)"
    team = []
    for prof in ROSTER:
        mine = [i for i in items if i.kind == prof.kind]
        total, waiting = totals.get(prof.kind, (0, 0))
        outcomes = [x.outcome for i in mine for x in i.interactions if x.is_person]
        limits: list[tuple[str, str]] = []
        if prof.kind == "instruction":
            for m in mandates:
                s = m.payload["scope"]
                per = s.get("max_per_payment") or {}
                tot = s.get("max_total") or {}
                limits.append(
                    (
                        f"Mandate {m.id}",
                        f"up to {_amount(per.get('amount'))} {per.get('currency')} per payment, "
                        f"{_amount(tot.get('amount'))} {tot.get('currency')} in total; "
                        f"{len(s.get('payees') or [])} payee(s) on {', '.join(s.get('networks') or [])}",
                    )
                )
            if not mandates:
                limits.append(("Mandates", "None in force: the agent cannot propose a payment"))
        tools = (
            "Read-only, except proposing a payment intent"
            if prof.kind == "instruction"
            else "Read-only; it records only its own findings"
        )
        limits.append(("Tools", tools))
        limits.append(("AI budget", budget))
        team.append(
            TeamMember(
                profile=prof,
                total=total,
                needs_person=waiting,
                accepted=outcomes.count("accepted"),
                rejected=outcomes.count("rejected"),
                last_at=mine[0].at if mine else None,
                source=mine[0].source if mine else None,
                activity=mine,
                limits=limits,
            )
        )
    return team


@dataclass
class TeamMap:
    """The overview's team map: who is waiting for a person right now, and the latest hand-backs."""

    members: list[TeamMember]
    waiting: list[tuple[TeamMember, Activity]]
    recent: list[tuple[TeamMember, Activity, Interaction]]


def team_map(team: list[TeamMember], *, recent: int = 4) -> TeamMap:
    waiting = [
        (m, a)
        for m in team
        for a in m.activity
        if a.status == "needs_human" and not any(x.is_person for x in a.interactions)
    ]
    said = sorted(
        ((m, a, x) for m in team for a in m.activity for x in a.interactions if x.is_person),
        key=lambda t: t[2].at,
        reverse=True,
    )
    return TeamMap(team, waiting, said[:recent])
