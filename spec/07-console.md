# 07 · Back-office console

**Product:** agentic payment controls in three layers: decision, orchestration and operations (see `AGENTS.md`). **This spec covers:** the screens for all three layers. Decision: Invoice drop, Policy, Mandates, Counterparties. Orchestration: Payments, Rails, kill switch. Operations: Exceptions, Reconciliation, Audit, Outbox.

Jinja2 and htmx, server-rendered. Use one CSS file with tokens from the brand (placeholders until the identity is done):

| Token | Value |
|---|---|
| ink | `#0F1629` |
| paper | `#F6F5F0` |
| orange (accent and destructive actions) | `#F2622E` |
| blue (links) | `#2F6BFF` |

Fonts: Space Grotesk for headings, Inter for body text, JetBrains Mono for IDs, addresses and hashes.

**On every page:**
- A top banner: "Prototype · test networks · simulated bank rail".
- The acting user and role (FND-04).
- The kill-switch state. A red bar shows while it is engaged.
- The demo clock with fast-forward, in demo mode only (FND-05).

## Screens

| Screen | Contents | Actions | Stories |
|---|---|---|---|
| **Overview** | The AI team map (CON-11); today's decisions by outcome; share decided without a human; open and overdue cases; UNKNOWN count and oldest age; recon match rate; rail health; recent events stream | Kill switch | CON-02, EXE-08 |
| **AI team** | The three agents (instruction, investigation, reconciliation) as team members: job, layer, what each may and may never do, who decides, limits (mandates in force, read-only tools, the shared daily AI budget); each agent's latest work, and under each item what followed: who resolved its flags, what the policy decided, who approved or rejected the case or the fix. Says whether the agents call the Claude API or use recorded stand-in answers | — (read-only) | CON-11 |
| **Invoice drop** | Upload area; extracted fields with confidence bars and highlighted source text; flags; mandate scope and usage | Resolve flags; "Submit as agent" | CON-05 |
| **Payments** | Table: ID, payee, amount, rail, status, decision, created; filters | Open detail | CON-03 |
| **Payment detail** | Header with status chip; the decision, with each check, reason and evidence; route candidates and scores; attempts (status, nonce, tx hash and explorer link); ledger postings; timeline; agent calls | Replay, Cancel, Send (assist), Export evidence | CON-03, AUD-02, AUD-03 |
| **Exceptions** | Queue: case, type, tier, owner, deadline countdown, status; filters (mine, overdue, tier) | Open case | CON-04 |
| **Case** | **Raw facts first**: payee as registered; full checksummed address in mono with first seen and last changed; amount against the median; rule hits with parameters; mandate scope. Then, collapsed: "Agent evidence and recommendation" with cited claims (each links to its evidence) | Approve or reject with a required reason; reassign | EXC-02, EXC-04 |
| **Reconciliation** | Latest run: match rate; breaks with proposed fix and rationale | Approve fix; run now | CON-07, LED-06 |
| **Rails** | Per rail: currency and network, balance, pre-funded limit used, success rate, p95, last 20 attempts | Connect (mock, Should) | CON-08, RAL-08, RAL-09 |
| **Policy** | Active version; history; diff viewer; draft editor (YAML with schema validation) | Propose; approve; activate | CON-06, POL-07 |
| **Mandates** | Mandates with scope, usage against limits, expiry | Issue (demo), revoke | CON-06, MND-03 |
| **Counterparties** | List with KYB, allowlist, destinations (first seen, last changed), stats | Edit destination (sets last_changed_at) | INT-04 |
| **Outbox** | Every mock email or notification: recipient, template, body, time | — | EXC-07 |
| **Audit** | Event stream with filters; hash-chain status | Verify chain | AUD-01 |
| **Evaluation** | Latest results.json summary; link to the report | Run suite (demo) | EVL-06 |
| **Incidents** | Incidents by severity, trigger, status, notification time and root cause; one incident's timeline and linked replays; a red Sev 1 banner on every page while one is open | Open (manual), log notification, link a replay, note, root cause, resolve | OPS-01, EXE-10 |
| **Settings** | Mode, fail-safe, deadlines, routing weights | Change mode or fail-safe (needs two roles); deadlines and weights read-only | CON-10, EXE-09 |
| **Demo** | Scenario runner: $18,500 invoice; forced timeout; 20-payment batch; close the day; attack sample; reset. Each scenario runs once per demo generation and then shows what it did. Not in the public sandbox | Run; reset (payments lead) | CON-09 |

