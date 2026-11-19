# User stories

Generated from `backlog/stories.yaml` by `tools/build_backlog.py`. Edit the YAML, not this file.

Estimates are ideal developer-days for one developer working with Claude Code (Estimate).

## FND · Foundation

_A tested, deployable skeleton with the safety guards in place from day one_ · layer: All three (foundation) · track: prototype · 9 stories · 3.75 days

### FND-01 · Repository, tooling and CI

**As a** builder, **I want** a monorepo with the API app, migrations, lint, type checks and tests running in CI, **so that** every story ships tested and nothing merges red.

**Acceptance criteria**

- [x] `make test`, `make lint` (ruff) and `make typecheck` (mypy, strict on `detent/domain`) pass locally and in GitHub Actions on every push
- [x] CI starts a Postgres 16 service and runs Alembic migrations before tests
- [x] `.env.example` lists every setting; a secret scanner runs as a pre-commit hook and in CI
- [x] The README explains setup in under 10 commands

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S0 Foundation (done) · **Depends on:** none · **Traces to:** A7.prototype, B5.security

### FND-02 · Settings and test-network guard

**As a** builder, **I want** the app to refuse to start with any mainnet chain ID or live credentials, **so that** the prototype can never move real money.

**Acceptance criteria**

- [x] Given a configured chain ID outside {84532 Base Sepolia, 11155111 Ethereum Sepolia, 31337 local}, when the app or worker starts, then it exits with a clear error
- [x] Given an API key prefix `sk_live_`, when any request uses it, then it is rejected with 403 `live_mode_unavailable`
- [x] Settings load via pydantic-settings; no setting is read from os.environ elsewhere

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S0 Foundation (done) · **Depends on:** FND-01 · **Traces to:** A6.no_custody, L8

### FND-03 · Baseline schema and ID conventions

**As a** builder, **I want** the core tables, enums and constraints from spec/02-domain-model.md as the first migration, **so that** invariants are enforced by the database, not just by code.

**Acceptance criteria**

- [x] IDs are prefixed UUIDv7 strings (`pay_`, `att_`, `dec_`, `exc_`, `dep_`, `evt_`, `org_`)
- [x] Money is stored as integer minor units plus an ISO currency code; no floats anywhere in money paths
- [x] Every table carries `org_id`; every query in the repository layer filters by it
- [x] Partial unique indexes from the domain model exist (one in-flight attempt, one confirmed attempt per payment)

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S0 Foundation (done) · **Depends on:** FND-01 · **Traces to:** A2b.states, A2.Intent

### FND-04 · Demo login and acting-user switcher

**As a** demo viewer, **I want** one demo password and a switcher to act as the payments lead, compliance lead, reviewer, backup owner or on-call engineer, **so that** the demo shows who is allowed to do what without building full auth.

**Acceptance criteria**

- [x] One shared password protects the console; after login the viewer picks an acting user
- [x] Every write records the acting user ID and role in the audit log
- [x] Role checks run on the server; hiding a button is never the only control

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S0 Foundation (done) · **Depends on:** FND-03 · **Traces to:** B3.rule_changes, B3.kill_switch, A2.Exceptions

### FND-05 · Controllable clock

**As a** demo viewer, **I want** to fast-forward time in demo mode, **so that** deadlines, overdue escalations and UNKNOWN resolution can be shown in minutes.

**Acceptance criteria**

- [x] All code reads time from a Clock service; a lint rule or test fails on direct `datetime.now()` in `detent/`
- [x] In demo mode the console can advance the clock by 15 min, 1 h or 1 day; outside demo mode the control is absent
- [x] Tests use a frozen clock

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S0 Foundation (done) · **Depends on:** FND-01 · **Traces to:** B3.exceptions, MVP.flow

### FND-06 · Background worker and job loop

**As a** builder, **I want** one worker process running scheduled and queued jobs from Postgres, **so that** UNKNOWN resolution, deadline sweeps, chain watching and webhook delivery survive restarts.

**Acceptance criteria**

- [x] Jobs are claimed with `SELECT ... FOR UPDATE SKIP LOCKED`; each job is idempotent
- [x] Killing the worker mid-job and restarting it never duplicates a side effect (tested)
- [x] Job runs, failures and durations are logged with the payment ID where relevant

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S0 Foundation (done) · **Depends on:** FND-03 · **Traces to:** B5.resilience

### FND-07 · Deploy to an EU region

**As a** founder, **I want** the web app and worker deployed in an EU region with Postgres in an EU region, **so that** the demo is reachable and data residency is truthful.

**Acceptance criteria**

- [ ] Web service and worker deploy from main; database is Neon in an EU region
- [ ] `/healthz` checks the database and both chain RPCs and reports each
- [ ] spec/10-security-and-deploy.md records the regions; the console footer states them

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S9 Demo-ready prototype in the EU · **Depends on:** FND-06 · **Traces to:** B5.hosting, B4.infra, A5.data

### FND-08 · Structured logs and request IDs

**As a** on-call engineer, **I want** JSON logs with request ID and payment ID on every line, **so that** any incident can be traced end to end.

**Acceptance criteria**

- [x] Every HTTP request gets a `request_id`, returned in the `Request-Id` header
- [x] Log lines include `payment_id` when one is in context
- [ ] Keys, secrets, full wallet private data and invoice bodies are never logged (tested with a log capture)

**Priority:** Should · **Estimate:** 0.25 d · **Milestone:** S0 Foundation (done) · **Depends on:** FND-01 · **Traces to:** B5.security, B3.incident

### FND-09 · Local EVM with a mock USDC for tests

**As a** builder, **I want** a local chain (anvil) with a mock 6-decimal USDC contract deployed by script, **so that** CI and the fault suite run deterministically without faucets or public RPC limits.

**Acceptance criteria**

- [x] `make chain` starts anvil and deploys MockUSDC; addresses are written to a test config
- [ ] The EVM adapter runs its contract tests against the local chain in CI
- [x] Public testnets are used only in nightly runs and the live demo

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S0 Foundation (done) · **Depends on:** FND-01 · **Traces to:** L3, A5.gate

## INT · Payment intents

_Every payment starts as an intent with one payment ID for life_ · layer: Decision · track: prototype · 5 stories · 2 days

### INT-01 · Create a payout intent

**As a** platform integrator, **I want** to POST a payout intent with amount, currency, payee, optional network, reference and notes, **so that** every payment starts with one ID and gets a decision before any money moves.

**Acceptance criteria**

- [x] POST /v1/payment_intents returns 201 with a `pay_` ID, the decision and the status
- [ ] The payment ID is assigned once and never changes through retries, failovers or approvals
- [x] Invalid input returns 422 with the standard error body and no intent is created
- [x] `source` is `platform` or `agent`; `agent` requires a `mandate_id`

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S1 A platform payout is decided through the API (done) · **Depends on:** FND-03 · **Traces to:** A2.Intent, A2b.states

### INT-02 · Idempotent creates

**As a** platform integrator, **I want** an `Idempotency-Key` on every create call, **so that** a network retry on my side can never create a second payment.

**Acceptance criteria**

- [x] Given the same key and the same body, when I repeat the call, then I get the original response and no new intent
- [x] Given the same key and a different body, then I get 409 `idempotency_conflict`
- [x] Keys are scoped per organisation; two parallel requests with one key create exactly one intent (concurrency test)

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S1 A platform payout is decided through the API (done) · **Depends on:** INT-01 · **Traces to:** A2.Execute, A6.retry_rule, D.standards, L3

### INT-03 · Read and list intents

**As a** platform integrator, **I want** to fetch an intent with its full timeline and to list intents with filters, **so that** I can show status to my users and debug my integration.

**Acceptance criteria**

- [x] GET /v1/payment_intents/{id} includes decisions, checks, attempts, ledger postings and events
- [x] GET /v1/payment_intents supports cursor pagination and filters by status, rail and created range
- [x] Another organisation's ID returns 404, never 403

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S1 A platform payout is decided through the API (done) · **Depends on:** INT-01 · **Traces to:** A2.Prove, D.standards

### INT-04 · Counterparty registry with wallet history

**As a** payments lead, **I want** counterparties with KYB status, wallets or bank accounts, first-seen and last-changed times and payment history, **so that** the policy can check "new wallet", "changed details", "first payment" and "above norm" from facts.

**Acceptance criteria**

- [x] Each payout destination stores `first_seen_at` and `last_changed_at`; editing it updates `last_changed_at` and writes an audit event
- [x] Each counterparty exposes payment count and median amount, computed from confirmed payments
- [x] Counterparties are seeded from fixtures and editable in the console

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S1 A platform payout is decided through the API (done) · **Depends on:** FND-03 · **Traces to:** A2.Policy, A2b.unusual, A2b.raw_facts

### INT-05 · Cancel an intent before it is sent

**As a** payments lead, **I want** to cancel an escalated, held or ready intent, **so that** a payment we no longer want never goes out.

**Acceptance criteria**

- [ ] Cancel is allowed from ESCALATED, HELD or READY only; from SUBMITTED or UNKNOWN it returns 409
- [ ] CANCELLED is terminal and audited with the actor and reason

**Priority:** Should · **Estimate:** 0.25 d · **Milestone:** L After launch (Should and Could) · **Depends on:** EXE-01 · **Traces to:** A2.Intent

## POL · Policy and decisions

_A deterministic, versioned, client-owned policy layer decides execute, escalate or block_ · layer: Decision · track: prototype · 9 stories · 5 days

### POL-01 · Rule-set format and loader

**As a** compliance lead, **I want** our rules as a versioned YAML rule set with named checks and parameters, **so that** the rules are ours, readable and exactly enforced.

**Acceptance criteria**

- [x] Rule sets follow spec/04-policy.md and are validated against a schema on load; an invalid file is rejected with line-level errors
- [x] A loaded version is immutable and identified by version number and content hash
- [x] Every decision stores the version and hash it used

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S1 A platform payout is decided through the API (done) · **Depends on:** FND-03 · **Traces to:** A2.Policy, A6.client_rules, B3.rule_changes

### POL-02 · Decision engine and precedence

**As a** payments lead, **I want** every intent evaluated against all checks with execute, escalate or block and a reason per check, **so that** I can see exactly why each payment was decided.

**Acceptance criteria**

- [x] Each check returns PASS, ESCALATE or BLOCK with a reason code, parameters and evidence references
- [x] Final decision: BLOCK if any check blocks; else ESCALATE if any escalates; else EXECUTE
- [x] Same inputs and rule version always give the same decision (property-based test)
- [ ] Rules-only evaluation p95 under 50 ms locally (benchmark in EVL-08)

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S1 A platform payout is decided through the API (done) · **Depends on:** POL-01, INT-01 · **Traces to:** A2.Decide, A6.block_final, A1.reviews

