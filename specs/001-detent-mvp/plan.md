# Implementation Plan: Detent MVP

**Branch**: `spec/001-detent-mvp` | **Date**: 2026-11-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-detent-mvp/spec.md`

## Summary

Detent is agentic payment controls in three layers. The plan keeps the architecture the founder specified in
`spec/01` and that M0 has started (one Python service, a worker, two simulator apps and Postgres). It adds two
things: contracts for every interface, and a re-sliced build order. The new order is nine small end-to-end
prototype slices (S1 to S9) and four portal slices (P1 to P4); each ends in a demonstrable exit check. The re-slicing
is **proposed** (C-17); the stories themselves are unchanged.

## Technical Context

**Language/Version**: Python 3.12 (uv workspace); TypeScript for one SDK; Astro for the site

**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2 Core, Alembic, psycopg 3, web3.py, Jinja2 and htmx, Anthropic SDK (M2 onwards)

**Storage**: Postgres 16 (Neon, EU region, in production); schemas `detent` and `banksim`

**Testing**: pytest, Hypothesis, import-linter (S5), Playwright (console screenshots), `detent eval` (S8), anvil with MockUSDC

**Target Platform**: Linux containers; Render (EU, Frankfurt) plus Neon for the demo; always-on paid tier for the sandbox (open founder decision)

**Project Type**: web service (API, server-rendered console and dashboard) plus a worker, two simulators, docs, SDKs and a static site

**Performance Goals**: rules-only decision p95 under 50 ms locally and under 5 s in production; agent investigation under 60 s, asynchronous; kill switch effective before the next send (spec/01, Estimate)

**Constraints**: test networks only; integer money; every query scoped by organisation; append-only audit and ledger; time from the Clock; no model call in replay; fail closed

**Scale/Scope**: one demo organisation and a few sandbox organisations; sandbox quotas of 60 requests per minute per key, 500 payments per day and 50 investigations per day per organisation (spec/08, Estimate); 146 stories, 61.25 Must days

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | How the plan complies | Status |
|---|---|---|
| I. The AI proposes; the policy decides | Agents live in `detent.agents` with read-only repositories; the one write path is `propose_payment_intent` through `/v1` with a mandate-bound key; an import-linter contract (S5) forbids imports of execution, rails and approval code; the policy reads typed fields only ([contracts/internal.md](contracts/internal.md#3-agent-output-schemas)) | Pass |
| II. Exactly once | Partial unique indexes, terminal and final-attempt triggers, and `transition()` under `FOR UPDATE` (S2); nonce and raw transaction stored before broadcast; UNKNOWN resolver resends only the same transaction (D-02) | Pass (database part done in M0) |
| III. Blocks final; timeouts never approve; fail closed | Terminal trigger (done); the re-run rule (D-01); the deadline sweeper never approves; `SYSTEM_UNAVAILABLE` routing; the kill switch read inside the lock | Pass, with C-03 open (RECEIVED → HELD) |
| IV. Evidence by construction | Hash-chained audit in the same transaction (done); append-only ledger; replay from `agent_calls` | Pass |
| V. Test networks, integer money, isolation, Clock | All enforced and tested in M0 | Pass |
| VI. Test-first | [tasks.md](tasks.md) puts a test task before every implementation task; [traceability.md](traceability.md) gives each criterion a test | Pass |
| VII. No invented rules | 19 proposed and 2 open requirements are marked as such and wait for the founder ([decisions.md](decisions.md)) | Pass, conditional on founder review |

**Post-design re-check (after Phase 1)**: the data model and contracts add no new business rule beyond the register.
Three M0 artefacts encode proposed rules (permission cells, enum values); they are listed in
[decisions.md](decisions.md#items-in-the-m0-code-that-depend-on-proposed-rules) and can be changed by a forward
migration. **Gate: pass.**

## Architecture

### Components and processes

```mermaid
flowchart LR
  subgraph Client["Client side"]
    PLAT[Platform backend]
    AG[AP agent<br/>proposes only]
    STAFF[Staff: payments lead,<br/>compliance, reviewers]
  end
  subgraph API["api process (FastAPI)"]
    V1["/v1 API"]
    CON[console + dashboard<br/>Jinja + htmx]
    subgraph Decision
      INT[intents] --> MND[mandates] --> POL[policy]
    end
    subgraph Orchestration
      RTE[routing] --> EXE[execution<br/>transition()] --> RAIL[rails adapters]
    end
    subgraph Operations
      EXC[exceptions] ; LED[ledger] ; REC[reconciliation] ; AUD[(audit)]
    end
  end
  WRK["worker process<br/>(jobs, SKIP LOCKED)"]
  AGTS["agents<br/>(read-only tools)"]
  FP[faultproxy] --> CH[(anvil / Base Sepolia /<br/>Eth Sepolia)]
  FP --> BS[banksim]
  PLAT --> V1
  AG --> V1
  STAFF --> CON
  V1 --> INT
  POL -->|EXECUTE| RTE
  POL -->|ESCALATE| EXC
  EXC -->|approve: re-run D-01| POL
  RAIL --> FP
  EXE --> LED
  WRK --> EXE & EXC & REC & LED
  WRK --> AGTS
  AGTS -->|propose_payment_intent| V1
  INT & POL & EXC & EXE & LED --> AUD
