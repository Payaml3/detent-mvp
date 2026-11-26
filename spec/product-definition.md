# Product definition: agentic payment controls

**Source of truth.** Decided 17 Nov 2026 (see `facts.md`). Every other document follows this page. DekernAI is the brand name (B-01, 26 Nov 2026; it replaced the working name Detent).

**In one line:** “Agentic payment controls: one layer that decides, orchestrates and operates every deposit and payout, under your rules.”

## Three layers

| Layer | Question it answers | What it does |
|---|---|---|
| **1. Decision** | Should this payment happen? | Execute, escalate or block every pay-in and pay-out, under rules the client owns |
| **2. Orchestration** | How and where does it go? | Picks the best rail by policy, sends it exactly once, fails over only on technical errors, and has a kill switch |
| **3. Operations** | What happens around it? | Exceptions queue, reconciliation across rails, and audit with replay |

AI agents work across all three, preparing intents, investigating escalations and drafting reconciliation fixes. The rules make every decision.

## How to say it by audience

| Audience | Say |
|---|---|
| Buyers (heads of payments, compliance) | "Agentic payment controls" |
| Investors and analysts | "Payment operations software, with orchestration and AI agents" |
| Regulators and contracts | "A technology service provider" (an ICT third-party provider under DORA), never a payment service provider |
| Developers | "A decision and orchestration API for pay-ins and pay-outs" |

## Rules for wording

- "Agentic" describes how the work is done, never who decides. AI agents prepare; the rules decide.
- Never call DekernAI a "payments company" or "payment provider". It never holds funds or keys.
- Pair the name with the category in public: "DekernAI agentic payment controls" or "DekernAI payment controls".
- Rails are chosen by policy, never by an AI agent.
- Avoid the terms "trust layer" and "guardrails" (a competitor's wording).

## How modules map to layers

| Layer | Modules (product model) | Code packages (dev package) |
|---|---|---|
| Decision | Intent, Mandate, Decide, Policy | `intents`, `mandates`, `policy` |
| Orchestration | Route, Execute, Connect | `routing`, `execution`, `rails` |
| Operations | Exceptions, Reconcile, Prove | `exceptions`, `ledger`, `reconciliation`, `audit` |
| Across all three | AI agents (instruction, investigation, reconciliation) | `agents` (read-only tools plus `propose_payment_intent`) |