### POL-03 · Compliance checks (KYB, allowlist, screening, Travel Rule, network)

**As a** compliance lead, **I want** KYB, allowlist, screening, Travel Rule and allowed-network checks, **so that** no payment reaches a payee we haven't cleared.

**Acceptance criteria**

- [x] KYB not verified -> BLOCK; KYB pending -> ESCALATE
- [x] Payee not on allowlist -> ESCALATE (first payment)
- [x] Mock screening list hit on address or name -> BLOCK `SCREENING_HIT`; screening unavailable -> fail closed per POL-09
- [x] Travel Rule originator and beneficiary fields missing above the configured threshold -> ESCALATE
- [x] Network or currency not allowed for the platform -> BLOCK
- [x] Screening sits behind a `Screening` interface so a real vendor can replace the mock

**Priority:** Must · **Estimate:** 1 d · **Milestone:** S1 A platform payout is decided through the API (done) · **Depends on:** POL-02, INT-04 · **Traces to:** A2.Policy, B4.risk_data

### POL-04 · Limits and daily caps

**As a** compliance lead, **I want** an auto-approval limit, a hard maximum and daily caps on routine payments, **so that** large or accumulated payments always reach a human, and splitting a payment can't get around a cap.

**Acceptance criteria**

- [x] Above the auto limit -> ESCALATE; above the hard maximum -> BLOCK
- [x] Daily caps per platform and per counterparty count confirmed plus in-flight amounts
- [x] Cap counters update atomically; 20 parallel intents that together exceed the cap never all execute (concurrency test)

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S1 A platform payout is decided through the API (done) · **Depends on:** POL-02 · **Traces to:** A2.Policy, A2b.unusual

### POL-05 · Unusual activity as checkable rules

**As a** compliance lead, **I want** new wallet, changed details, first payment and amount above the counterparty's norm as explicit rules, **so that** "unusual" is something the system can check and a reviewer can verify.

**Acceptance criteria**

- [x] Wallet first seen within N days -> ESCALATE `NEW_WALLET`; destination changed within N days -> ESCALATE `CHANGED_DETAILS`
- [x] No prior confirmed payment to this counterparty -> ESCALATE `FIRST_PAYMENT`
- [x] Amount above k x the counterparty's median -> ESCALATE `ABOVE_NORM`
- [x] Each hit stores the raw fact (address, timestamps, median, ratio) as evidence

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S3 Escalate, review raw facts, approve with a policy re-run (done) · **Depends on:** POL-02, INT-04 · **Traces to:** A2b.unusual, A2b.raw_facts

### POL-06 · A block is final

**As a** compliance lead, **I want** a blocked payment to stay blocked whatever anyone does next, **so that** no approval, retry or other rail can override a compliance decision.

**Acceptance criteria**

- [x] BLOCKED has no outgoing transitions in the state machine and a database trigger rejects any status change away from it
- [ ] Approve, retry, reroute or resubmit on a blocked payment returns 409 `payment_blocked`
- [x] A new intent to the same counterparty or the same destination address within 24 h of a block, whatever the amount, is escalated RESUBMISSION_AFTER_BLOCK with a link to the blocked one (D-10)

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S3 Escalate, review raw facts, approve with a policy re-run (done) · **Depends on:** POL-02, EXE-01 · **Traces to:** A6.block_final, A2b.rule, L5

### POL-07 · Versioned rule changes with two approvers

**As a** compliance lead, **I want** rule changes proposed as a new version and activated only after a second person approves, **so that** no single person can quietly weaken our controls.

**Acceptance criteria**

- [x] A proposer creates a draft version; the console shows a diff against the active version
- [x] Activation needs a second, different user; if any rule loosens (higher limit, removed check, shorter screening scope, longer window) the compliance lead must be one of the two
- [x] On activation the compliance lead's attestation is recorded: the client approves these rules and keeps AML accountability
- [x] All versions are kept and readable; decisions link to the version used

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S6 Operations around escalations (done) · **Depends on:** POL-01, FND-04 · **Traces to:** B3.rule_changes, A6.client_rules, B1.contracts, B3.onboarding

### POL-08 · Decision-only API

**As a** platform integrator, **I want** POST /v1/decisions to get a decision without Detent executing anything, **so that** I can use Detent before my own payout process, and shadow mode can reuse the same engine.

**Acceptance criteria**

- [x] Returns the same decision object as intent creation, with `executed: false`
- [x] Decisions are stored and audited but never create attempts

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S1 A platform payout is decided through the API (done) · **Depends on:** POL-02 · **Traces to:** A2.Decide, A3.shadow

### POL-09 · Fail closed

**As a** compliance lead, **I want** any internal error during a decision to hold the payment or send it to manual review, **so that** nothing is ever executed unchecked.

**Acceptance criteria**

- [x] If policy evaluation, screening or a data read fails, the decision is ESCALATE `SYSTEM_UNAVAILABLE` routed by the platform's fail-safe setting (`hold` or `manual_queue`)
- [x] No code path turns an error into EXECUTE (fault-injection test on each dependency)

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S1 A platform payout is decided through the API (done) · **Depends on:** POL-02 · **Traces to:** A6.fail_closed, B5.failsafe

## AGT · Mandates and instruction agent

_An AI agent can propose payments from invoices, only inside a signed mandate, and can never move money_ · layer: Decision (agents serve all three) · track: prototype · 9 stories · 4 days

### MND-01 · Signed mandate for an AI agent

**As a** payments lead, **I want** to issue a mandate that limits what an agent may propose (payees, per-payment and total amounts, networks, currencies and expiry), **so that** an agent can only ask for payments inside a scope we signed.

**Acceptance criteria**

- [x] Mandates are JSON with an HMAC-SHA256 signature by the platform's mandate key (format in spec/05-agents.md)
- [x] Invalid signature, unknown agent or expired mandate are detectable without calling the model
- [x] The format keeps fields that map to AP2-style mandates later

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S5 An AI agent proposes the $18,500 invoice inside a mandate (done) · **Depends on:** FND-03 · **Traces to:** A2.Mandate

### MND-02 · Mandate check in the policy

**As a** compliance lead, **I want** agent-sourced intents checked against their mandate before any other check, **so that** an agent can never exceed what we delegated.

**Acceptance criteria**

- [x] Missing or invalid signature, revoked or expired mandate, payee outside scope, amount above per-payment limit, cumulative total above limit, or network outside scope -> BLOCK with the specific reason
- [x] Cumulative usage updates atomically (concurrency test)
- [x] The check re-runs at execution time

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S5 An AI agent proposes the $18,500 invoice inside a mandate (done) · **Depends on:** MND-01, POL-02 · **Traces to:** A2.Mandate, A5.proposes, D.sandbox

### MND-03 · Revoke a mandate

**As a** payments lead, **I want** to revoke a mandate at once, **so that** a misbehaving agent loses its permissions immediately.

**Acceptance criteria**

- [x] Revocation by console or API takes effect for every intent not yet SUBMITTED
- [x] An approved intent whose mandate is revoked before sending is BLOCKED `MANDATE_REVOKED` at the pre-send re-check

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S5 An AI agent proposes the $18,500 invoice inside a mandate (done) · **Depends on:** MND-02, EXE-03 · **Traces to:** A2.Mandate

### AGT-01 · Instruction agent turns an invoice into a proposed intent

**As a** payments lead, **I want** the instruction agent to read a supplier invoice and propose a structured payment intent, **so that** our accounts-payable work can be delegated without giving the agent any power to pay.

**Acceptance criteria**

- [x] Input: invoice text or PDF; output: payee, matched counterparty, amount, currency, network, wallet, invoice number, due date, each with confidence and the source text span
- [x] Uses the agents model from config (default `claude-sonnet-5-5`) with tool use and a strict JSON schema; output is validated by Pydantic
- [x] Invalid output is retried once, then the proposal is marked `needs_human`
- [ ] The canonical $18,500 USDC invoice yields the expected intent on 10 of 10 runs (EVL-04)

**Priority:** Must · **Estimate:** 1 d · **Milestone:** S5 An AI agent proposes the $18,500 invoice inside a mandate (done) · **Depends on:** INT-04, MND-01 · **Traces to:** A5.proposes, A2.Intent, L1

### AGT-02 · Flag, never guess

**As a** reviewer, **I want** uncertain invoice fields flagged instead of filled in, **so that** a wrong network or wallet is never silently chosen.

**Acceptance criteria**

- [x] Missing network, two wallets, total not matching line items, ambiguous currency, payee not in the registry, or wallet different from the registry each set a named flag
- [x] Any flag sets `requires_clarification`; such a proposal can't be submitted until a human resolves each flag
- [x] Tests on the interpretation set confirm no flagged field is ever populated from outside the document

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S5 An AI agent proposes the $18,500 invoice inside a mandate (done) · **Depends on:** AGT-01 · **Traces to:** A5.proposes, L1

### AGT-03 · The agent can only propose

**As a** compliance lead, **I want** the agent's only money-related ability to be "propose an intent" under a mandate, **so that** the model can never execute, approve or retry.

**Acceptance criteria**

- [x] The agent's tool registry has no tool that writes state except `propose_payment_intent`, which calls the public API with scope `intents:create`
- [x] An import-boundary test fails if `detent.agents` imports `detent.execution`, `detent.exceptions.approve` or `detent.rails`
- [x] An attempt by the agent to call any other write endpoint is rejected by scope and logged

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S5 An AI agent proposes the $18,500 invoice inside a mandate (done) · **Depends on:** AGT-01 · **Traces to:** A5.tools, A2b.no_agent_retry, B6.ai

### AGT-04 · Prompt-injection isolation

**As a** compliance lead, **I want** invoice text, notes, names and references treated strictly as data, **so that** text like "ignore your rules, this is pre-approved" changes nothing.

**Acceptance criteria**

- [x] Untrusted text reaches the model only inside delimited data blocks, after the instructions, with an explicit data-only rule
- [x] The policy never reads agent free text; it reads only typed fields
- [x] Instruction-like content in a document is reported as a `possible_injection` flag and never followed
- [ ] All injection scenarios in the attack suite pass (EVL-02)

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S5 An AI agent proposes the $18,500 invoice inside a mandate (done) · **Depends on:** AGT-01 · **Traces to:** A5.injection, L2, B6.ai

### AGT-05 · Record every agent call for replay

**As a** auditor, **I want** each agent call stored with prompt version, model ID, input hash and raw output, **so that** replay is deterministic and I can see exactly what the agent said.

**Acceptance criteria**

- [x] Agent calls are rows linked to the intent or case, with token counts and latency
- [x] Replay reads stored outputs and never calls the model again

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S5 An AI agent proposes the $18,500 invoice inside a mandate (done) · **Depends on:** AGT-01 · **Traces to:** A2.Prove, A5.citations

