# Detent Constitution

Detent (working name) is **agentic payment controls**: one layer that decides, orchestrates and operates every deposit and payout, under the platform's own rules. It has three layers:
- **Decision:** execute, escalate or block.
- **Orchestration:** best rail by policy, exactly-once execution, failover on technical errors only, kill switch.
- **Operations:** exceptions, reconciliation, audit with replay.

AI agents work across all three; the rules make every decision. This constitution mirrors the invariants in `CLAUDE.md`. If they ever disagree, stop and ask the founder.

## Core Principles

### I. The rules decide; agents only propose (NON-NEGOTIABLE)
- AI agents prepare intents, investigate escalations and draft reconciliation fixes.
- They never execute, approve, reject, retry, re-route or edit rules.
- `detent.agents` must not import `detent.execution`, `detent.rails` or approval code, and an import-boundary test enforces this.
- Agent tools are read-only, except `propose_payment_intent` under a signed mandate.
- Untrusted text (invoices, notes, names, references) is data only. The policy reads typed fields, never agent free text.
- Every agent claim cites evidence, or it isn't shown.

### II. Exactly once (NON-NEGOTIABLE)
- One payment ID for life.
- At most one in-flight attempt and one CONFIRMED attempt per payment, enforced by database constraints.
- A timeout becomes UNKNOWN, never FAILED. Nothing is resent while an attempt is UNKNOWN.
- Retries are deterministic, run by the execution layer only, and only for technical failures.
- A failure can retry; a rejection can't; no retry can ever become a second payment.

### III. A block is final, and the system fails closed (NON-NEGOTIABLE)
- BLOCKED and REJECTED are terminal; a database trigger enforces it.
- A block is never approved, retried, re-routed or resubmitted.
- Any error in a decision path leads to hold or the manual queue, never execute.
- A timeout never becomes an approval: overdue cases stay held, the counterparty is told, and the backup owner takes over.
- Approval re-runs policy with the active rule version, and the approver can't be the initiator.
- The kill switch is checked inside the lock before every send, and only the client's payments lead can release it.

### IV. The client owns the rules
- Rules are versioned YAML, immutable once active.
- Activation needs two different approvers, and any loosening change needs the compliance lead.
- Every decision records the rule version and hash it used.
- Detent enforces the rules exactly and never holds funds or keys. The prototype holds test-network keys only.

### V. Proven, not asserted
- Test-first: tests come from each story's acceptance criteria before the code.
- Money paths need concurrency and fault tests.
- The release gate (100+ attack scenarios, 30+ fault cases) fails the build on any unauthorised execution, any duplicate payment, any timeout turned FAILED, or any approval by timeout, whatever other scores say.
- The audit log is append-only and hash-chained, written in the same transaction as the change it describes.
- Every payment can be replayed, without calling a model.

## Constraints

- **Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 with Alembic on Postgres 16, web3.py, Jinja2 and htmx, pytest and Hypothesis.
- **Models:** from settings: `claude-sonnet-5-5` for the agents, `claude-haiku-5-5` for light tasks, and `claude-opus-5-5` for evaluation only.
- **Networks:** test networks only. Refuse to start with a chain ID outside 84532, 11155111 or 31337, and reject `sk_live_` keys.
- **Money:** integer minor units plus a currency; no floats in money paths.
- **Tenancy and time:** every query is scoped by `org_id`, and time comes from the `Clock` service.
- **Data and honesty:**
  - no real client data, logos, testimonials or volume figures
  - no certification or licence claims
  - measured results are dated and labelled "test-network evaluation on synthetic data"
- **Wording:** "agentic payment controls", never "payments company" or "payment provider".
- **Independence:** no former-employer names, documents or API designs anywhere. A CI denylist check enforces this.

## Development Workflow

- **Sources:** the existing specs (`spec/00` to `spec/11`) and backlog (`backlog/user-stories.md`) are the source material. When running `/speckit-specify`, base each feature on one milestone or epic from `backlog/milestones.md` and keep its story IDs (for example, EXE-05) in the spec and tasks.
- **Order:** follow the milestones (M0 to M12). Each milestone's exit check must pass before the next one starts.
- **Gates:** every change passes lint, type checks and tests. Changes touching POL, EXE, RAL, EXC or LED also run `make eval`.
- **Commits:** reference the story ID. If a spec is wrong, fix the spec in the same change and say so.

## Governance

- This constitution and `CLAUDE.md` take precedence over generated plans and tasks.
- An amendment needs the founder's approval, a version bump and a matching update to `CLAUDE.md`.
- A plan or task that would weaken an invariant must stop and ask instead of working around it.

**Version**: 1.0.0 | **Ratified**: 2026-11-18 | **Last Amended**: 2026-11-18