## UX rules

- Show IDs, addresses and hashes in full in mono, with copy buttons. Never truncate an address on the case screen.
- Use one colour per status: CONFIRMED blue, UNKNOWN amber, BLOCKED and REJECTED orange or red, ESCALATED ink outline.
- Destructive or irreversible buttons (Approve, Send, Kill switch release) ask for confirmation in-page, not with a browser dialog.
- Agent content is visually distinct (a tinted panel with an "AI-generated, cited" label). It is never mixed into the raw facts.

## As built (S9, CON-09)

- **Reset is a new data generation** (D-08 applied to the demo): a fresh fictional organisation seeded from the
  fixtures (`org_demo_g2`, ...), recorded in the append-only `demo_generations` table. The console, the demo clock
  and the agent's key follow the newest generation. Nothing is deleted: the previous generation keeps its audit
  log and ledger, and its kill switch is engaged at reset so it can never send again. A reset is refused while
  any attempt is in flight, and only the payments lead can reset. The demo clock carries over (never backwards).
- **Scenarios** (`detent/demo/scenarios.py`, also `detent demo run <id>`) go through the product's own services:
  the rules decide and the worker sends. The runner never sends a payout or approves anything; it plays the
  outside world (fictional payers sending deposits, a fault armed on the proxy for the next matching send).
  Idempotent: a second run in the same generation returns the recorded result (`demo.scenario_run`).
- **Footer:** the hosting and database regions (FND-07).

## As built (L group 1: INT-05, EXE-10, OPS-01, CON-10)

- **Cancel (INT-05, G-17):** payment detail has "Cancel this payment" for the payments lead while the payment is
  ESCALATED, HELD or READY, with a required reason; the API is `POST /v1/payment_intents/{id}/cancel` (`intents:create`;
  agent keys are refused). Any other status answers 409 `not_cancellable`. An open case is resolved `cancelled`.
- **Incidents (OPS-01):** `/console/incidents` and `/console/incidents/{id}` (`detent/console/incidents.py`,
  `detent/incidents/records.py`). Sev 1 to 4 with notification windows of 1 h, 4 h, 24 h and 5 days; overdue shows in
  red. A Sev 1 or Sev 2 needs a root cause before it is resolved. On-call and the two leads work incidents.
- **Sev 1 banner (EXE-10):** every console page shows a red bar linking each open Sev 1.
- **Settings (CON-10):** the fail-safe is proposed by one lead and approved by the other, like the mode (`mode_changes`
  now has a `setting` column, migration 0016). Deadlines come from the active rule version and routing weights from
  the routing defaults and any per-rail overrides; both are read-only.

## As built (L group 2: SHD-01 to SHD-04, EXC-09)

- **Shadow import (SHD-01):** `/console/shadow` (payments lead and compliance lead; `detent/console/shadow.py`,
  `detent/shadow/imports.py`). Upload a CSV, map its columns (the mapping is guessed from the header), see the
  validation report (rows read, valid, invalid with reasons, duplicates), then decide. Decisions run in memory with
  the active rule version; no payment, decision row, destination, attempt or job is created (`shadow.imported`
  records `executed: false`). Daily caps are counted per UTC day inside the import.
- **Anonymise (SHD-04):** names, destinations and free text are hashed with a per-import salt that is never stored,
  so hashes match inside one import and differ across imports. A counterparty reference that is a registry ID
  (`cpt_...`) is kept; anything else is treated as unregistered.
