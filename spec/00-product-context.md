# 00 · Product context

## What it is

**Agentic payment controls:** one layer that decides, orchestrates and operates every deposit and payout, under the platform's own rules. AI agents do the work in all three layers; the rules make every decision.

| Layer | Question it answers | What it does |
|---|---|---|
| **1. Decision** | Should this payment happen? | Execute, escalate or block every pay-in and pay-out, under rules the client owns |
| **2. Orchestration** | How and where does it go? | Picks the best rail by policy, sends it exactly once, fails over only on technical errors, kill switch |
| **3. Operations** | What happens around it? | Exceptions queue, reconciliation across rails, audit with replay |

## The problem

Platforms that hold user balances, such as payout platforms, fintechs, crypto service providers, brokers, prop firms and marketplaces, get rails from their providers but keep every decision themselves:

- whether to credit a deposit, and to which account
- whether a payout is safe
- which rail to use
- how to reconcile afterwards

On stablecoins and instant bank payouts a wrong decision can't be reversed. Today the work is done with static rules, a manual review queue and spreadsheets.

## Who uses the MVP

| Persona | What they do in the product |
|---|---|
| **Payments lead** (client's head of payments) | Sets the mode, owns the kill switch, issues agent mandates, approves reconciliation fixes |
| **Compliance lead** | Owns the rule set; is one of the two approvers on every loosening change; signs mode gates |
| **Reviewer** (client operations) | Owns exception cases; approves or rejects with raw facts first |
| **Backup owner** | Takes over overdue cases |
| **AI agent** (client's accounts-payable agent) | Proposes payment intents from invoices, inside a signed mandate. Never executes |
| **Platform integrator** (client developer) | Calls the API, receives webhooks, uses the sandbox |
| **Auditor** | Reads the audit log, replays payments, exports evidence |
| **On-call engineer** (Detent) | Can engage the kill switch; handles Sev 1 incidents |
| **Detent admin** (founder or sales) | Creates sandbox organisations after a demo; issues invites |
| **Prospect** | Reads the website, books a demo, requests sandbox access |

## MVP definition

In under 10 minutes, a head of payments can:

1. watch an AI agent turn an $18,500 supplier invoice into a USDC payment intent
2. see it escalated under their rules and approve it from the exceptions queue
3. watch a forced timeout resolve without a second payment
4. read the results report

Then a developer can get sandbox keys (sales-led), follow the quickstart and trigger every path with test values.

## Launch criteria (from mvp-scope)

- **L1:** the $18,500 invoice produces the same correct intent on 10 of 10 runs. An ambiguous invoice is flagged, never guessed.
- **L2:** zero unauthorised executions across 100+ attack scenarios, including prompt injection.
- **L3:** zero duplicate payments across 30+ fault cases. Every retry and network switch keeps the payment ID.
- **L4:** a timeout becomes UNKNOWN and nothing is resent until it resolves. The kill switch stops all sending and holds pending payments.
- **L5:** a compliance block is never re-routed. A technical failure fails over under the same payment ID.
- **L6:** an escalation past its deadline stays held and the counterparty gets a status update. Approval re-runs policy. Raw facts are shown first.
- **L7:** 99% or more of deposits match automatically, and each exception shows a proposed fix.
- **L8:** every payment can be replayed. The console is labelled "prototype, test networks, simulated bank rail".

**Can be rough:** desktop only; one demo login for the console; a cold start; several seconds of AI delay; one currency per rail.

## Product principles

1. Never hold funds or keys. The prototype holds test keys only.
2. The client owns the rules; we enforce them exactly.
3. A block is final.
4. Fail closed.
5. Prove it on their data first (shadow mode).
6. A failure can retry; a rejection can't; no retry can ever become a second payment.
7. A timeout never becomes an approval.

## Honesty rules (product, docs and website)

- Detent is "agentic payment controls" software, never a "payments company" or "payment provider". "Agentic" describes how the work is done, never who decides.
- No client logos, testimonials, customer counts or volume figures.
- No certification badges and no "licensed" or "regulated" claims. Roadmap items are labelled as roadmap.
- Every measured result is labelled "test-network evaluation on synthetic data, [date]".
- Demo data uses invented names, marked as fictional.
- No former-employer names, documents or API designs, anywhere.
- The founder's prior-company figures may appear only as personal experience on an About section, never as Detent's traction.

## Out of scope for this MVP

Real rails, banks or open banking; integration with a client's custody provider; real screening vendors; card and voucher rails; machine-learning risk scores; treasury rebalancing; certifications; multi-tenant client production use; single sign-on; the investment-diligence workflow.

All tables carry `org_id` from day one so that sandbox organisations are isolated.