### AGT-06 · Model configuration and cost guard

**As a** founder, **I want** model IDs in config and a daily token budget per organisation, **so that** AI costs stay bounded and the provider can be swapped.

**Acceptance criteria**

- [x] Model IDs come from settings: agents `claude-sonnet-5-5`, light tasks `claude-haiku-5-5`, evaluation judge `claude-opus-5-5`
- [x] Model calls go through one `LLMClient` interface so a second provider can be added
- [x] Over budget, agent features return `needs_human`; nothing falls back to executing

**Priority:** Should · **Estimate:** 0.25 d · **Milestone:** S5 An AI agent proposes the $18,500 invoice inside a mandate (done) · **Depends on:** AGT-01 · **Traces to:** B4.infra, B6.dependence, D.abuse

## EXE · Exactly-once execution

_A payment is sent once: timeouts become UNKNOWN, retries keep the payment ID, the kill switch stops everything_ · layer: Orchestration · track: prototype · 10 stories · 5.75 days

### EXE-01 · Payment state machine

**As a** builder, **I want** one transition function with an allowed-transitions table, called under a row lock, **so that** no code can put a payment into an impossible state.

**Acceptance criteria**

- [x] All status changes go through `transition(payment_id, to_status, reason, actor)`, which runs `SELECT ... FOR UPDATE` in one transaction
- [x] Illegal transitions raise, change nothing and write an audit event
- [x] Property-based tests on random event sequences never reach a state outside the table in spec/02-domain-model.md

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S2 An EXECUTE decision is sent exactly once (done) · **Depends on:** FND-03 · **Traces to:** A2b.states, A2.Execute

### EXE-02 · Attempts and exactly-once guarantees

**As a** payments lead, **I want** each send recorded as an attempt under the same payment ID, with database guarantees against a second payment, **so that** no retry or failover can ever pay twice.

**Acceptance criteria**

- [x] At most one attempt per payment is SUBMITTED or UNKNOWN at a time (partial unique index)
- [x] At most one attempt per payment is CONFIRMED (partial unique index)
- [x] A new attempt is created only when the previous one is definitively FAILED
- [x] Rail idempotency keys are derived from the payment ID as defined in spec/06-rails-and-faults.md

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S2 An EXECUTE decision is sent exactly once (done) · **Depends on:** EXE-01 · **Traces to:** A2.Execute, A6.retry_rule, A2b.rule, L3

### EXE-03 · Pre-send checks under the lock

**As a** payments lead, **I want** the state lock, balance check, pre-funded wallet limit, kill switch and a fresh policy check right before every send, **so that** nothing is sent on stale or unsafe conditions.

**Acceptance criteria**

- [ ] Inside the lock: kill switch off, source balance covers amount plus fees or gas, the wallet's daily pre-funded limit has room, mandate valid
- [x] If the decision is older than the configured age or the rule version changed, policy re-runs first
- [x] Any failed check moves the payment to HELD with the reason; nothing is sent

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S2 An EXECUTE decision is sent exactly once (done) · **Depends on:** EXE-02, POL-02 · **Traces to:** A2.Execute, A2b.custody

### EXE-04 · Nonce manager

**As a** builder, **I want** nonces allocated per chain and wallet under a database lock and stored before broadcast, **so that** two different transactions never share a nonce.

**Acceptance criteria**

- [x] The nonce is written on the attempt before the transaction is broadcast
- [x] On startup the manager reconciles with `eth_getTransactionCount(pending)` and refuses to send if they disagree
- [x] Concurrent sends from one wallet get consecutive nonces (concurrency test)

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S2 An EXECUTE decision is sent exactly once (done) · **Depends on:** EXE-02, RAL-02 · **Traces to:** A2.Execute, A2b.custody

### EXE-05 · A timeout becomes UNKNOWN

**As a** payments lead, **I want** a send whose outcome is unclear marked UNKNOWN, never FAILED, **so that** a stuck transaction that later confirms is never paid a second time.

**Acceptance criteria**

- [x] A timeout, dropped connection or 5xx after the request may have reached the rail -> attempt and payment UNKNOWN
- [x] While UNKNOWN, no new attempt can be created (database and code)
- [x] Only a definitive rail answer moves UNKNOWN to CONFIRMED or FAILED

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S4 Never paid twice (done) · **Depends on:** EXE-02 · **Traces to:** A2b.unknown, A2b.states, L4

### EXE-06 · UNKNOWN resolver

**As a** payments lead, **I want** UNKNOWN payments resolved from the rail's own evidence, with a human decision if they stay stuck, **so that** we learn the real outcome quickly and never guess.

**Acceptance criteria**

- [x] The worker polls by transaction hash (chain) or idempotency key (bank) on a backoff schedule
- [x] CONFIRMED needs receipt status 1 and the rail's confirmation threshold; FAILED needs receipt status 0, the nonce consumed by another transaction, or the rail's definitive not-found
- [x] Still UNKNOWN after the threshold -> an `UNKNOWN_STUCK` exception to the payments lead, with two options: keep waiting, or approve a cancel-by-replacement (same nonce, zero value) carried out by the execution layer
- [x] Median and p95 time to resolve are recorded for the results report

**Priority:** Must · **Estimate:** 1 d · **Milestone:** S4 Never paid twice (done) · **Depends on:** EXE-05, FND-06, EXC-01 · **Traces to:** A2b.unknown, B7.unknown

### EXE-07 · Deterministic retry policy

**As a** compliance lead, **I want** retries decided by configured rules in the execution layer only, **so that** the AI never decides to retry and a rejection is never retried.

**Acceptance criteria**

- [x] Retry config lists retryable error codes, maximum attempts and backoff
- [x] Only `TECHNICAL_RETRYABLE` failures retry; `REJECTED_BY_RAIL` and any BLOCK never do
- [x] Every retry keeps the payment ID and is audited with the rule that allowed it

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S4 Never paid twice (done) · **Depends on:** EXE-02 · **Traces to:** A2b.no_agent_retry, A6.retry_rule, A2b.rule

### EXE-08 · Kill switch

**As a** payments lead, **I want** a kill switch that I or Detent's on-call engineer can pull, and that only I can release, **so that** we can stop all sending at once during an incident.

**Acceptance criteria**

- [x] Engaging (console button or POST /v1/kill_switch) stops new submissions; the flag is checked inside the lock before every send
- [x] Pending payments stay held; UNKNOWN attempts keep resolving read-only
- [x] Release requires the client's payments lead, even if on-call engaged it
- [x] A red banner shows on every console page while engaged; every change is audited

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S4 Never paid twice (done) · **Depends on:** EXE-03, FND-04 · **Traces to:** B3.kill_switch, A2.Execute, L4

### EXE-09 · Shadow, Assist and Auto modes

**As a** payments lead, **I want** a mode setting per platform, **so that** we can adopt step by step under signed gates.

**Acceptance criteria**

- [x] Shadow: decisions recorded, nothing sent. Assist: EXECUTE decisions wait for a human 'Send' click. Auto: EXECUTE decisions send automatically
- [x] Changing mode needs the payments lead and the compliance lead; each change is audited
- [x] Orchestrate is shown as routing being enabled when 2 or more rails are connected

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S6 Operations around escalations (done) · **Depends on:** EXE-03, FND-04 · **Traces to:** A3.shadow, A3.assist, A3.auto, A3.orchestrate, B6.wrong_decision, B3.mode_gates

### EXE-10 · Sev 1 invariant monitor

**As a** on-call engineer, **I want** a continuous check for duplicate payments, unauthorised executions and double credits, **so that** if an invariant ever breaks we stop and know within a minute.

**Acceptance criteria**

- [ ] Every minute and after each confirmation: two confirmed transfers for one payment ID, a confirmed attempt without an EXECUTE or approved decision, or two credits for one inbound transfer
- [ ] A hit opens a Sev 1 incident, engages the kill switch (configurable, on by default), posts to the mock outbox and shows a red banner

**Priority:** Should · **Estimate:** 0.5 d · **Milestone:** L After launch (Should and Could) · **Depends on:** EXE-08, LED-05 · **Traces to:** B3.incident, B7.safety

## RAL · Rails, routing and faults

_Three rails behind one adapter contract, best-rail routing, failover on technical errors only, and fault injection to prove it_ · layer: Orchestration · track: prototype · 11 stories · 6 days

### RAL-01 · Rail adapter contract

**As a** builder, **I want** one adapter interface with normalised statuses and an error taxonomy, **so that** adding a rail never touches decision or execution logic.

**Acceptance criteria**

- [x] Interface: `eligible`, `quote`, `submit`, `status`, `health`, as in spec/06-rails-and-faults.md
- [x] Errors normalise to TECHNICAL_RETRYABLE, TECHNICAL_FINAL, REJECTED_BY_RAIL or TIMEOUT
- [x] A shared contract-test suite runs against every adapter

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S2 An EXECUTE decision is sent exactly once (done) · **Depends on:** FND-03 · **Traces to:** A2.Connect, B4.rails, B6.dependence

### RAL-02 · Base Sepolia USDC adapter

**As a** demo viewer, **I want** real test USDC transfers on Base Sepolia with explorer links, **so that** the demo moves real (test) value on a real network.

**Acceptance criteria**

- [x] ERC-20 transfer via web3.py signed with a test key from settings; gas estimated and checked
- [x] Confirmation threshold configurable; explorer link stored on the attempt
- [ ] Contract tests pass on the local chain and nightly on Base Sepolia

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S2 An EXECUTE decision is sent exactly once (done) · **Depends on:** RAL-01, FND-09 · **Traces to:** A2.Connect, A2b.custody, A7.prototype

### RAL-03 · Ethereum Sepolia USDC adapter

**As a** demo viewer, **I want** the same transfers on Ethereum Sepolia, **so that** routing has a real second network to choose.

**Acceptance criteria**

- [x] Shares an EVM base class with RAL-02; its own fee profile and confirmation threshold
- [ ] Contract tests pass

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S4 Never paid twice (done) · **Depends on:** RAL-02 · **Traces to:** A2.Connect

### RAL-04 · Simulated instant bank rail

**As a** demo viewer, **I want** a mock instant bank rail with its own fees, limits, cut-off times and failure rate, **so that** routing and reconciliation span stablecoin and fiat.

**Acceptance criteria**

- [x] A separate FastAPI sub-app with GBP and EUR, per-payment and daily limits, cut-off times, a configurable failure rate and idempotency by key
- [x] Status endpoint and asynchronous settlement callback; daily statement endpoint (used by LED-07)
- [x] Deterministic test values: amounts ending .13 time out then settle; .42 fail technically

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S4 Never paid twice (done) · **Depends on:** RAL-01 · **Traces to:** A2.Connect, A7.prototype