- **Report (SHD-02):** `/console/shadow/{id}` with a weekly view (`?week=2026-W48`), and HTML and PDF exports
  (`report.html`, `report.pdf`). Sections: summary, decision mix, agreement, unsafe approvals (DekernAI would execute,
  the platform rejected), the platform's approvals the rules would stop, unreconciled rows, simulated routing saving
  (fee paid minus the lowest estimated fee among connected rails in the same currency), method and limits. The report
  reads stored rows only, so it is replayable.
- **Mode gate (SHD-03, D-41):** `/console/shadow` lists gates. A gate measures the last 30 days of shadow rows (the
  newest import wins for a repeated reference) against the organisation's `gate_agreement_bp` (9500) and zero unsafe
  approvals, and is frozen when created. The payments lead and the compliance lead each sign a passed gate, as two
  different people. Settings offers signed gates when a lead proposes a move up; a production organisation can't move up
  without one. The applied mode change is linked to the gate (`mode_gates.mode_change_id`, migration 0017).
- **Agreement sample (EXC-09):** `/console/agreement?days=30` compares the newest recorded investigation's
  recommendation with the final decision for cases approved or rejected in the period, and lists disagreements with
  the agent's cited claims and the person's reason. `needs_information` and cases with no investigation are counted
  but not compared.

## As built (L group 4: AUD-03, DEM-06)

- **Audit (AUD-03):** `/console/audit` replaces the placeholder: the hash-chain check, the last 100 events (filter
  by kind) and an evidence export for one payment or the payments created in a date range, as JSON, HTML or PDF
  (`detent/audit/evidence.py`). A pack holds the inputs, every decision with its rule version and checks, the
  people who approved or rejected, the state changes from the audit log, the attempts with transaction hashes and
  explorer links, and the chain check result at build time. A broken chain is stated on the first page.
- **Scenario packs (DEM-06):** the Demo screen shows which pack seeded the current generation and resets into
  another (`POST /console/demo/reset`, payments lead only; `detent demo reset --pack <id>`). Packs live in
  `fixtures/packs/`: payout platform, crypto service provider and marketplace, each with a fictional platform,
  counterparties, rule overrides on the default rule set and a short batch. "Run this pack's batch" sends it through
  the rules. The scripted spec/11 scenarios use the default pack.

## As built (slice U: USR-03)

- **User payouts:** Payments, Payment detail, Exceptions and the case page show the user account reference and
  "user payout profile" for a payout to one of the platform's own end users. The case's raw facts show the
  platform's `user_verified` flag with who set it and when, in place of KYB and the allowlist.

## As built (slice T: CON-11)

- **AI team (`/console/agents`):** the client's three agents shown as their AI team, in the console navigation after
  Overview and in the dashboard navigation (a dashboard member sees their own organisation, DSH-09). The page leads
  with "They propose; your rules and your people decide" (invariant 5). Each agent card lists what it may do (its one
  proposal), what it may never do (approve, send, retry, re-route, change rules, post to the ledger), who decides, and
  its limits: the mandates in force for the instruction agent, read-only tools, and the daily AI budget the team shares.
- **Activity and interactions:** each agent's latest 15 items from `agent_calls`, newest first, with a summary built
  from typed fields only (amount, currency, counterparty ID, recommendation enum, fix action and target, flag codes);
  invoice text and the model's free text stay on the detail screens (invariant 11). Under each item, what followed,
  from the audit log: `agent.flags_resolved`, `decision.made` ("Your rules (policy vN) decided ..."),
  `case.resolved`, `reconciliation.fix_applied`, `reconciliation.fix_rejected` and `payment.cancelled`, with the
  person's name and role. Each item links to its case, payment or reconciliation; the invoice proposal link is hidden
  for dashboard members (the invoice drop is demo-only).
- **Overview team map:** the Overview opens with a map of the team: the three AI agents around "Your rules", with
  "Your people" below. A red dashed line and dot mark an agent with work waiting for a person; beside the map,
  "Right now" lists that work and "Latest decisions on their work" lists the last four human decisions. Each node
  links to its agent on the AI team page. The map says "AI agents"; "agentic" stays the category word.
- **Read-only:** the page has no form or button and writes nothing; it never calls a model (`detent/views/ai_team.py`).

