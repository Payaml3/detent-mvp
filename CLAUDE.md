# CLAUDE.md: Detent MVP

Read this file at the start of every session. It's the project's standing instructions.

**Then read `HANDOFF.md`:** where the build is, which branch to start from, the next slice and the open founder items. We work one slice per session in this one repository; update `HANDOFF.md` at the end of each slice.

## Operating protocol

We work under `founder/operating-protocol.md`; `founder/status.md` holds priorities, risks and founder items.
Decisions: product and engineering in `specs/001-detent-mvp/decisions.md`, business in `founder/decisions.md`.
Skills: `handoff` (close a session or slice), `record-decision`, `weekly-review` (in `.claude/skills/`).
The context guard (`.claude/hooks/`, limits in `.claude/governance.json`) warns, then asks for a handoff.
New content starts as Proposed, Assumption or Open; only the founder makes anything Approved.

## Model choice

| Work | Model |
|---|---|
| Architecture, security, and money-path slices or stories (POL, EXE, RAL, EXC, LED, MND, AGT, invariants) | strongest available |
| Routine stories, docs, website copy, tests for already-built code, reviews, handoffs | mid-tier |
| Weekly review early stop, formatting, renames | smallest that works |

A session can't switch its own model, so recommend the model in every "Next session" line.

## What we are building

Detent (working name) is **agentic payment controls** for UK and EU platforms that hold user balances: one layer that decides, orchestrates and operates every deposit and payout, under the platform's own rules. It sits **beside** the platform's payment rails, starting with rails that can't be reversed: stablecoins and instant bank payouts.

It has three layers. AI agents work across all three, preparing intents, investigating escalations and drafting reconciliation fixes. The rules make every decision.

In one line: "Agentic payment controls: one layer that decides, orchestrates and operates every deposit and payout, under your rules."

| Layer | Question | Modules (spec) |
|---|---|---|
| **1. Decision** | Should this payment happen? Execute, escalate or block under client-owned rules | intents, mandates, policy (spec/04, spec/05) |
| **2. Orchestration** | How and where does it go? Best rail by policy, exactly-once execution, failover on technical errors only, kill switch. A timeout becomes UNKNOWN, never FAILED | routing, execution, rails (spec/06) |
| **3. Operations** | What happens around it? Exceptions queue, reconciliation across rails, audit with replay | exceptions, ledger, reconciliation, audit (spec/07) |

Detent is **not** a payment company or payment provider. It never holds client funds or keys in production. In the prototype it holds **test-network keys only**. Use "agentic payment controls" (or "payment controls" for short) in all UI text, docs and copy, and name the three layers decision, orchestration and operations. Never write "payments company" or "payment provider" about Detent.

The MVP has two tracks:
1. **Prototype:** the back-office engine and console, demoed in 10 minutes (spec/11-demo-script.md).
2. **Developer portal:** the public sandbox API, dashboard, docs, SDKs and marketing site.

## Where things are

| Path | What it holds |
|---|---|
| `spec/00-product-context.md` | Problem, users, MVP definition, honesty rules |
| `spec/01-architecture.md` | Components, module boundaries, request flows |
| `spec/02-domain-model.md` | Entities, payment state machine, database constraints |
| `spec/03-api.md` | Public API endpoints, errors, webhooks, standards |
| `spec/04-policy.md` | Rule-set format, checks, precedence, rule changes |
| `spec/05-agents.md` | Instruction, investigation and reconciliation agents; mandates; injection rules |
| `spec/06-rails-and-faults.md` | Adapter contract, rails, routing, failover, fault injection, test values |
| `spec/07-console.md` | Back-office screens |
| `spec/08-developer-portal.md` | Dashboard, sandbox, docs, SDKs, website |
| `spec/09-evaluation-and-tests.md` | Test strategy, eval suites, release gate |
| `spec/10-security-and-deploy.md` | Settings, secrets, hosting, runbooks |
| `spec/11-demo-script.md` | The 10-minute demo |
| `backlog/user-stories.md` | Every story with acceptance criteria (generated) |
| `backlog/milestones.md` | Build order and exit checks |
| `backlog/stories.yaml` | Source of the backlog. Edit it, then run `python tools/build_backlog.py` |
| `fixtures/` | Policy, mandate, counterparties, rails, invoices, batch |

## Non-negotiable invariants

Each invariant has tests. Never weaken a test to make it pass. If a story seems to need an exception, stop and ask.

1. **One payment ID for life.** Retries, failovers and approvals keep the `pay_` ID.
2. **At most one in-flight attempt and one CONFIRMED attempt per payment**, enforced by partial unique indexes.
3. **A timeout is UNKNOWN, never FAILED.** Nothing is resent while any attempt is UNKNOWN. Only definitive rail evidence resolves it.
4. **BLOCKED and REJECTED are terminal.** A block is never approved, retried, re-routed or resubmitted. A database trigger enforces this.
5. **The AI proposes; the policy decides.** `detent.agents` must never import `detent.execution`, `detent.rails` or the approve functions. An import-boundary test enforces this. Agent tools are read-only, except `propose_payment_intent`.
6. **Retries are deterministic.** Only the execution layer retries, only on `TECHNICAL_RETRYABLE`, and only by configured rules.
7. **A timeout never becomes an approval.** An overdue case stays held, the counterparty is told, and the backup owner takes over.
8. **Approval re-runs policy** with the active rule version before anything is sent. The approver can't be the initiator.
9. **Fail closed.** Any error in a decision path leads to hold or the manual queue, never execute.
10. **Kill switch.** It is checked inside the lock before every send. Only the client's payments lead can release it.
11. **Untrusted text is data.** Invoice text, notes, names and references go to models only inside delimited data blocks. The policy reads typed fields only, never agent free text.
12. **Audit is append-only and hash-chained.** Audit events are written in the same transaction as the change they describe.
13. **All state changes go through `transition()`**, under `SELECT ... FOR UPDATE`, using the allowed-transitions table.
14. **Test networks only.** Refuse to start with a chain ID outside 84532, 11155111 or 31337. Reject `sk_live_` keys.
15. **Money is integer minor units plus a currency.** No floats anywhere in money paths.
16. **Every query is scoped by `org_id`.**
17. **Time comes from the `Clock` service.** Never call `datetime.now()` directly in `detent/`.

