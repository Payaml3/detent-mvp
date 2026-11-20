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
| **Overview** | Today's decisions by outcome; share decided without a human; open and overdue cases; UNKNOWN count and oldest age; recon match rate; rail health; recent events stream | Kill switch | CON-02, EXE-08 |
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
| **Settings** | Mode, fail-safe, deadlines, routing weights | Change mode (needs two roles) | CON-10, EXE-09 |
| **Demo** | Scenario runner: $18,500 flow; forced timeout; 20-payment batch; attack sample; reset | Run; reset | CON-09 |

## UX rules

- Show IDs, addresses and hashes in full in mono, with copy buttons. Never truncate an address on the case screen.
- Use one colour per status: CONFIRMED blue, UNKNOWN amber, BLOCKED and REJECTED orange or red, ESCALATED ink outline.
- Destructive or irreversible buttons (Approve, Send, Kill switch release) ask for confirmation in-page, not with a browser dialog.
- Agent content is visually distinct (a tinted panel with an "AI-generated, cited" label). It is never mixed into the raw facts.
