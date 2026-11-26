# Product model

Playbook stage 5 (B Define, with the operating model). Gate: founder approves.

**Status: Proposed.** Rebuilt from the one-line extracts of the founder's product model (sections A1 to A7)
in `backlog/model-items.yaml`, plus `spec/product-definition.md` (the source of truth for wording) and
`spec/00-product-context.md`. The founder's original is not in the repo (`founder/sources/README.md`); when it
is added as `founder/sources/product-model.md`, it wins and this page is updated to match. What the build has
proven is marked; outcomes for customers are hypotheses until a design partner confirms them.

## A1. Outcomes for the client

| Outcome | How we'd measure it | Status |
| --- | --- | --- |
| Fewer manual reviews | Share decided without a human, target 70% or more (B7) | Hypothesis; proven only on synthetic data |
| Deposits credited once, to the right account | Wrong or double credits: 0; auto-match 99% or more (L7) | Proven on test networks (S7) |
| Lower cost and failure rate per payout | Cost per payout; failure rate after failover | Hypothesis |
| Evidence an auditor accepts | Every payment replayable; append-only, hash-chained audit (L8) | Proven in the prototype (S7, S8) |

## A2. Modules by layer

| Layer | Module | What it does | Built |
| --- | --- | --- | --- |
| Decision | Intent | One payment ID for life; agents can only propose | S1, S5 |
| Decision | Mandate | Agent-proposed intents stay inside a signed scope | S5 |
| Decision | Decide | Execute, escalate or block, with a reason per check | S1 |
| Decision | Policy | Versioned client-approved rules: KYB, allowlist, limits, KYT, Travel Rule, unusual rules, daily caps | S1, S6 |
| Orchestration | Route | Best rail by policy; failover on technical errors only | S4 |
| Orchestration | Execute | Idempotency, state lock, nonce, balance check, pre-funded limits, kill switch | S2, S4 |
| Orchestration | Connect | Rail adapters, connection flow, status normalisation | S2, S4 |
| Operations | Exceptions | Owner, deadline, held on timeout, raw facts first, approval re-runs policy | S3, S6 |
| Operations | Reconcile | One ledger, deposit intents, matching, exceptions with proposed fixes | S7 |
| Operations | Prove | Audit log, replay, evidence export | S7 |
| Across all three | AI agents | Instruction, investigation and reconciliation agents; read-only tools plus `propose_payment_intent` | S5, S6, S7 |

## A2b. Payment rules

- A failure can retry; a rejection can't; no retry can become a second payment.
- States: SUBMITTED, UNKNOWN, CONFIRMED, FAILED then RETRY, BLOCKED (`spec/02-domain-model.md`).
- UNKNOWN: nothing is resent until the original's outcome is known. The agent never decides to retry.
- Timeouts never become approvals. Approvers see raw facts before the agent's summary.
- "Unusual" is a set of checkable rules: new wallet, changed details, first payment, above norm; daily caps.
- Custody boundary: in production, signing and nonces stay at the client's custody provider; the prototype
  holds test-network keys only.

## A3. Operating modes

| Mode | What happens | Gate to the next mode |
| --- | --- | --- |
| 1 Shadow | Decisions on live traffic during onboarding (`client-journey.md` phase 5); nothing sent | Client signs: agreement % and zero unsafe approvals |
| 2 Assist | Live recommendations; staff click every decision | Same, on live traffic |
| 3 Auto | Executes within approved rules; only escalations reach humans | Same |
| 4 Orchestrate | Routing across two or more rails | Routing add-on |

## A4. Commercial model

Software fee per payment, not a share of money moved; plans: Pilot, Growth, Scale (entry through onboarding, B-04), and a
routing add-on. Detail and open prices: `docs/product/business-model.md`.

## A5. AI model

The LLM proposes; the policy decides. Uncertain fields are flagged, never guessed. Agent tools are read-only.
Free text is data, never instructions, tested by the attack suite (100+ scenarios, the release gate). Every
agent claim cites evidence or isn't shown. Client data is not used to train models; processing stays in the
UK or EU (partly: needs the provider's data terms, production readiness).

## A6. Principles

Never hold funds or keys. The client owns the rules; we enforce them exactly. A block is final. Fail closed.
Prove it on their data first (shadow mode). No retry can ever become a second payment. A timeout never
becomes an approval.

## A7. Product roadmap by phase

| Phase | Scope | Status |
| --- | --- | --- |
| Prototype | $18,500 invoice flow, execution layer, exceptions, deposits, testnets, simulated bank | Built (S0 to S8); live testnet run in S9 |
| MVP portal | Sandbox API and webhooks, dashboard, docs and SDKs, website (P1 to P4) | In progress (D-37) |
| Design-partner beta | Shadow on real exports, CSV or API import, one real read-only adapter | Later; needs a design partner |
| v1 | Assist and Auto for real, two real adapters, multi-tenant, roles, SOC 2 Type I | Later |
| v2 | Routing live, bank rails through a licensed partner, back-office platform integrations | Later |
| v3 | Signed agent mandates on open standards, shared risk signals | Later |

## Open

- Which product outcome the first design partner values most (feeds the North Star check).
- Whether one real read-only adapter for the beta should be a stablecoin custody provider or a bank rail.