## Stack

- Python 3.12 with `uv` for dependencies.
- FastAPI and Pydantic v2.
- SQLAlchemy 2 and Alembic on Postgres 16. Production uses Neon in an EU region.
- web3.py, with anvil and MockUSDC for local tests.
- Jinja2 and htmx for the console and dashboard. No SPA framework.
- pytest, Hypothesis, ruff and mypy.
- Anthropic Python SDK. Models come from settings: `claude-sonnet-5-5` for the agents, `claude-haiku-5-5` for light tasks, and `claude-opus-5-5` as the evaluation judge only.
- Docs: Mintlify, from `docs/`.
- Website: Astro static site, in `apps/site/`.
- SDKs: Python in `sdks/python`, TypeScript in `sdks/typescript`.

## Repository layout (target)

```
apps/api/src/detent/
  domain/        # pure types, money, ids, state machine table (no I/O)
  intents/  policy/  mandates/  agents/  execution/  rails/  routing/
  exceptions/  ledger/  reconciliation/  audit/  webhooks/  sandbox/
  api/           # FastAPI routers for /v1
  console/       # Jinja + htmx back office
  dashboard/     # developer dashboard + admin
  worker/        # job loop and scheduled jobs
  db/            # engine + org-scope guard, org-scoped repositories, Core tables
  clock.py  settings.py  logging.py  chainguard.py  devchain.py  cli.py
apps/api/tests/  # unit, integration, property, concurrency
apps/banksim/    # simulated instant bank rail (separate FastAPI app)
apps/faultproxy/ # fault-injection proxy
apps/site/       # Astro marketing site
eval/            # scenarios (data) + runner + report templates
docs/            # Mintlify docs + snippets/<lang>/
sdks/python  sdks/typescript
fixtures/  spec/  backlog/  tools/
```

## Commands (create them in FND-01, keep this list current)

```
make setup        # uv sync + pre-commit hooks (ruff, gitleaks, no .env files)
make db           # docker compose Postgres 16 + alembic upgrade head
make db-reset     # drop the local schema, migrate and seed again
make seed         # fictional demo org and console users (idempotent)
make chain        # anvil (31337) + MockUSDC; writes chain/local.json; Ctrl-C stops
make dev          # api :8000 + worker + banksim :8100 + faultproxy :8200
make test         # unit, property, integration, concurrency, local chain (needs make db)
make test-fast    # unit + property only, no database
make lint typecheck
make eval         # detent eval run --suite all (fails until slice S8)
make denylist     # OPS-02 check; needs DENYLIST in the environment
make governance   # tools/check_governance.py (registers, HANDOFF on slice done) + tools/tests
make backlog      # python tools/build_backlog.py
make spec         # python tools/build_spec.py: Spec Kit inventory, traceability, tasks + coverage checks
make site-dev     # marketing site (Astro) dev server; make site builds it; make site-test runs its checks
```

Specifications and planning use Spec Kit (`.specify/`, `specs/<feature>/`); the MVP plan is in `specs/001-detent-mvp/`.
Rules marked Proposed or Open in `specs/001-detent-mvp/decisions.md` are not business rules until the founder approves them.

Migrations are plain SQL files in `apps/api/migrations/versions/` run by Alembic; they are forward-only. The test suite drops and re-migrates the `detent_test` database, and each test creates its own organisation, so no cleanup is needed.

## How to work a story

1. Read the story in `backlog/user-stories.md` and the specs it points to.
2. Write the tests from the acceptance criteria first, including concurrency and fault tests where the story touches money.
3. Implement the smallest change that passes. Keep modules inside their boundaries.
4. Run `make lint typecheck test`. For any story in POL, EXE, RAL, EXC or LED, also run `make eval`.
5. Tick the criteria in `backlog/user-stories.md` (edit `stories.yaml`, then regenerate). Commit with the story ID in the message, for example `EXE-05: timeout becomes UNKNOWN`.
6. If a spec is wrong or missing something, update the spec in the same change and say so in the commit.

## Definition of done (every story)

- Every acceptance criterion has a passing test or a written manual check in the PR description.
- Lint, type checks, tests and the release-gate suites pass.
- State-changing actions write audit events.
- No secrets, real personal data or former-employer material are in the change.
- User-facing text is honest: label prototype items, and add no claims about clients, certifications or licences.

## Things never to do

- Never connect to a mainnet, a real bank or a real payment provider.
- Never let an agent call execution, approval or retry code.
- Never mark a timeout as FAILED, and never resend while UNKNOWN.
- Never edit or delete audit rows or ledger entries. Corrections are new entries.
- Never add real company names, client logos, testimonials or volume figures.
- Never use or reference any former employer's product, documents, API design or name. CI runs a private denylist check (OPS-02).
- Never commit `.env` files, keys or wallet secrets.
- Never call the model inside replay. Replay uses stored outputs.

## Open decisions (ask the founder; don't guess)

- The final name and domain (`Detent` is the working name; keep it in one settings value: `BRAND_NAME`).
- The transactional email provider for the dashboard.
- The paid hosting tier for the public sandbox, which should not sleep.
- Whether the website shows prices or "Talk to us".