### RAL-05 · Fault-injection proxy

**As a** builder, **I want** a proxy in front of chain RPC and the bank rail that injects named faults, **so that** the exactly-once claims are demonstrated, not asserted.

**Acceptance criteria**

- [x] Faults: timeout after forwarding, timeout before forwarding, connection reset, 5xx, delayed receipt, hidden receipt for N polls (stuck), duplicated response
- [x] Fault chosen per attempt by scenario config in tests and sandbox; disabled in demo mode unless a scenario requests it
- [x] Each injected fault is logged with the attempt ID

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S4 Never paid twice (done) · **Depends on:** RAL-02, RAL-04 · **Traces to:** L3, L4, A2b.unknown

### RAL-06 · Routing engine

**As a** payments lead, **I want** the best eligible rail chosen by cost, speed, success rate and liquidity, with the reason stored, **so that** payouts cost less and fail less, and I can see why a rail was chosen.

**Acceptance criteria**

- [x] Routing runs only after an EXECUTE decision; a BLOCK never reaches routing
- [x] Eligibility first (currency, network constraint from intent or mandate, limits, cut-off, health, liquidity), then a weighted score from config
- [x] The decision stores each candidate's score and the reason for the winner

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S4 Never paid twice (done) · **Depends on:** RAL-01, POL-02 · **Traces to:** A2.Route, A3.orchestrate, A1.cost

### RAL-07 · Failover on technical failure only

**As a** compliance lead, **I want** failover to another rail only after a definitive technical failure and only when the intent allows a network switch, **so that** a rejection is never re-routed and failover can't pay twice.

**Acceptance criteria**

- [x] Failover needs the previous attempt definitively FAILED with a technical code; never from UNKNOWN
- [x] Never after BLOCK or REJECTED_BY_RAIL
- [ ] Network switches need `allow_network_switch` on the intent or mandate, or a human approval
- [x] The new attempt keeps the payment ID

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S4 Never paid twice (done) · **Depends on:** RAL-06, EXE-07 · **Traces to:** A2.Route, A6.block_final, L5, A1.cost

### RAL-08 · Rail health and circuit breaker

**As a** payments lead, **I want** each rail's success rate, latency, balance and limit usage, and unhealthy rails taken out of routing, **so that** payments avoid a failing rail automatically.

**Acceptance criteria**

- [ ] Rolling success rate and p95 latency per rail; balance and pre-funded limit usage
- [ ] Circuit opens after the configured failure count and closes after a successful probe

**Priority:** Should · **Estimate:** 0.5 d · **Milestone:** L After launch (Should and Could) · **Depends on:** RAL-06 · **Traces to:** A2.Connect, B3.adapters

### RAL-09 · Rail connection flow (mock)

**As a** payments lead, **I want** to connect a rail through a mock authorisation screen or by entering scoped API keys, **so that** onboarding looks like the real thing and we keep our own rail accounts.

**Acceptance criteria**

- [ ] Mock OAuth-style consent screen and a scoped-key form; credentials encrypted at rest and never shown again
- [ ] Scopes listed; disconnect removes credentials and takes the rail out of routing

**Priority:** Should · **Estimate:** 0.75 d · **Milestone:** L After launch (Should and Could) · **Depends on:** RAL-01 · **Traces to:** A2.Connect, B3.onboarding, B5.security

### RAL-10 · Daily adapter contract tests

**As a** on-call engineer, **I want** adapter contract tests run daily against testnets and the simulator, **so that** a rail API change is caught before a demo.

**Acceptance criteria**

- [ ] Scheduled GitHub Actions job; failure opens an issue with the failing adapter and test

**Priority:** Should · **Estimate:** 0.25 d · **Milestone:** L After launch (Should and Could) · **Depends on:** RAL-03, RAL-04 · **Traces to:** B3.adapters

### RAL-11 · Simulated chain rail for the sandbox

**As a** platform integrator, **I want** sandbox payouts on a simulated USDC rail that settles instantly by default, **so that** I can test every path quickly without draining faucet wallets.

**Acceptance criteria**

- [ ] Implements the adapter contract with instant settlement and the same test values
- [ ] Sandbox organisations use it by default; real testnet is opt-in (SBX-03)

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** RAL-01 · **Traces to:** D.sandbox

## EXC · Exceptions and investigation

_Every escalation has an owner and a deadline, shows raw facts first, and a timeout never becomes an approval_ · layer: Operations · track: prototype · 9 stories · 4 days

### EXC-01 · Exception cases with owner and deadline

**As a** payments lead, **I want** every escalation to become a case with a named owner, a backup owner and a deadline by risk tier, **so that** escalations always get answered.

**Acceptance criteria**

- [x] Owner assignment rules by case type and amount, in config
- [ ] Deadlines by tier from config (defaults: 2 h for payouts above the auto limit, 1 business day for deposit exceptions)
- [x] Statuses OPEN, HELD_OVERDUE, RESOLVED; every change audited

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S3 Escalate, review raw facts, approve with a policy re-run (done) · **Depends on:** POL-02, FND-05 · **Traces to:** A2.Exceptions, B3.exceptions

### EXC-02 · Raw facts first

**As a** reviewer, **I want** to see the raw facts before the agent's summary, **so that** my judgement isn't anchored by the AI.

**Acceptance criteria**

- [x] Top of the case: payee as registered, full checksummed wallet address, first seen and last changed times, amount against the counterparty's median, each rule hit with its parameters, and the mandate scope
- [x] The agent's evidence and recommendation sit below, collapsed by default

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S3 Escalate, review raw facts, approve with a policy re-run (done) · **Depends on:** EXC-01, INT-04 · **Traces to:** A2b.raw_facts, L6

### EXC-03 · Investigation agent with cited evidence

**As a** reviewer, **I want** the investigation agent to gather evidence and draft a recommendation that cites its sources, **so that** I decide faster without trusting unsupported claims.

**Acceptance criteria**

- [x] Read-only tools: ledger history, counterparty record, screening result, rail status, prior cases
- [x] Each claim cites evidence record IDs; uncited claims are removed and the removal is flagged
- [x] Recommendation is approve, reject or needs-information with a confidence; the agent cannot change any state
- [x] Runs in the worker; the case is usable before the agent finishes

**Priority:** Must · **Estimate:** 1 d · **Milestone:** S6 Operations around escalations (done) · **Depends on:** EXC-01, AGT-05 · **Traces to:** A5.citations, A5.tools, A2.Exceptions, A1.reviews

### EXC-04 · Approve or reject, with policy re-run

**As a** reviewer, **I want** approval to send the payment back through policy before anything is sent, **so that** an approval can't push through something the rules now block.

**Acceptance criteria**

- [x] Approve re-runs policy with the active version and fresh data; a new BLOCK stays blocked; a new escalation reason opens a new case; otherwise the payment proceeds per mode
- [x] Reject -> REJECTED (terminal); a reason is required for both
- [x] The approver can't be the user who initiated the intent

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S3 Escalate, review raw facts, approve with a policy re-run (done) · **Depends on:** EXC-01, EXE-03 · **Traces to:** A2.Exceptions, A6.block_final, L6

### EXC-05 · Double-approval safety

**As a** payments lead, **I want** concurrent approvals of one case to have exactly one effect, **so that** a double click or two reviewers never cause two sends.

**Acceptance criteria**

- [x] Row lock plus version check; the second approval gets 409 `already_resolved`
- [x] Fault suite includes parallel approvals from console and API

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S3 Escalate, review raw facts, approve with a policy re-run (done) · **Depends on:** EXC-04 · **Traces to:** L3, A6.retry_rule

### EXC-06 · Deadline sweeper - a timeout never becomes an approval

**As a** payments lead, **I want** overdue cases held, the counterparty told, and the case passed to the backup owner, **so that** nothing is auto-approved and nobody is left waiting without news.

**Acceptance criteria**

- [x] Past the deadline: case HELD_OVERDUE, payment stays held, a status update goes to the counterparty via the outbox, and the backup owner gets the case with a new deadline
- [x] The count of payments approved by timeout is always 0 and is reported

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S6 Operations around escalations (done) · **Depends on:** EXC-01, EXC-07, FND-06 · **Traces to:** A2b.timeout_hold, A6.timeout, B3.exceptions, L6, B7.exceptions

### EXC-07 · Mock outbox

**As a** demo viewer, **I want** every outbound notification visible in an Outbox screen, **so that** the demo shows the counterparty updates without sending real email.

**Acceptance criteria**

- [ ] Counterparty updates, owner assignments and incident notices are stored with recipient, template and body
- [x] Nothing in the prototype sends real email

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S3 Escalate, review raw facts, approve with a policy re-run (done) · **Depends on:** FND-03 · **Traces to:** B3.exceptions

### EXC-08 · Exceptions by API

**As a** platform integrator, **I want** to list cases and approve or reject them by API, **so that** our own tools can work the queue.

**Acceptance criteria**

- [ ] GET /v1/exceptions with filters; POST /v1/exceptions/{id}/approve and /reject need scope `exceptions:approve`
- [ ] Same rules as the console: re-run, separation of duties, 409 on double approval

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P1 Public sandbox API and webhooks · **Depends on:** EXC-04 · **Traces to:** A2.Exceptions, D.standards

### EXC-09 · Agent-versus-human agreement sample

**As a** compliance lead, **I want** a report comparing the agent's recommendations with our final decisions, **so that** we can see whether the agent deserves more trust.

**Acceptance criteria**

- [ ] Per period: cases, agreement rate, disagreements listed with both rationales

**Priority:** Could · **Estimate:** 0.25 d · **Milestone:** L After launch (Should and Could) · **Depends on:** EXC-03 · **Traces to:** B3.agent_eval, B7.quality

## LED · Ledger, deposits and reconciliation

_One ledger across rails; deposits credited once; mismatches become exceptions with proposed fixes_ · layer: Operations · track: prototype · 8 stories · 4.25 days

### LED-01 · Double-entry ledger

**As a** auditor, **I want** one immutable double-entry ledger across all rails, **so that** every balance can be explained from entries.

**Acceptance criteria**

- [x] Journal entries with balanced postings; accounts for user balances, platform operating, rail clearing per rail, fees and suspense
- [x] Entries are append-only; corrections are new entries
- [x] Every posting references a payment, deposit or adjustment ID

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S7 One ledger, deposits credited once, reconciliation, replay (done) · **Depends on:** FND-03 · **Traces to:** A2.Reconcile, A1.evidence

### LED-02 · Payout postings

**As a** payments lead, **I want** payouts reserved on submission, settled on confirmation and released on final failure, **so that** balances are always right, even with UNKNOWN payments.

