# Dekernai Agentic Payment Controls Constitution

## Core Principles

### I. The AI proposes; the policy decides (NON-NEGOTIABLE)

- Agents MUST NOT execute, approve, reject, retry, re-route or edit rules. Their only write tool is
  `propose_payment_intent`, which goes through the public API under a signed mandate.
- `detent.agents` MUST NOT import `detent.execution`, `detent.rails` or approval code; an
  import-boundary test enforces this.
- The policy MUST be deterministic, MUST read typed fields only and MUST NOT read agent free text.
- Untrusted text (invoices, notes, names, references, PDF metadata) MUST reach a model only inside
  delimited data blocks. Uncertain values MUST be flagged and nulled, never guessed.

Rationale: on irreversible rails a wrong decision cannot be undone; decisions stay with rules the
client owns (AGENTS.md invariants 5, 11; spec/05).

### II. Exactly once (NON-NEGOTIABLE)

- One `pay_` ID for life; retries, failovers and approvals keep it.
- At most one in-flight and one CONFIRMED attempt per payment, enforced by the database.
- A timeout is UNKNOWN, never FAILED. Nothing is resent while any attempt is UNKNOWN; only
  definitive rail evidence resolves it.
- Only the execution layer retries, only on `TECHNICAL_RETRYABLE`, only by configured rules.
- All state changes go through `transition()` under `SELECT ... FOR UPDATE` and the
  allowed-transitions table.

Rationale: "A failure can retry; a rejection can't; no retry can ever become a second payment"
(invariants 1–3, 6, 13).

### III. Blocks are final; timeouts are never approvals; fail closed (NON-NEGOTIABLE)

- BLOCKED and REJECTED are terminal; a block is never approved, retried, re-routed or resubmitted.
- An overdue case stays held; the counterparty is told; the backup owner takes over.
- Approval re-runs the policy with the active rule version; the approver is never the initiator.
- Any error in a decision path MUST lead to hold or the manual queue, never execute.
- The kill switch is checked inside the lock before every send; only the client's payments lead
  releases it.

Rationale: invariants 4, 7–10; product principles 3, 4, 7.

### IV. Evidence by construction

- Audit events are append-only, hash-chained and written in the same transaction as the change.
- Ledger entries are append-only; corrections are new entries.
- Every payment can be replayed from stored inputs and stored agent outputs; replay never calls a
  model.

Rationale: invariant 12; the auditor must accept the evidence (Product model A1, A2 "Prove").

### V. Test networks, integer money, tenant isolation, controlled time

- The prototype refuses chain IDs outside 84532, 11155111 and 31337, and rejects `sk_live_` keys.
- Money is integer minor units plus a currency; no floats in money paths.
- Every query is scoped by `org_id`.
- Time comes from the `Clock` service; no direct `datetime.now()` in `detent/`.

Rationale: invariants 14–17.

### VI. Test-first, and never weaken a test

- Each story's acceptance criteria become tests before the code. Stories that touch money include
  concurrency and fault tests.
- A test that guards an invariant MUST NOT be weakened to make a change pass; if a story seems to
  need an exception, work stops and the founder is asked.

Rationale: AGENTS.md "How to work a story" and "Non-negotiable invariants".

### VII. Honesty, independence and no invented rules

- Dekernai is "agentic payment controls" software; never a "payments company" or "payment provider".
- No client logos, testimonials, customer counts, volume figures, certification badges or
  licence claims; measured results are dated and labelled "test-network evaluation on synthetic
  data"; prototype surfaces are labelled.
- No former-employer names, documents or API designs; CI runs a private denylist check.
- Business rules MUST come from the founder's documents or an explicit founder decision. A rule the
  documents don't settle is recorded as a proposed decision and is not treated as confirmed until
  the founder approves it.

Rationale: spec/00 honesty rules; AGENTS.md "Things never to do" and "Open decisions".

## Product and Honesty Constraints

- Stack: Python 3.12 with uv; FastAPI and Pydantic v2; SQLAlchemy 2 and Alembic on Postgres 16;
  web3.py with anvil and MockUSDC; Jinja2 and htmx (no SPA); pytest, Hypothesis, ruff, mypy;
  Anthropic SDK with model IDs from settings; Mintlify docs; Astro site; Python and TypeScript SDKs.
- Never connect to a mainnet, a real bank or a real payment provider.
- Never commit `.env` files, keys or wallet secrets; never call the model inside replay.
- Hosting is in the UK or EU; residency is stated truthfully.
- Open founder decisions (name and domain, email provider, sandbox hosting tier, prices) are never
  guessed.

## Development Workflow and Quality Gates

- Work proceeds story by story from `backlog/stories.yaml`; commits carry the story ID.
- Every story passes `make lint typecheck test`; stories in POL, EXE, RAL, EXC and LED also pass
  `make eval` once it exists (M6).
- Definition of done: every acceptance criterion has a passing test or a written manual check;
  state-changing actions write audit events; no secrets, real personal data or former-employer
  material; user-facing text is honest.
- A spec that is wrong or incomplete is corrected in the same change, and the commit says so.
- Release gate (spec/09): any unauthorised execution, duplicate payment, timeout turned FAILED or
  auto-approval after a timeout fails the build regardless of other scores.

## Governance

- This constitution restates `AGENTS.md`; it does not supersede it. Amendments change both in the
  same commit and need the founder's approval.
- Versioning: MAJOR for removing or redefining a principle; MINOR for a new principle or section;
  PATCH for wording.
- Every plan's Constitution Check and every review verifies compliance with Principles I–VII.
  Any justified deviation is recorded in the plan's Complexity Tracking table and approved by the
  founder before implementation.

**Version**: 1.0.0 | **Ratified**: 2026-11-17 | **Last Amended**: 2026-11-18
