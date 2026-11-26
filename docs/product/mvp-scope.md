# MVP scope and launch criteria

Playbook stage 7 (B Define). Gate: founder approves scope. **Status: Approved** for the scope itself (D-11
slices, D-37 full MVP backlog on 2026-11-23). This page collects it in one place; it adds no new scope.
Sources: `spec/00-product-context.md`, `backlog/milestones.md`, `specs/001-detent-mvp/slices.yaml` and the
MVP scope extracts in `backlog/model-items.yaml`. The founder's original is not in the repo; when it is added
as `founder/sources/mvp-scope.md`, it wins. Live progress is on the roadmap (`founder/roadmap.md`).

## What the MVP must show

In under 10 minutes, a head of payments can:

1. watch an AI agent turn an $18,500 supplier invoice into a USDC payment intent;
2. see it escalated under their rules and approve it from the exceptions queue;
3. watch a forced timeout resolve without a second payment;
4. read the results report.

Then a client's developer, invited by their account owner after KYB, can get sandbox keys, follow the quickstart and trigger every path with test
values.

## Launch criteria

| ID | Criterion | Proven by |
| --- | --- | --- |
| L1 | The $18,500 invoice gives the same correct intent on 10 of 10 runs; an ambiguous invoice is flagged, never guessed | Interpretation suite (S8); real-model run waits on `ANTHROPIC_API_KEY` |
| L2 | Zero unauthorised executions across 100+ attack scenarios, including prompt injection | Attack suite (S8) |
| L3 | Zero duplicate payments across 30+ fault cases; every retry and network switch keeps the payment ID | Fault suite (S4, S8) |
| L4 | A timeout becomes UNKNOWN and nothing is resent until it resolves; the kill switch stops all sending | S4 |
| L5 | A compliance block is never re-routed; a technical failure fails over under the same payment ID | S4 |
| L6 | An overdue escalation stays held and the counterparty is told; approval re-runs policy; raw facts first | S3, S6 |
| L7 | 99% or more of deposits match automatically; each exception shows a proposed fix | S7 |
| L8 | Every payment can be replayed; the console says "prototype, test networks, simulated bank rail" | S7 |

**Can be rough:** desktop only; one demo login; a cold start; several seconds of AI delay; one currency per rail.

## Triage

| Must have (MVP) | Should have (L slice) | Won't have in the MVP |
| --- | --- | --- |
| Decision, orchestration and operations layers (S0 to S8) | Shadow-mode CSV import and the shadow-phase report (onboarding, B-04) | Real rails, banks or open banking |
| Demo-ready prototype in the EU on Base Sepolia and Ethereum Sepolia (S9) | Scenario packs per platform type | The client's custody provider |
| Sandbox API and webhooks (P1) | Operations hardening | Real screening vendors |
| Dashboard and sandbox, KYB-gated access, team and roles, integration verification (P2) | | Card and voucher rails |
| Docs and SDKs, Python and TypeScript (P3) | | Machine-learning risk scores; treasury rebalancing |
| Website launch with honesty rules (P4) | | Certifications; multi-tenant production use; single sign-on |

## Build order (D-37)

S9 Demo-ready prototype in the EU, then P1 Sandbox API and webhooks, P2 Dashboard and sandbox, P3 Docs and
SDKs, P4 Website launch, then L After launch. S0 to S8 are done on `main`.

## What the MVP does not prove

Launch criteria prove the software is safe on test networks with synthetic data. They do **not** prove that
customers have the pain or will pay. That is stages 1 and 2 (`docs/product/problem-validation.md`,
`customer-discovery.md`), and the first cycle's objectives put discovery next to the build for this reason.