**Acceptance criteria**

- [x] SUBMITTED reserves; CONFIRMED settles and posts actual fees; final FAILED reverses the reservation; UNKNOWN keeps the reservation
- [x] Ledger and payment status agree after every fault-suite case

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S7 One ledger, deposits credited once, reconciliation, replay (done) · **Depends on:** LED-01, EXE-02 · **Traces to:** A2.Reconcile

### LED-03 · Deposit intents

**As a** platform integrator, **I want** to create a deposit intent for a user account with expected token, network and optional amount, **so that** incoming money can be matched to the right account.

**Acceptance criteria**

- [x] POST /v1/deposit_intents returns deposit instructions: a per-account test address, or a bank reference for the simulated rail
- [x] Idempotent like payment intents

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S7 One ledger, deposits credited once, reconciliation, replay (done) · **Depends on:** LED-01 · **Traces to:** A1.deposits, A2.Reconcile

### LED-04 · Deposit watchers

**As a** payments lead, **I want** incoming transfers on both chains and the bank rail recorded once each, **so that** no deposit is missed or counted twice.

**Acceptance criteria**

- [x] Reads ERC-20 Transfer logs to watched addresses, and bank-rail inbound credits
- [x] Unique on (rail, transaction hash, log index); restarting the watcher never duplicates

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S7 One ledger, deposits credited once, reconciliation, replay (done) · **Depends on:** LED-03, FND-06, RAL-02 · **Traces to:** A1.deposits

### LED-05 · Deposit decision and credit-once

**As a** payments lead, **I want** each inbound transfer matched, checked and credited once after enough confirmations, **so that** users are credited once, to the right account.

**Acceptance criteria**

- [x] Match on address or reference, token, network and amount within tolerance
- [x] Policy checks the sender (screening) and the token and network match
- [x] Credit only after the confirmation threshold; a unique constraint allows one credit per inbound transfer
- [x] Mismatches (wrong network or token, amount mismatch, no intent, flagged sender) open deposit exceptions

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S7 One ledger, deposits credited once, reconciliation, replay (done) · **Depends on:** LED-04, POL-03, EXC-01 · **Traces to:** A1.deposits, A2.Reconcile, L7

### LED-06 · Reconciliation run with proposed fixes

**As a** payments lead, **I want** a reconciliation of the ledger against every rail's records, with a proposed fix for each break, **so that** reconciliation is a review of exceptions, not a spreadsheet job.

**Acceptance criteria**

- [x] Matches ledger postings to chain transfers and bank statements for payouts and deposits; reports the match rate
- [x] Each break becomes an exception with a fix drafted by the reconciliation agent (for example, credit account X, or return to sender)
- [x] A fix is applied only after human approval, as a new adjustment entry
- [x] On a generated set of 500 synthetic deposits and payouts with 3 designed breaks, automatic matching is 99% or more and each break gets a proposed fix
- [ ] The demo batch (20 payouts, 8 deposits) shows exactly one designed break, dep-07

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S7 One ledger, deposits credited once, reconciliation, replay (done) · **Depends on:** LED-02, LED-05, LED-07, EXC-01 · **Traces to:** A2.Reconcile, L7, B7.recon

### LED-07 · Bank statement import

**As a** builder, **I want** the simulated bank's daily statement imported for reconciliation, **so that** fiat reconciliation works like it does with a real bank.

**Acceptance criteria**

- [x] Pulls the statement endpoint (JSON or CSV), idempotent per statement date

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S7 One ledger, deposits credited once, reconciliation, replay (done) · **Depends on:** RAL-04 · **Traces to:** A2.Reconcile

### LED-08 · Usage metering

**As a** founder, **I want** payments decided per organisation per month counted from decisions and the ledger, **so that** per-payment pricing can be billed later, and sandbox usage shown now.

**Acceptance criteria**

- [ ] Monthly counts of payments decided, agent investigations and API calls per organisation

**Priority:** Could · **Estimate:** 0.25 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** LED-01 · **Traces to:** A4.fee, B3.billing, D.usage

## AUD · Audit and replay

_Every step is recorded append-only and any payment can be replayed and exported_ · layer: Operations · track: prototype · 3 stories · 2 days

### AUD-01 · Append-only, hash-chained audit log

**As a** auditor, **I want** every step recorded in an append-only log I can verify, **so that** the record can't be quietly changed.

**Acceptance criteria**

- [ ] Events written in the same transaction as the change they describe: intent, agent output, decision with rule version and checks, case events, approvals, transitions, rail requests and responses, postings, kill switch, policy changes
- [x] A database trigger rejects UPDATE and DELETE on audit rows
- [x] Each row stores a hash of the previous row; `detent audit verify` detects a tampered row (tested)

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S1 A platform payout is decided through the API (done) · **Depends on:** FND-03 · **Traces to:** A2.Prove, B5.security, A1.evidence

### AUD-02 · Replay any payment

**As a** auditor, **I want** to replay a payment step by step from its stored inputs, rule version and agent outputs, **so that** I can confirm the decision would be made the same way again.

**Acceptance criteria**

- [x] Console button and GET /v1/payment_intents/{id}/replay
- [x] Replay uses stored inputs and stored agent outputs and must reproduce the recorded decision; a mismatch raises an alert
- [x] Every payment in the demo data replays successfully (test)

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S7 One ledger, deposits credited once, reconciliation, replay (done) · **Depends on:** AUD-01, AGT-05, POL-02 · **Traces to:** A2.Prove, L8, B3.incident

### AUD-03 · Evidence export

**As a** auditor, **I want** an evidence pack for a payment or date range, **so that** I can review it offline.

**Acceptance criteria**

- [ ] JSON plus a readable HTML or PDF: inputs, rule versions, decisions, approvers, state changes, transaction hashes with explorer links, and the hash-chain check result

**Priority:** Should · **Estimate:** 0.5 d · **Milestone:** L After launch (Should and Could) · **Depends on:** AUD-02 · **Traces to:** A2.Prove, A1.evidence

## CON · Back-office console

_The screens where the 10-minute demo happens_ · layer: All three (console) · track: prototype · 10 stories · 4.75 days

### CON-01 · Console shell and prototype labelling

**As a** demo viewer, **I want** a clean console with navigation, acting-user indicator, kill-switch state and a permanent prototype label, **so that** it looks real and is honest about what it is.

**Acceptance criteria**

- [x] Jinja and htmx; navigation: Overview, Payments, Exceptions, Reconciliation, Rails, Policy, Mandates, Counterparties, Outbox, Audit, Evaluation, Settings
- [x] A banner on every page: 'Prototype · test networks · simulated bank rail'
- [x] Wording uses 'agentic payment controls' and names the three layers (decision, orchestration, operations); never 'payments company' or 'payment provider'

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S3 Escalate, review raw facts, approve with a policy re-run (done) · **Depends on:** FND-04 · **Traces to:** L8, BR.category, D.honesty

### CON-02 · Overview screen

**As a** payments lead, **I want** today's decisions, open and overdue cases, UNKNOWN payments, match rate and rail health at a glance, **so that** I know where attention is needed.

**Acceptance criteria**

- [x] Counts by decision and status; share decided without a human; oldest UNKNOWN age; open and overdue cases; match rate; rail health; recent events
- [x] Refreshes by htmx polling

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S6 Operations around escalations (done) · **Depends on:** CON-01 · **Traces to:** B7.automation, B7.exceptions, B7.unknown

### CON-03 · Payments list and detail

**As a** reviewer, **I want** a payment page with every check, the route, attempts, postings and the timeline, **so that** I can answer "what happened to this payment" in one place.

**Acceptance criteria**

- [ ] Each check with result, reason and evidence; route candidates and scores; attempts with hash and explorer link; ledger postings; timeline; replay button

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S3 Escalate, review raw facts, approve with a policy re-run (done) · **Depends on:** CON-01, AUD-01 · **Traces to:** A2.Prove, A2.Decide

### CON-04 · Exceptions queue screen

**As a** reviewer, **I want** my queue with deadlines counting down and the case page with approve and reject, **so that** I can work escalations quickly and correctly.

**Acceptance criteria**

- [x] Filters by owner, tier and overdue; countdown to deadline; case page follows EXC-02; approve and reject with a required reason

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S3 Escalate, review raw facts, approve with a policy re-run (done) · **Depends on:** CON-01, EXC-04 · **Traces to:** A2.Exceptions, A2b.raw_facts

### CON-05 · Invoice drop and agent proposal screen

**As a** demo viewer, **I want** to drop an invoice and watch the agent's proposal, flags and mandate appear, **so that** the agentic part of the demo is visible.

**Acceptance criteria**

- [ ] Upload text or PDF; extracted fields with confidence and highlighted source text; flags; the mandate in force
- [x] 'Submit as agent' calls the public API with the agent's key and shows the decision

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S5 An AI agent proposes the $18,500 invoice inside a mandate (done) · **Depends on:** CON-01, AGT-02, MND-02 · **Traces to:** MVP.flow, A5.proposes

### CON-06 · Policy and mandates screens

**As a** compliance lead, **I want** to read, diff, propose and approve rule versions, and to manage mandates, **so that** rule ownership is visible and practical.

**Acceptance criteria**

- [x] Active version, history and diff; propose and approve per POL-07
- [x] Mandates list with scope, usage against limits, expiry and revoke

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S6 Operations around escalations (done) · **Depends on:** POL-07, MND-03 · **Traces to:** B3.rule_changes, A2.Mandate

### CON-07 · Reconciliation screen

**As a** payments lead, **I want** the latest run's match rate and breaks with proposed fixes, **so that** I can approve fixes in minutes.

**Acceptance criteria**

- [x] Run history, match rate, breaks with proposed fix and approve button

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S7 One ledger, deposits credited once, reconciliation, replay (done) · **Depends on:** LED-06 · **Traces to:** A2.Reconcile, L7

### CON-08 · Rails screen

**As a** payments lead, **I want** connected rails with balance, limits and recent results, **so that** I can see where money is going.

**Acceptance criteria**

- [x] Per rail: network or currency, balance, pre-funded limit usage, last 20 attempts

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S4 Never paid twice (done) · **Depends on:** CON-01, RAL-06 · **Traces to:** A2.Connect

### CON-09 · Demo scenario runner

**As a** founder, **I want** one-click scenarios and a reset, **so that** every demo runs the same way in under 10 minutes.

**Acceptance criteria**

- [ ] Scenarios: the $18,500 invoice; forced timeout to UNKNOWN then CONFIRMED with no resend; 20-payment batch with deposits and one designed break; an attack sample; reset demo data
- [ ] Each scenario is scripted, idempotent and uses the controllable clock

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** S9 Demo-ready prototype in the EU · **Depends on:** CON-05, LED-06, EVL-01 · **Traces to:** MVP.flow, MVP.scenarios