```

| Process | Responsibility | State |
|---|---|---|
| `api` | `/v1`, console, dashboard, `/healthz`; synchronous decisions | Stateless |
| `worker` | UNKNOWN resolver, deadline sweeper, deposit watchers, reconciliation, investigation agent, webhook delivery, invariant monitor | Jobs in Postgres; lease plus fencing (M0) |
| `banksim` | Simulated FPS and SEPA Instant | Own schema `banksim` |
| `faultproxy` | Pass-through or injected faults on every rail call | Scenario per request header |
| Postgres | All state | Neon EU in production |

### Module boundaries (enforced)

| Package | May import | Must not import | Enforced by |
|---|---|---|---|
| `detent.domain` | standard library only | anything with I/O | AST test (M0, done) |
| `detent.policy` | domain, read-only repositories | execution, rails, agents | import-linter (S5) |
| `detent.agents` | domain, read-only repositories, `LLMClient` | execution, rails, `exceptions.approve` | import-linter (AGT-03) |
| `detent.execution` | domain, routing, rails, ledger, audit, policy (re-check) | agents | import-linter |
| `detent.api`, `detent.console` | services | repositories directly | import-linter |
| everything | `detent.settings` for configuration | `os.environ` | AST test (M0, done) |
| everything | `detent.clock` | `datetime.now()` | ruff banned-API rule and AST test (M0, done) |

### Request flows

- **Synchronous decision (S1)**: `POST /v1/payment_intents` → idempotency record lookup → intent row (RECEIVED) → mandate check → policy (all checks, counters `UPDATE ... RETURNING`) → decision row → `transition()` → audit event → response. One transaction; any exception rolls back and yields ESCALATE SYSTEM_UNAVAILABLE in a fresh transaction (fail closed).
- **Send (S2)**: job `send_payment` → `SELECT ... FOR UPDATE` on the payment → kill switch, mode, balance, pre-funded limit, mandate, decision age (re-run if stale) → attempt CREATED with nonce and signed raw transaction → commit → broadcast → SUBMITTED, or UNKNOWN on timeout → job `resolve_attempt`.
- **Approval (S3)**: lock case and payment → check approver ≠ initiator, role and deadline rules → re-run policy with `approved_reasons` → READY, a new case, or BLOCKED → audit.

## Data model and contracts

- Entities, constraints and state machines: [data-model.md](data-model.md)
- Public API (OpenAPI 3.1): [contracts/openapi.yaml](contracts/openapi.yaml)
- Webhooks: [contracts/webhooks.md](contracts/webhooks.md)
- Internal contracts (rail adapter, agent outputs, rule-set schema, jobs, audit event kinds): [contracts/internal.md](contracts/internal.md)
- Technical decisions and alternatives: [research.md](research.md)

## Milestones

**Proposed (C-17)**: build in end-to-end slices instead of layers. Each slice ends in an exit check you can run or
demo. Every one of the 146 stories is in exactly one slice, and no story comes before one of its dependencies
(`tools/build_spec.py` checks both). Source: [slices.yaml](slices.yaml). Day counts are the backlog's estimates.

| Slice | Delivers (end to end) | Stories | Days | Replaces |
|---|---|---|---|---|
| S0 ✅ | Foundation with the safety guards | 9 | 3.5 | M0 |
| S1 | API intent → decision with every check → audited | 11 | 5.75 | M1 |
| S2 | EXECUTE → sent once on the local chain → CONFIRMED | 6 | 3.75 | half of M3 |
| S3 | Escalation → case → raw facts → approve → re-run → sent | 10 | 4.75 | parts of M3, M4 |
| S4 | Timeouts, retries, failover, kill switch, second chain, bank simulator | 10 | 5.25 | rest of M3 |
| S5 | $18,500 invoice → agent proposal → mandate → escalation → send | 11 | 4.75 | M2 + invoice screen |
| S6 | Overdue cases, investigation, rule changes, modes | 6 | 3.75 | rest of M4 |
| S7 | Ledger, deposits, reconciliation, replay | 9 | 5.0 | M5 |
| S8 | Evaluation suites and release gate | 8 | 4.75 | M6 |
| S9 | Deployed EU demo on real testnets | 6 | 2.25 | M7 |
| P1 to P4 | API and webhooks; dashboard and sandbox; docs and SDKs; website | 44 | 21.25 | M8 to M11 |
| L | Should and Could after launch | 16 | 7.0 | M12 |

Exit checks per slice and the task list: [tasks.md](tasks.md).

**Why this order**: money moves end to end in S2, a week earlier than in the layered plan; the reviewer's approval
loop is clickable in S3 instead of M4; the agent comes after the paths it depends on exist, so its first demo is the
real flow. **Trade-off**: the console shell (CON-01) moves earlier, to S3.

**Scope option (C-13, open)**: whichever order is chosen, the prototype (S0 to S9) is about 44 days of Must and Should
work for one developer with Claude Code, and the portal about 21 more. Founder choice: full scope, prototype first,
or trim (backlog/milestones.md).

## Project Structure

### Documentation (this feature)

```text
specs/001-detent-mvp/
├── spec.md             # requirements, journeys, roles, workflows, failure cases (/speckit-specify)
├── decisions.md        # contradictions, gaps, assumptions; confirmed vs proposed
├── requirements.yaml   # FR source data
├── inventory.md        # generated: source-linked requirements inventory
├── traceability.md     # generated: requirement → story → criterion → test
├── slices.yaml         # proposed end-to-end milestones
├── test-map.yaml       # evidence for done criteria
├── plan.md             # this file (/speckit-plan)
├── research.md         # technical decisions (/speckit-plan, phase 0)
├── data-model.md       # entities and state machines (/speckit-plan, phase 1)
├── quickstart.md       # how to validate each slice (/speckit-plan, phase 1)
├── contracts/          # openapi.yaml, webhooks.md, internal.md (/speckit-plan, phase 1)
├── tasks.md            # generated (/speckit-tasks)
└── checklists/requirements.md
```

### Source Code (repository root)

```text
apps/api/src/detent/
├── domain/        # ids, money, states, roles (pure; done)
├── db/            # engine + org-scope guard, repositories, Core tables (done)
├── intents/  policy/  mandates/                 # decision layer (S1, S5)
├── routing/  execution/  rails/                 # orchestration layer (S2, S4)
├── exceptions/  ledger/  reconciliation/  audit/ # operations layer (S3, S6, S7; audit partly done)
├── agents/        # instruction, investigation, reconciliation agents (S5, S6, S7)
├── api/           # /v1 routers (S1 onwards)
├── console/       # back office (done: login, act-as; screens from S3)
├── dashboard/  webhooks/  sandbox/              # portal (P1, P2)
├── worker/        # job loop (done) + handlers per slice
└── clock.py settings.py logging.py chainguard.py devchain.py cli.py runtime.py seed.py
apps/api/migrations/versions/   # forward-only SQL
apps/api/tests/{unit,property,integration,concurrency,e2e}/
apps/banksim/  apps/faultproxy/  # stubs now; S4
eval/ docs/ sdks/ apps/site/      # S8, P3, P4
chain/                            # MockUSDC (done)
```

**Structure Decision**: keep the uv workspace and layout from CLAUDE.md as built in M0; new packages appear when
their slice starts.

## Complexity Tracking

No constitution violations to justify.
