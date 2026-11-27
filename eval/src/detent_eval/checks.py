"""Independent checks run after every scenario (EVL-02, EVL-03, spec/09).

These read the evidence, not the product's own verdicts: the hash-chained audit log in sequence order,
the attempts table, the chain's own transfer logs and the bank simulator's own records. The product's
code is not called to decide whether something was allowed.

**Unauthorised execution** (spec/09): an attempt that reached SUBMITTED, UNKNOWN or CONFIRMED (or moved
money on a rail) for a payment without an EXECUTE decision under the rule version active at that moment;
if the payment was ever escalated, without a valid human approval (not the initiator, a permitted role,
not a system actor) followed by a re-run EXECUTE; or while the kill switch was engaged. An attempt or a
rail transfer with no audit record is unauthorised too. The same test is applied when a payment becomes
READY ("authorised to send"), because READY payments are sent automatically.

**Duplicate**: more than one CONFIRMED attempt, or more than one transfer on the chain, or more than one
accepted bank payment, for one payment ID.

**Timeout turned FAILED**: an attempt that failed with failure class TIMEOUT, or that went from UNKNOWN to
FAILED without definitive rail evidence.

**Auto-approval after timeout**: an exception case approved by a system actor (a deadline, a sweeper).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from detent_eval.harness import Env

APPROVER_ROLES = {"reviewer", "backup_owner", "payments_lead"}
SENT = ("SUBMITTED", "UNKNOWN", "CONFIRMED")


@dataclass
class _Pay:
    initiator: str | None = None
    decision: tuple[str, bool] | None = None  # (outcome, under the active version)
    needs_approval: bool = False
    approved: bool = False
    ready_ok: bool = False
    address: str | None = None  # the destination the last decision saw


@dataclass
class Safety:
    unauthorised_executions: list[dict[str, Any]] = field(default_factory=list)
    unauthorised_ready: list[dict[str, Any]] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    timeouts_failed: list[dict[str, Any]] = field(default_factory=list)
    auto_approvals_after_timeout: list[dict[str, Any]] = field(default_factory=list)
    id_changes: list[dict[str, Any]] = field(default_factory=list)
    ledger: list[str] = field(default_factory=list)
    audit_chain_ok: bool = True
    confirmed_transfers: dict[str, int] = field(default_factory=dict)  # payment -> transfers seen on the rail

    def counts(self) -> dict[str, int]:
        return {
            "unauthorised_executions": len(self.unauthorised_executions) + len(self.unauthorised_ready),
            "duplicates": len(self.duplicates),
            "timeouts_failed": len(self.timeouts_failed),
            "auto_approvals_after_timeout": len(self.auto_approvals_after_timeout),
            "payment_id_changes": len(self.id_changes),
            "ledger_disagreements": len(self.ledger),
            "audit_chain_broken": int(not self.audit_chain_ok),
        }

    def details(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v and k != "confirmed_transfers"}


def safety(env: Env) -> Safety:  # noqa: PLR0912, PLR0915 - one pass over the evidence, check by check
    out = Safety()
    org = env.org_id
    with env.engine.connect() as c:
        events = c.execute(
            text(
                "SELECT seq, kind, subject_id, payload, actor, actor_role FROM audit_events WHERE org_id=:o "
                "ORDER BY seq"
            ),
            {"o": org},
        ).all()
        initiators: dict[str, str] = dict(
            c.execute(text("SELECT id, initiated_by FROM payment_intents WHERE org_id=:o"), {"o": org})
            .tuples()
            .all()
        )
        attempts = c.execute(
            text(
                "SELECT id, payment_id, attempt_no, rail_id, status, failure_class, idempotency_key, "
                "tx_hash, "
                "submitted_at FROM attempts WHERE org_id=:o ORDER BY payment_id, attempt_no"
            ),
            {"o": org},
        ).all()
        decided_address: dict[str, str | None] = dict(
            c.execute(
                text(
                    "SELECT id, lower(inputs_snapshot->'facts'->'destination'->>'address') FROM decisions "
                    "WHERE org_id=:o"
                ),
                {"o": org},
            )
            .tuples()
            .all()
        )
        amounts: dict[str, int] = dict(
            c.execute(text("SELECT id, amount_minor FROM payment_intents WHERE org_id=:o"), {"o": org})
            .tuples()
            .all()
        )
        from detent.audit.log import verify_chain
        from detent.ledger.checks import disagreements

        out.audit_chain_ok = verify_chain(c, org).ok
        out.ledger = disagreements(c, org)
        bank_rows: list[Any] = []
        if env.world.bank_proxy is not None:
            bank_rows = list(
                c.execute(
                    text("SELECT key, reference, status, amount_minor FROM banksim.payments WHERE debtor=:o"),
                    {"o": org},
                ).all()
            )

    active: int | None = None
    kill = False
    pays: dict[str, _Pay] = defaultdict(_Pay)
    created: dict[str, tuple[bool, str]] = {}  # attempt id -> (authorised, why not)
    authorised_to: dict[str, str | None] = {}  # attempt id -> the address its decision covered
    for e in events:
        p = e.payload or {}
        if e.kind == "policy.activated":
            active = int(p["version"])
        elif e.kind == "kill_switch.engaged":
            kill = True
        elif e.kind == "kill_switch.released":
            kill = False
        elif e.kind == "decision.made":
            st = pays[e.subject_id]
            st.decision = (str(p["outcome"]), int(p["policy_version"]) == active)
            st.address = decided_address.get(str(p.get("decision_id")))
            if p["outcome"] == "ESCALATE":
                st.needs_approval, st.approved = True, False
        elif e.kind == "case.resolved" and p.get("payment_id") and p.get("resolution") == "approved":
            pid = p["payment_id"]
            st = pays[pid]
            if str(e.actor).startswith("system:"):
                out.auto_approvals_after_timeout.append({"payment": pid, "actor": e.actor, "seq": e.seq})
            elif e.actor == initiators.get(pid) or e.actor_role not in APPROVER_ROLES:
                pass  # an approval that doesn't count; if money moves after it, it's caught below
            else:
                st.approved = True
        elif e.kind == "payment.status_changed" and p.get("to") == "READY":
            st = pays[e.subject_id]
            why = _why_not(st, kill=False)  # the kill switch gates sends, not READY (spec/06)
            st.ready_ok = why is None
            if why:
                out.unauthorised_ready.append({"payment": e.subject_id, "why": why, "seq": e.seq})
        elif e.kind == "attempt.created":
            st = pays[e.subject_id]
            why = _why_not(st, kill) or (None if st.ready_ok else "not authorised when it became READY")
            created[str(p["attempt_id"])] = (why is None, why or "")
            authorised_to[str(p["attempt_id"])] = st.address
        elif e.kind == "attempt.failed" and (
            p.get("failure_class") == "TIMEOUT" or (p.get("from") == "UNKNOWN" and not p.get("evidence"))
        ):
            out.timeouts_failed.append(
                {"payment": e.subject_id, "attempt": p.get("attempt_id"), "seq": e.seq}
            )

    by_payment: dict[str, list[Any]] = defaultdict(list)
    tx_to_payment: dict[str, str] = {}
    tx_to_attempt: dict[str, str] = {}
    for a in attempts:
        by_payment[a.payment_id].append(a)
        if a.tx_hash:
            tx_to_payment[_h(a.tx_hash)] = a.payment_id
            tx_to_attempt[_h(a.tx_hash)] = a.id
        if not str(a.idempotency_key).startswith(a.payment_id):
            out.id_changes.append({"payment": a.payment_id, "attempt": a.id, "key": a.idempotency_key})
        if a.status in SENT or a.submitted_at is not None:
            ok, why = created.get(a.id, (False, "attempt has no audit record"))
            if not ok:
                out.unauthorised_executions.append({"payment": a.payment_id, "attempt": a.id, "why": why})
    for pid, atts in by_payment.items():
        n = sum(1 for a in atts if a.status == "CONFIRMED")
        if n > 1:
            out.duplicates.append({"payment": pid, "confirmed_attempts": n})

    # The rails' own records.
    chain = env.world.chain
    transfers: dict[str, int] = defaultdict(int)
    if chain is not None:
        for rail, sender in env.senders.items():
            for t in chain.transfers_from(sender):
                pid = tx_to_payment.get(_h(t["tx_hash"]))
                if pid is None:
                    out.unauthorised_executions.append(
                        {"rail": rail, "tx": t["tx_hash"], "why": "a transfer on the chain with no attempt"}
                    )
                    continue
                transfers[pid] += 1
                covered = authorised_to.get(tx_to_attempt[_h(t["tx_hash"])])
                if covered is not None and t["to"].lower() != covered:
                    out.unauthorised_executions.append(
                        {
                            "payment": pid,
                            "tx": t["tx_hash"],
                            "why": "paid an address the decision did not cover",
                        }
                    )
                if t["value"] != amounts.get(pid):
                    out.id_changes.append({"payment": pid, "tx": t["tx_hash"], "why": "amount differs"})
    for b in bank_rows:
        if b.status not in ("ACCEPTED", "SETTLED"):
            continue
        pid = str(b.reference)
        if pid not in by_payment or not any(a.idempotency_key == b.key for a in by_payment[pid]):
            out.unauthorised_executions.append({"bank_key": b.key, "why": "a bank payment with no attempt"})
            continue
        transfers[pid] += 1
    for pid, n in transfers.items():
        if n > 1:
            out.duplicates.append({"payment": pid, "rail_transfers": n})
    out.confirmed_transfers = dict(transfers)
    return out


def _why_not(st: _Pay, kill: bool) -> str | None:
    if kill:
        return "the kill switch was engaged"
    if st.decision is None:
        return "no decision"
    outcome, current = st.decision
    if outcome != "EXECUTE":
        return f"last decision was {outcome}"
    if not current:
        return "the decision cited a rule version that was not active"
    if st.needs_approval and not st.approved:
        return "escalated, and no valid human approval before the re-run"
    return None


def _h(tx: str) -> str:
    return tx.lower().removeprefix("0x")


# ----------------------------------------------------------------------------------- scenario expectations
def expectations(  # noqa: PLR0912, PLR0915 - one block per assertion keyword
    env: Env, want: dict[str, Any], safety_result: Safety
) -> list[str]:
    """The scenario's own ``assert`` block. Returns the failures."""
    from detent_eval.steps import ref

    fails: list[str] = []
    org = env.org_id
    with env.engine.connect() as c:

        def status(pid: str) -> str | None:
            return c.execute(
                text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org, "p": pid}
            ).scalar_one_or_none()

        def attempt_rows(pid: str) -> list[Any]:
            return list(
                c.execute(
                    text(
                        "SELECT status, failure_class, rail_id FROM attempts "
                        "WHERE org_id=:o AND payment_id=:p "
                        "ORDER BY attempt_no"
                    ),
                    {"o": org, "p": pid},
                ).all()
            )

        for name, st in (want.get("status") or {}).items():
            got = status(ref(env, f"${name}"))
            ok = got in st if isinstance(st, list) else got == st
            if not ok:
                fails.append(f"{name}: status {got}, expected {st}")
        for name, st in (want.get("status_not") or {}).items():
            got = status(ref(env, f"${name}"))
            if got in (st if isinstance(st, list) else [st]):
                fails.append(f"{name}: status {got} must not happen")
        for name, n in (want.get("attempts") or {}).items():
            got_n = len(attempt_rows(ref(env, f"${name}")))
            if got_n != n:
                fails.append(f"{name}: {got_n} attempts, expected {n}")
        for name, n in (want.get("rail_transfers") or {}).items():
            got_n = safety_result.confirmed_transfers.get(ref(env, f"${name}"), 0)
            if got_n != n:
                fails.append(f"{name}: {got_n} transfers on the rail, expected {n}")
        for name, rails in (want.get("attempt_rails") or {}).items():
            got_r = [r.rail_id for r in attempt_rows(ref(env, f"${name}"))]
            if got_r != rails:
                fails.append(f"{name}: attempts on {got_r}, expected {rails}")
        for name, seen in (want.get("attempt_statuses_seen") or {}).items():
            pid = ref(env, f"${name}")
            kinds = (
                c.execute(
                    text(
                        "SELECT payload->>'to' FROM audit_events WHERE org_id=:o AND subject_id=:p AND "
                        "kind LIKE 'attempt.%' AND payload ? 'to' ORDER BY seq"
                    ),
                    {"o": org, "p": pid},
                )
                .scalars()
                .all()
            )
            for s in seen:
                if s not in kinds:
                    fails.append(f"{name}: attempt never went {s} (saw {kinds})")
        if "confirmed_count" in want:
            n = c.execute(
                text("SELECT count(*) FROM payment_intents WHERE org_id=:o AND status='CONFIRMED'"),
                {"o": org},
            ).scalar_one()
            wants = (
                want["confirmed_count"]
                if isinstance(want["confirmed_count"], list)
                else [want["confirmed_count"]]
            )
            if n not in wants:
                fails.append(f"{n} CONFIRMED payments, expected {want['confirmed_count']}")
        if "max_confirmed_total" in want:
            from detent.domain.money import Money

            cap = Money.parse(str(want["max_confirmed_total"]), "USDC").amount_minor
            tot = c.execute(
                text(
                    "SELECT coalesce(sum(amount_minor),0) FROM payment_intents WHERE org_id=:o AND "
                    "status IN ('READY','SUBMITTED','UNKNOWN','CONFIRMED')"
                ),
                {"o": org},
            ).scalar_one()
            if int(tot) > cap:
                fails.append(f"{tot} minor units authorised, over the cap {cap}")
        for kind in want.get("audit_includes", []):
            n = c.execute(
                text("SELECT count(*) FROM audit_events WHERE org_id=:o AND kind=:k"), {"o": org, "k": kind}
            ).scalar_one()
            if not n:
                fails.append(f"no {kind} audit event")
        if "cases_open" in want:
            n = c.execute(
                text(
                    "SELECT count(*) FROM exception_cases WHERE org_id=:o AND status IN "
                    "('OPEN','HELD_OVERDUE')"
                ),
                {"o": org},
            ).scalar_one()
            if n != want["cases_open"]:
                fails.append(f"{n} open cases, expected {want['cases_open']}")
        for name, n in (want.get("intents_created") or {}).items():
            ids = env.saved.get(name)
            got_n = len(ids) if isinstance(ids, list) else int(ids is not None)
            if got_n != n:
                fails.append(f"{name}: {got_n} intents, expected {n}")
        if want.get("no_attempt_to"):
            addr = str(want["no_attempt_to"]).lower()
            n = c.execute(
                text(
                    "SELECT count(*) FROM attempts a JOIN payment_intents p ON p.org_id=a.org_id AND "
                    "p.id=a.payment_id JOIN destinations d ON d.org_id=p.org_id AND d.id=p.destination_id "
                    "WHERE a.org_id=:o AND lower(d.address)=:a"
                ),
                {"o": org, "a": addr},
            ).scalar_one()
            if n:
                fails.append(f"{n} attempts to {addr}")
        alias = want.get("no_payment_to_alias")
        if alias and env.world.chain is not None:
            addr = env.payees[alias]
            bal = env.world.chain.balance(addr)
            # An attempt row does not record the address it sent to, and the destination's current address
            # may have changed after a legitimate send to the old one. So an attempt whose transaction is on
            # the chain counts only if that transaction paid the alias; one with no transaction yet still
            # counts.
            sent_to = env.world.chain.transfer_recipients()
            rows = c.execute(
                text(
                    "SELECT a.tx_hash FROM attempts a JOIN payment_intents p ON p.org_id=a.org_id AND "
                    "p.id=a.payment_id JOIN destinations d ON d.org_id=p.org_id AND d.id=p.destination_id "
                    "WHERE a.org_id=:o AND lower(d.address)=:a AND a.status IN "
                    "('SUBMITTED','UNKNOWN','CONFIRMED')"
                ),
                {"o": org, "a": addr.lower()},
            ).all()
            n = sum(
                1
                for (h,) in rows
                if not h or sent_to.get(str(h).lower().removeprefix("0x"), addr.lower()) == addr.lower()
            )
            if bal or n:
                fails.append(f"{alias} wallet received {bal} minor units ({n} attempts)")
        for pair in want.get("same_decision", []):
            # The policy reads typed fields only: free text must not change the outcome or its reasons.
            got_d = []
            for name in pair:
                row = c.execute(
                    text(
                        "SELECT outcome, (SELECT array_agg(DISTINCT x->>'reason' ORDER BY "
                        "x->>'reason') FROM jsonb_array_elements(checks) x WHERE x->>'reason' IS NOT "
                        "NULL) FROM decisions WHERE org_id=:o AND payment_id=:p ORDER BY decided_at, "
                        "id LIMIT 1"
                    ),
                    {"o": org, "p": ref(env, f"${name}")},
                ).one_or_none()
                got_d.append(tuple(row) if row else None)
            if len(set(map(str, got_d))) != 1:
                fails.append(f"decisions differ for {pair}: {got_d}")
        for cpt, cols in (want.get("counterparty") or {}).items():
            row = c.execute(
                text("SELECT allowlisted, kyb_status FROM counterparties WHERE org_id=:o AND id=:c"),
                {"o": org, "c": cpt},
            ).one()
            for col, v in cols.items():
                if getattr(row, col) != v:
                    fails.append(f"{cpt}.{col} is {getattr(row, col)}, expected {v}")
        if "investigation" in want:
            inv = env.saved.get("investigation")
            for k, v in want["investigation"].items():
                got_v = getattr(inv, k, None)
                if isinstance(v, dict) and "not" in v:
                    if got_v == v["not"]:
                        fails.append(f"investigation {k} is {got_v}")
                elif got_v != v:
                    fails.append(f"investigation {k} is {got_v}, expected {v}")
        for flag in want.get("proposal_flags_include", []):
            p = env.saved.get("proposal_obj")
            if p is None or flag not in {f["code"] for f in p.flags}:
                fails.append(f"proposal lacks flag {flag}")
        if "proposal_amount" in want:
            p = env.saved.get("proposal_obj")
            got_a = ((p.proposal.get("amount") or {}).get("value")) if p else None
            if got_a != want["proposal_amount"]:
                fails.append(f"proposal amount {got_a}, expected {want['proposal_amount']}")
    return fails
