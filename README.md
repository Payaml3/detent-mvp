# DekernAI MVP: development package for Claude Code

**Confidential. Prepared 17 Nov 2026.** DekernAI is the brand name (B-01, 26 Nov 2026; it replaced the working name Detent). Category: agentic payment controls, in three layers: decision, orchestration and operations.

This package turns the product model, operating model, MVP scope and developer portal spec into a build-ready repository start: standing instructions for Claude Code, specs, a fully decomposed backlog with acceptance criteria, fixtures and kickoff prompts.

## Developer setup

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker, and [Foundry](https://book.getfoundry.sh/getting-started/installation) (anvil, forge).

```bash
make setup                 # dependencies and pre-commit hooks
cp .env.example .env       # local settings; never commit .env
make db                    # Postgres 16 in Docker, then migrations
make seed                  # fictional demo organisation and users
make lint typecheck test   # the gate every story must pass
make dev                   # http://localhost:8000/console (password from DEMO_PASSWORD)
make chain                 # in a second terminal: anvil + MockUSDC
```

Everything runs on test networks and simulated rails. The app refuses to start with any chain ID outside 84532, 11155111 and 31337, and rejects `sk_live_` keys.

CI (`.github/workflows/ci.yml`) runs lint, typecheck, migrations and the full test suite against Postgres 16 and anvil, a gitleaks secret scan, and the OPS-02 independence check. The independence check reads the `INDEPENDENCE_DENYLIST` repository secret (one term per line) and fails until that secret is set.

## How to use it

1. Create an empty private Git repository and copy this folder's contents into its root.
2. Install Claude Code and open it in the repository. It reads `CLAUDE.md` automatically.
3. Follow `prompts/milestone-prompts.md`, one milestone at a time, in plan mode for the first message of each.
4. After each milestone, run its exit check from `backlog/milestones.md` yourself.
5. Keep the backlog current: edit `backlog/stories.yaml`, then run `python tools/build_backlog.py`. This regenerates the stories, epics, traceability and CSV, and fails if any model item loses coverage.

## What's inside

| Path | Contents |
|---|---|
| `AGENTS.md` (imported by `CLAUDE.md`) | Product summary, 17 non-negotiable invariants, stack, commands, definition of done, things never to do |
| `spec/` | 12 specs: product context, architecture, domain model and state machine, API, policy, agents and mandates, rails and faults, console, developer portal, evaluation, security and deploy, demo script |
| `backlog/stories.yaml` | 146 user stories in 21 epics (the source) |
| `backlog/user-stories.md` | The stories as a readable document with acceptance-criteria checkboxes |
| `backlog/epics.md` | Epic summary and totals by epic, priority and milestone |
| `backlog/milestones.md` | Build order M0 to M12 with exit checks, plus scope options |
| `backlog/traceability.md` | Every product model, operating model, MVP and portal item mapped to its stories, with status |
| `backlog/backlog.csv` | Import into Jira, Linear or a spreadsheet |
| `backlog/model-items.yaml` | The 117 model items used for traceability |
| `fixtures/` | Policy v1, screening list, fictional counterparties, rails, agent mandate, 6 invoices with expected outputs, the 20-payment demo batch |
| `eval/scenarios/` | One example attack and one example fault scenario, as templates |
| `prompts/milestone-prompts.md` | Prompts to paste into Claude Code per milestone |
| `tools/build_backlog.py` | Regenerates backlog documents and checks coverage |

## Before you start (founder inputs)

| Needed by | Item |
|---|---|
| M0 | GitHub repository; a CI secret holding the private denylist for OPS-02 (former-employer terms; never commit it) |
| M2 | Anthropic API key; confirm the AI provider's data terms before any client data is used |
| M3 | Two test wallets per chain, funded from Circle's faucet and a gas faucet |
| M7 | Render and Neon accounts (EU regions) |
| M8 to M11 | Final name and domain; transactional email provider; always-on hosting tier; Mintlify account; booking link; sales inbox; legal review of privacy, sandbox terms and cookies; decision on showing prices |