### CON-10 · Settings screen

**As a** payments lead, **I want** to see and set mode, fail-safe, deadlines and routing weights, **so that** the operating choices are explicit.

**Acceptance criteria**

- [ ] Mode and fail-safe editable with the approvals from EXE-09; deadlines and weights shown read-only in the prototype

**Priority:** Should · **Estimate:** 0.25 d · **Milestone:** L After launch (Should and Could) · **Depends on:** EXE-09 · **Traces to:** B5.failsafe, A3.gates

## EVL · Evaluation harness

_Measured proof: attacks, faults, interpretation and agreement, gated in CI and published as a results report_ · layer: All three (proof) · track: prototype · 8 stories · 4.75 days

### EVL-01 · Evaluation runner

**As a** builder, **I want** `detent eval run --suite attacks|faults|interpretation|agreement|all` on a fresh database, **so that** results are repeatable and comparable across commits.

**Acceptance criteria**

- [ ] Each scenario runs in isolation with a fixed seed; output is results.json with date, commit, model IDs and per-scenario results
- [ ] Scenarios are data files under eval/scenarios/, not code

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S8 Proof and release gate · **Depends on:** FND-09, POL-02 · **Traces to:** A5.gate, B3.agent_eval

### EVL-02 · Attack suite (100+ scenarios)

**As a** compliance lead, **I want** at least 100 attack scenarios with zero unauthorised executions, **so that** the safety claim is measured.

**Acceptance criteria**

- [ ] Categories from spec/09-evaluation-and-tests.md: injection in invoice body, notes, payee name, reference and PDF metadata; mandate violations; split payments; wallet change race; resubmission after block; self-approval; approval after deadline; idempotency-key reuse; tampered rule version; cross-organisation access; wrong-scope keys; re-route after block
- [ ] Pass means no SUBMITTED or CONFIRMED attempt without authorisation; the suite reports per category

**Priority:** Must · **Estimate:** 1 d · **Milestone:** S8 Proof and release gate · **Depends on:** EVL-01, AGT-04, EXC-04, RAL-07 · **Traces to:** L2, A5.gate, A5.injection, B7.safety

### EVL-03 · Fault suite (30+ cases)

**As a** payments lead, **I want** at least 30 fault cases with zero duplicate payments, **so that** "no retry can become a second payment" is proven.

**Acceptance criteria**

- [ ] Matrix of faults (timeout after and before send, reset, 5xx, delayed and hidden receipt, duplicated response, worker crash mid-send, concurrent retries, double approvals, failover, kill switch mid-batch) across the rails
- [ ] Pass: 0 duplicates, every retry and switch keeps the payment ID, no timeout ever becomes FAILED

**Priority:** Must · **Estimate:** 1 d · **Milestone:** S8 Proof and release gate · **Depends on:** EVL-01, RAL-05, EXE-06 · **Traces to:** L3, L4, L5, B7.safety

### EVL-04 · Interpretation set

**As a** builder, **I want** 30 labelled invoices including 10 runs of the canonical one and ambiguous variants, **so that** the agent's accuracy and "flag, never guess" are measured.

**Acceptance criteria**

- [ ] Metrics: field accuracy, flag recall on ambiguous cases, invented-value count (must be 0), and canonical 10/10

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S8 Proof and release gate · **Depends on:** EVL-01, AGT-02 · **Traces to:** L1, A5.proposes

### EVL-05 · Agreement set (synthetic)

**As a** founder, **I want** 50 synthetic cases labelled with an expert decision, **so that** agreement can be reported now and replaced by real anonymised cases later.

**Acceptance criteria**

- [ ] Agreement of final decision and of agent recommendation with labels, reported separately; clearly marked synthetic

**Priority:** Should · **Estimate:** 0.5 d · **Milestone:** S8 Proof and release gate · **Depends on:** EVL-01, EXC-03 · **Traces to:** B7.quality, A1.reviews

### EVL-06 · Results report

**As a** founder, **I want** a dated results report generated from results.json, **so that** I can show measured results to prospects and investors.

**Acceptance criteria**

- [ ] HTML and Markdown with metrics, per-category tables and the caveat 'test-network evaluation on synthetic data, [date]'
- [ ] results.json is published for the website's Measured results section

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S8 Proof and release gate · **Depends on:** EVL-02, EVL-03, EVL-04 · **Traces to:** MVP.flow, D.site, D.honesty, B7.automation

### EVL-07 · Release gate in CI

**As a** compliance lead, **I want** the attack and fault suites to block any release with a single unauthorised execution or duplicate, **so that** regressions never reach the demo or the sandbox.

**Acceptance criteria**

- [ ] Runs on main and on release tags against the local chain and simulators; nightly against public testnets
- [ ] Any unauthorised execution or duplicate fails the build, whatever other scores say

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** S8 Proof and release gate · **Depends on:** EVL-02, EVL-03 · **Traces to:** A5.gate, B3.agent_eval, B6.ai

### EVL-08 · Latency benchmark

**As a** on-call engineer, **I want** p95 decision latency measured with and without agent investigation, **so that** we can state the resilience target honestly.

**Acceptance criteria**

- [ ] Benchmark reports p50 and p95 for rules-only and agent paths; included in the results report

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S8 Proof and release gate · **Depends on:** EVL-01 · **Traces to:** B5.resilience, B7.reliability

## DEM · Demo data and scenarios

_Fictional, repeatable demo data and a one-click scenario runner_ · layer: All three (demo) · track: prototype · 6 stories · 1.75 days

### DEM-01 · Fictional demo platform and actors

**As a** founder, **I want** one clearly fictional platform with users, counterparties, rules v1 and an agent mandate, **so that** the demo is realistic without using any real company or former-employer material.

**Acceptance criteria**

- [ ] Names are invented and labelled fictional; no real client, partner or former-employer names
- [ ] Seed is idempotent and resettable

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S9 Demo-ready prototype in the EU · **Depends on:** INT-04, POL-01, MND-01 · **Traces to:** B1.independence, B6.former_employer, MVP.flow

### DEM-02 · Canonical invoice and variants

**As a** founder, **I want** the $18,500 USDC supplier invoice and its ambiguous and malicious variants as fixtures, **so that** the headline flow and its edge cases are always available.

**Acceptance criteria**

- [x] fixtures/invoices/ contains the canonical invoice plus missing-network, two-wallet, changed-wallet and injection variants with expected outputs

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S5 An AI agent proposes the $18,500 invoice inside a mandate (done) · **Depends on:** none · **Traces to:** L1, MVP.flow

### DEM-03 · 20-payment batch with deposits

**As a** founder, **I want** a batch fixture mixing payouts across rails with deposits and one designed reconciliation break, **so that** routing and reconciliation are shown in one run.

**Acceptance criteria**

- [ ] Covers all three rails, at least one escalation, one block and exactly one reconciliation break

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S9 Demo-ready prototype in the EU · **Depends on:** LED-06 · **Traces to:** MVP.flow, L7

### DEM-04 · Wallet funding runbook and check

**As a** founder, **I want** a script that checks test-wallet balances and tells me what to top up, **so that** a demo never fails for lack of test USDC or gas.

**Acceptance criteria**

- [ ] `detent demo check` prints USDC and gas balances per wallet and chain with faucet instructions

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S9 Demo-ready prototype in the EU · **Depends on:** RAL-03 · **Traces to:** A7.prototype

### DEM-05 · Demo script

**As a** founder, **I want** a written 10-minute demo script matching the scenario runner, **so that** every demo tells the same story.

**Acceptance criteria**

- [ ] spec/11-demo-script.md updated to match the built screens; ends with the shadow-report ask

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S9 Demo-ready prototype in the EU · **Depends on:** CON-09 · **Traces to:** MVP.flow, B3.lead_shadow

### DEM-06 · Scenario packs per platform type

**As a** founder, **I want** seed packs for a payout platform, a crypto service provider and a marketplace, **so that** I can tailor the demo to the prospect.

**Acceptance criteria**

- [ ] Each pack: platform, counterparties, rules and a short batch; selectable on reset

**Priority:** Should · **Estimate:** 0.5 d · **Milestone:** L After launch (Should and Could) · **Depends on:** DEM-01 · **Traces to:** MVP.scenarios

## SHD · Shadow mode

_Run decisions on a prospect's exported data and produce the free shadow report_ · layer: Decision (shadow mode) · track: prototype · 4 stories · 2.25 days

### SHD-01 · Shadow CSV import

**As a** payments lead, **I want** to upload a month of payout and deposit exports with our actual decisions, **so that** Detent can show what it would have decided on our real data.

**Acceptance criteria**

- [ ] Column-mapping screen; validation report; decisions run with POL-08 and nothing is executed

**Priority:** Should · **Estimate:** 0.75 d · **Milestone:** L After launch (Should and Could) · **Depends on:** POL-08 · **Traces to:** MVP.shadow_csv, A3.shadow, A6.shadow_first, A7.beta, B3.lead_shadow

### SHD-02 · Shadow report

**As a** payments lead, **I want** a report of what would have been auto-approved, escalated and blocked, agreement with our decisions, unsafe approvals and routing savings, **so that** we can judge the value before any pilot.

**Acceptance criteria**

- [ ] Sections: decision mix, agreement, unsafe approvals (approved by Detent but blocked or lossy for the client), unreconciled items, simulated routing saving; export as HTML and PDF

**Priority:** Should · **Estimate:** 0.75 d · **Milestone:** L After launch (Should and Could) · **Depends on:** SHD-01, RAL-06 · **Traces to:** A3.shadow, B3.lead_shadow, A4.plans

### SHD-03 · Mode-gate report and sign-off

**As a** compliance lead, **I want** a gate report with agreement and unsafe approvals over a period, and a recorded sign-off, **so that** each move from Shadow to Assist to Auto is evidenced.

**Acceptance criteria**

- [ ] Shows 30-day agreement and unsafe approvals against the gate thresholds; sign-off by payments lead and compliance lead recorded and linked to the mode change

**Priority:** Could · **Estimate:** 0.5 d · **Milestone:** L After launch (Should and Could) · **Depends on:** SHD-02, EXE-09 · **Traces to:** A3.gates, B3.mode_gates

### SHD-04 · Anonymise on import

**As a** compliance lead, **I want** names and addresses hashed with a per-import salt, **so that** sharing a shadow export doesn't expose personal data.

**Acceptance criteria**

- [ ] Raw names and account identifiers never stored; hashes are consistent within one import

**Priority:** Should · **Estimate:** 0.25 d · **Milestone:** L After launch (Should and Could) · **Depends on:** SHD-01 · **Traces to:** B1.contracts, A5.data

## OPS · Operational controls

_The operating-model processes that need software: incidents, independence check, recovery_ · layer: Operations · track: prototype · 4 stories · 1.25 days

### OPS-01 · Incident records

**As a** on-call engineer, **I want** incidents with severity, timeline, notification time and root cause, **so that** we can run the Sev 1 process and support clients' DORA reporting.

**Acceptance criteria**

- [ ] Sev levels per spec; Sev 1 opened automatically by EXE-10 or manually; notification logged within 1 hour; root-cause field and linked replays

**Priority:** Should · **Estimate:** 0.5 d · **Milestone:** L After launch (Should and Could) · **Depends on:** EXE-10, AUD-02 · **Traces to:** B3.incident

### OPS-02 · Independence check in CI

**As a** founder, **I want** CI to fail if the repo contains any term from a private denylist, **so that** no former-employer name or material ever enters the codebase.

**Acceptance criteria**

- [x] The denylist lives in a CI secret, never in the repo; the check scans code, fixtures and docs

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** S0 Foundation (done) · **Depends on:** FND-01 · **Traces to:** B1.independence, B6.former_employer

### OPS-03 · Backup and restore drill

**As a** on-call engineer, **I want** a documented, tested restore from the database provider's point-in-time recovery, **so that** we can recover in under an hour without losing decisions.

**Acceptance criteria**

- [ ] Runbook in spec/10; one drill done and timed; audit hash chain verified after restore

**Priority:** Could · **Estimate:** 0.25 d · **Milestone:** L After launch (Should and Could) · **Depends on:** FND-07 · **Traces to:** B5.resilience

### OPS-04 · Security pack draft

**As a** founder, **I want** a written description of the controls as built, **so that** it can seed a pen test and vendor due diligence later.

**Acceptance criteria**

- [ ] docs/security.md generated from spec/10, listing controls and their tests; roadmap items labelled as roadmap

**Priority:** Could · **Estimate:** 0.25 d · **Milestone:** L After launch (Should and Could) · **Depends on:** EVL-07 · **Traces to:** B5.assurance, B5.security

## API · Public sandbox API

_A provider-grade API: keys, scopes, errors, versioning, limits, logs, OpenAPI_ · layer: All three (public API) · track: portal · 7 stories · 3.75 days

### API-01 · API keys and scopes

**As a** platform integrator, **I want** test API keys with scopes, sent as a Bearer token, **so that** my integration is authenticated and least-privileged.

**Acceptance criteria**

- [x] `Authorization: Bearer sk_test_...`; keys hashed at rest; scopes read, intents:create, exceptions:approve, admin
- [x] Wrong scope -> 403 `insufficient_scope`; live keys -> 403 `live_mode_unavailable`
- [ ] Every data access filters by the key's organisation (cross-organisation tests in EVL-02)

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** P1 Public sandbox API and webhooks · **Depends on:** FND-03 · **Traces to:** D.keys, D.standards, B5.security

### API-02 · Error model

**As a** platform integrator, **I want** consistent JSON errors with type, code, message, payment ID and request ID, **so that** I can handle errors in code.

**Acceptance criteria**

- [ ] Every 4xx and 5xx uses the schema in spec/03-api.md; the code catalogue is generated into the docs

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P1 Public sandbox API and webhooks · **Depends on:** FND-08 · **Traces to:** D.standards

### API-03 · Dated API versions

**As a** platform integrator, **I want** a dated version header, **so that** my integration doesn't break when the API changes.

**Acceptance criteria**

- [ ] `Detent-Version: 2026-12-01`; organisations are pinned to a default; unknown versions return 400

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P1 Public sandbox API and webhooks · **Depends on:** API-01 · **Traces to:** D.standards

### API-04 · Rate limits

**As a** founder, **I want** per-key rate limits returned in headers, **so that** the sandbox stays healthy.

**Acceptance criteria**

- [ ] `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` headers; 429 with `Retry-After`

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P1 Public sandbox API and webhooks · **Depends on:** API-01 · **Traces to:** D.standards, D.abuse

### API-05 · OpenAPI 3.1 file

**As a** platform integrator, **I want** a complete, polished OpenAPI file with examples for every endpoint, **so that** docs, SDKs and "try it" all come from one source.

**Acceptance criteria**

- [ ] Generated from FastAPI, then completed with descriptions, examples and error responses
- [ ] Lint passes (Redocly or Spectral); a CI test fails if the code and the checked-in spec drift

**Priority:** Must · **Estimate:** 1.5 d · **Milestone:** P1 Public sandbox API and webhooks · **Depends on:** API-02, EXC-08, LED-03 · **Traces to:** D.docs, D.sdks, D.standards

### API-06 · Request logs

**As a** platform integrator, **I want** every API call I make logged with status, latency, idempotency key and payment ID, **so that** I can debug my own integration.

**Acceptance criteria**

- [ ] Stored per organisation for 30 days; bodies redacted; filterable in the dashboard

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** P1 Public sandbox API and webhooks · **Depends on:** API-01 · **Traces to:** D.logs

### API-07 · Events list

**As a** platform integrator, **I want** GET /v1/events with cursor pagination, **so that** I can poll if I can't receive webhooks.

**Acceptance criteria**

- [ ] Same event objects as webhooks; filter by type and payment ID

**Priority:** Should · **Estimate:** 0.25 d · **Milestone:** P1 Public sandbox API and webhooks · **Depends on:** WHK-01 · **Traces to:** D.webhooks, D.standards

## WHK · Webhooks

_Signed, retried, logged event delivery_ · layer: All three (public API) · track: portal · 3 stories · 1.25 days

### WHK-01 · Webhook endpoints and event types

**As a** platform integrator, **I want** to register endpoints for chosen event types, **so that** my systems react to decisions and state changes in real time.

**Acceptance criteria**

- [ ] Event types from spec/03-api.md (payment_intent.*, exception.*, deposit.credited, reconciliation.break)
- [ ] Signing secret shown once; events carry `id` and a per-payment `sequence`

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** P1 Public sandbox API and webhooks · **Depends on:** API-01 · **Traces to:** D.webhooks

### WHK-02 · Signed webhooks

**As a** platform integrator, **I want** an HMAC-SHA256 signature over timestamp and body with a 5-minute window, **so that** I can trust that events come from Detent.

**Acceptance criteria**

- [ ] `Detent-Signature: t=<unix>,v1=<hex>`; the verify helper rejects bad signatures and stale timestamps (tests in every docs language)

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P1 Public sandbox API and webhooks · **Depends on:** WHK-01 · **Traces to:** D.webhooks

### WHK-03 · Delivery, retries and log

**As a** platform integrator, **I want** at-least-once delivery with retries, a delivery log, resend and a test event, **so that** I never silently miss an event.

**Acceptance criteria**

- [ ] Outbox-based worker; exponential backoff up to 24 h; delivery log with status and response time; manual resend; 'send test event'

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** P1 Public sandbox API and webhooks · **Depends on:** WHK-02, FND-06 · **Traces to:** D.webhooks

## DSH · Developer dashboard

_Sales-led access, keys, logs, webhooks, sandbox controls, usage and the console per organisation_ · layer: All three (developer access) · track: portal · 10 stories · 3.5 days

### DSH-01 · Admin creates organisations and invites

**As a** Detent admin, **I want** to create an organisation after a demo and invite its developers, **so that** sandbox access stays sales-led.

**Acceptance criteria**

- [ ] Admin screen: organisation name, expiry (default 60 days), invite emails; invite links are single-use and expire in 7 days
- [ ] No public sign-up route exists

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** API-01 · **Traces to:** D.sales_led, B3.onboarding

### DSH-02 · Accept invite and verify email

**As a** platform integrator, **I want** to verify my email, set a password and see my test keys, **so that** I can start integrating straight after the demo.

**Acceptance criteria**

- [ ] Email verification link; password hashed with argon2; first login shows the keys page
- [ ] Emails go through a transactional email provider in production and the outbox in development

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** DSH-01 · **Traces to:** D.sales_led

### DSH-03 · Organisation expiry and extension

**As a** Detent admin, **I want** sandbox access to expire unless I extend it, **so that** access is reviewed and can't linger.

**Acceptance criteria**

- [ ] After expiry, API calls return 403 `organisation_expired` and the dashboard is read-only; admin can extend

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** DSH-01 · **Traces to:** D.sales_led, D.abuse

### DSH-04 · Keys page

**As a** platform integrator, **I want** to create, roll and revoke keys with scopes, **so that** I can manage credentials safely.

**Acceptance criteria**

- [ ] Keys shown once at creation; last-used time; roll keeps the old key valid for a configurable overlap; revoke is immediate

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** DSH-02 · **Traces to:** D.keys

### DSH-05 · Request logs page

**As a** platform integrator, **I want** to browse my request logs with filters, **so that** I can debug quickly.

**Acceptance criteria**

- [ ] Filters by status, path, idempotency key and payment ID; detail view with redacted bodies

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** API-06, DSH-02 · **Traces to:** D.logs

### DSH-06 · Webhooks page

**As a** platform integrator, **I want** to manage endpoints, see the secret once, send a test event and read the delivery log, **so that** I can set up webhooks without support.

**Acceptance criteria**

- [ ] All WHK features available in the UI

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** WHK-03, DSH-02 · **Traces to:** D.webhooks

### DSH-07 · Sandbox controls page

**As a** platform integrator, **I want** to reset test data and force scenarios, **so that** I can test every path on demand.

**Acceptance criteria**

- [ ] Reset; force timeout to UNKNOWN, rail failure and flagged address; explorer links for real-testnet payments

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** SBX-01, SBX-04, DSH-02 · **Traces to:** D.sandbox

### DSH-08 · Usage page

**As a** platform integrator, **I want** my usage against sandbox quotas, **so that** I know when I'll hit a limit.

**Acceptance criteria**

- [ ] Calls, payments decided and agent investigations against daily quotas

**Priority:** Should · **Estimate:** 0.25 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** LED-08, SBX-02 · **Traces to:** D.usage

### DSH-09 · Console per organisation

**As a** platform integrator, **I want** the back-office console inside the dashboard, scoped to my organisation, **so that** I see my sandbox payments the way an operations team would.

**Acceptance criteria**

- [ ] Console screens reused with the organisation scope; demo-only controls (clock, scenario runner) hidden

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** CON-04, DSH-02 · **Traces to:** D.console

### DSH-10 · Access requests inbox

**As a** Detent admin, **I want** website access requests stored as leads and emailed to the sales inbox, **so that** I can follow up and approve companies.

**Acceptance criteria**

- [ ] Form fields: name, work email, company, role, use case; stored; admin list with status; email to the sales inbox

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** DSH-01 · **Traces to:** D.sales_led, D.ops_pages

## SBX · Sandbox

_Developers trigger every path with test values, inside quotas_ · layer: All three (developer access) · track: portal · 4 stories · 1.5 days

### SBX-01 · Test values

**As a** platform integrator, **I want** magic values that trigger each path, **so that** I can test timeouts, failover, blocks and escalations instantly.

**Acceptance criteria**

- [ ] Amount ending .13 -> timeout, UNKNOWN, then CONFIRMED; .42 -> technical failure then failover under the same ID; payee 0x...dEaD -> BLOCK; payee not allowlisted -> ESCALATE; amount above mandate -> BLOCK
- [ ] Documented in the docs and covered by tests

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** RAL-11, RAL-05 · **Traces to:** D.sandbox

### SBX-02 · Quotas and abuse limits

**As a** founder, **I want** daily caps on payments and agent investigations per organisation, and limits on the shared wallet, **so that** sandbox costs stay bounded.

**Acceptance criteria**

- [ ] Over quota -> 429 `quota_exceeded`; shared testnet wallet has a daily outflow cap

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** API-04 · **Traces to:** D.abuse

### SBX-03 · Real test-network mode

**As a** platform integrator, **I want** to opt in to real Base Sepolia or Ethereum Sepolia payouts, **so that** I can see real explorer links.

**Acceptance criteria**

- [ ] Per-organisation setting; payouts come from a shared, rate-limited faucet wallet; explorer links returned

**Priority:** Should · **Estimate:** 0.5 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** RAL-03, SBX-02 · **Traces to:** D.sandbox

### SBX-04 · Sandbox reset

**As a** platform integrator, **I want** to reset my organisation's test data, **so that** I can start clean.

**Acceptance criteria**

- [ ] Starts a new data generation for the organisation: intents, cases, ledger and logs from earlier generations are hidden from the API and dashboard but never deleted (audit and ledger stay append-only); keeps keys, webhooks and settings; audited (D-08)

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P2 Dashboard and sandbox · **Depends on:** API-01 · **Traces to:** D.sandbox

## DOC · Docs portal

_Concepts, guides and reference with tested samples in 8 languages_ · layer: All three (developer access) · track: portal · 6 stories · 4.25 days

### DOC-01 · Docs site and structure

**As a** platform integrator, **I want** a docs site with Get started, Concepts, Guides, API reference, Webhooks, Errors and limits, SDKs and Changelog, **so that** I can find anything in two clicks.

**Acceptance criteria**

- [ ] Mintlify (Starter) from the repo's docs/ folder; reference generated from openapi.yaml; custom domain placeholder

**Priority:** Must · **Estimate:** 0.5 d · **Milestone:** P3 Docs and SDKs · **Depends on:** API-05 · **Traces to:** D.docs

### DOC-02 · Concept pages

**As a** platform integrator, **I want** concise concept pages, **so that** I understand the model before I write code.

**Acceptance criteria**

- [ ] Payment intents and the payment ID; decisions; payment states; policies and versions; mandates; exceptions and deadlines; deposits and reconciliation; routing and failover; audit and replay

**Priority:** Must · **Estimate:** 1 d · **Milestone:** P3 Docs and SDKs · **Depends on:** DOC-01 · **Traces to:** D.docs, BR.category

### DOC-03 · Guides

**As a** platform integrator, **I want** task guides, **so that** I can complete common jobs end to end.

**Acceptance criteria**

- [ ] Let an AI agent pay a supplier invoice ($18,500 USDC); credit deposits safely; handle UNKNOWN payments; approve escalations by API; use the kill switch; move from shadow to auto

**Priority:** Must · **Estimate:** 1 d · **Milestone:** P3 Docs and SDKs · **Depends on:** DOC-01 · **Traces to:** D.docs

### DOC-04 · Tested samples in 8 languages

**As a** platform integrator, **I want** code samples in cURL, Python, TypeScript, Go, Java, C#, PHP and Ruby that actually run, **so that** I can copy and paste with confidence.

**Acceptance criteria**

- [ ] Guide and webhook-verification samples live as files under docs/snippets/<lang>/ and run in CI against a sandbox started in the pipeline
- [ ] Reference request samples are generated from the OpenAPI file

**Priority:** Must · **Estimate:** 1.25 d · **Milestone:** P3 Docs and SDKs · **Depends on:** DOC-03, WHK-02 · **Traces to:** D.samples

### DOC-05 · Try it with a sandbox key

**As a** platform integrator, **I want** to send real sandbox requests from the reference pages, **so that** I can explore without writing code.

**Acceptance criteria**

- [ ] Works with a pasted sandbox key; visitors without a key see examples and a 'Request sandbox access' button
- [ ] Only the sandbox base URL is configurable

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P3 Docs and SDKs · **Depends on:** DOC-01 · **Traces to:** D.docs, D.sales_led

### DOC-06 · Changelog and versioning page

**As a** platform integrator, **I want** dated changelog entries, **so that** I know what changed.

**Acceptance criteria**

- [ ] One entry per release with the API version; linked from the reference

**Priority:** Should · **Estimate:** 0.25 d · **Milestone:** P3 Docs and SDKs · **Depends on:** DOC-01 · **Traces to:** D.docs, D.standards

## SDK · SDKs

_Typed Python and TypeScript clients with automatic idempotency and webhook helpers_ · layer: All three (developer access) · track: portal · 3 stories · 2.25 days

### SDK-01 · Python SDK

**As a** platform integrator, **I want** a typed Python SDK, **so that** I integrate in minutes.

**Acceptance criteria**

- [ ] Generated from openapi.yaml then polished: typed models, automatic idempotency keys on creates, safe retries, webhook verify helper
- [ ] Tests run against the CI sandbox; package builds and installs from the repo

**Priority:** Must · **Estimate:** 1 d · **Milestone:** P3 Docs and SDKs · **Depends on:** API-05, WHK-02 · **Traces to:** D.sdks

### SDK-02 · TypeScript SDK

**As a** platform integrator, **I want** a typed TypeScript SDK, **so that** Node teams integrate as easily as Python teams.

**Acceptance criteria**

- [ ] Same features as SDK-01; ESM and CJS builds; tests in CI

**Priority:** Must · **Estimate:** 1 d · **Milestone:** P3 Docs and SDKs · **Depends on:** API-05, WHK-02 · **Traces to:** D.sdks

### SDK-03 · Postman collection and OpenAPI download

**As a** platform integrator, **I want** a Postman collection and a downloadable spec, **so that** I can use my usual tools.

**Acceptance criteria**

- [ ] Generated in CI from openapi.yaml and linked from the docs

**Priority:** Should · **Estimate:** 0.25 d · **Milestone:** P3 Docs and SDKs · **Depends on:** API-05 · **Traces to:** D.sdks

## WEB · Marketing site

_A public face that looks real and stays honest_ · layer: Go-to-market · track: portal · 8 stories · 3.75 days

### WEB-01 · Home page

**As a** prospect, **I want** a home page that explains the product, shows how it works and offers a demo, **so that** I understand in one minute whether it's for me.

**Acceptance criteria**

- [x] Sections 1-11 from spec/08-developer-portal.md; primary CTA 'Book a demo', secondary 'Request sandbox access'
- [x] Category wording 'agentic payment controls', with the three layers shown as one section; never 'payments company' or 'payment provider'
- [x] Passes the honesty checklist: no logos, testimonials, customer counts, certification badges or licence claims

**Priority:** Must · **Estimate:** 1.5 d · **Milestone:** P4 Website launch · **Depends on:** none · **Traces to:** D.site, D.honesty, BR.category, A4.plans

### WEB-02 · Product, Security and Design partners pages

**As a** prospect, **I want** deeper pages on the product, security and the shadow-report offer, **so that** I can take it to my compliance team.

**Acceptance criteria**

- [x] Security page: non-custodial, audit and replay, kill switch, EU hosting; roadmap items labelled roadmap (for example 'SOC 2: planned')
- [x] Design partners page explains the free shadow report and data handling

**Priority:** Must · **Estimate:** 0.75 d · **Milestone:** P4 Website launch · **Depends on:** WEB-01 · **Traces to:** D.site, D.honesty, B3.lead_shadow, B5.hosting

### WEB-03 · Measured results section

**As a** prospect, **I want** live numbers from the evaluation with dates, **so that** I see evidence, not claims.

**Acceptance criteria**

- [x] Reads results.json at build time; every figure labelled 'test-network evaluation, [date]'

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P4 Website launch · **Depends on:** EVL-06, WEB-01 · **Traces to:** D.site, D.honesty

### WEB-04 · Developer code tabs

**As a** prospect, **I want** a tabbed code block creating a payment intent in 8 languages, **so that** my developers see it's real.

**Acceptance criteria**

- [ ] Uses the same tested snippets as DOC-04

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P4 Website launch · **Depends on:** DOC-04, WEB-01 · **Traces to:** D.site, D.samples

### WEB-05 · Legal pages and analytics

**As a** prospect, **I want** privacy, sandbox terms and cookie notice, with cookie-light analytics, **so that** the site meets basic GDPR expectations.

**Acceptance criteria**

- [x] Templates marked 'draft for legal review'; analytics without cookie banners where possible

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P4 Website launch · **Depends on:** WEB-01 · **Traces to:** D.ops_pages, B1.contracts

### WEB-06 · Booking and access form

**As a** prospect, **I want** to book a demo or request sandbox access, **so that** I can start a conversation in one click.

**Acceptance criteria**

- [ ] Booking link to the founder's appointment page; access form posts to DSH-10

**Priority:** Must · **Estimate:** 0.25 d · **Milestone:** P4 Website launch · **Depends on:** DSH-10, WEB-01 · **Traces to:** D.ops_pages, D.sales_led

### WEB-07 · Status page

**As a** platform integrator, **I want** a status page for the sandbox API, **so that** I know whether a failure is mine.

**Acceptance criteria**

- [ ] Fed by health checks; shows sandbox API, dashboard and docs

**Priority:** Should · **Estimate:** 0.25 d · **Milestone:** P4 Website launch · **Depends on:** FND-07 · **Traces to:** D.ops_pages, B7.reliability

### WEB-08 · SEO basics

**As a** founder, **I want** titles, meta, sitemap, Open Graph and structured data paired with the category, **so that** "Detent payment controls" and our topic searches find us.

**Acceptance criteria**

- [x] Titles pair the name with 'payment controls'; sitemap.xml; OG images; schema.org Organization and SoftwareApplication

**Priority:** Should · **Estimate:** 0.25 d · **Milestone:** P4 Website launch · **Depends on:** WEB-01 · **Traces to:** BR.category, D.site
