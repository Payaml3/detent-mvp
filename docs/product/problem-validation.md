# Problem validation

Playbook stage 1 (A Discover). Gate: pain confirmed by evidence, not assumption.

**Status: Proposed. Every problem statement below is a hypothesis to validate.** No customer interviews,
letters of intent or usage data exist in the repo yet (`founder/status.md`, risk 1). The hypotheses come from
the founder's product model, case study and `spec/00-product-context.md`. Nothing here is a fact about the
market until the evidence column is filled.

## The problem we think exists

Platforms that hold user balances (payout platforms, fintechs, crypto service providers, brokers, prop firms
and marketplaces) get rails from their providers but keep every decision themselves: whether to credit a
deposit and to which account, whether a payout is safe, which rail to use, and how to reconcile afterwards.
On stablecoins and instant bank payouts a wrong decision can't be reversed. Today that work is done with
static rules, a manual review queue and spreadsheets.

## Hypotheses

Each hypothesis is **Assumption** until the evidence column holds interview notes or data. "Confirmed" needs
at least 5 of 8 interviewed platforms describing it unprompted, with a recent concrete example.

| ID | Hypothesis | Why we believe it (source) | What would disprove it | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| H1 | Irreversible payouts (stablecoin, instant bank) are a top-3 operational worry for heads of payments at balance-holding platforms | Product model A1; case study v2 | Interviewees rank it below onboarding, fraud on cards or FX cost | None yet | Assumption |
| H2 | Payout and deposit decisions sit in code, a review queue and spreadsheets, with no single record of which rule held a payment and why | Product model A1, A2; spec/00 | Most platforms already use a rules engine with an audit trail they're happy with | None yet | Assumption |
| H3 | Manual review takes a material share of a payments ops team's week (target signal: more than 1 FTE per 10k payouts a month) | Operating model B7 (share decided without a human, 70% target) | Review volume is small, or fully handled by the rail provider | None yet | Assumption |
| H4 | Timeouts and unknown outcomes cause duplicate payments or slow customer chasers at least monthly | Product model A2b; launch criterion L3, L4 | Rails give definitive outcomes; duplicates are rare and cheap | None yet | Assumption |
| H5 | Deposits are sometimes credited to the wrong account or twice, and reconciliation across rails is manual | Product model A1 (deposits credited once); L7 | Matching is automatic today at 99% or more | None yet | Assumption |
| H6 | Platforms want AI help (invoice-to-payment, investigation) but won't let AI decide or send | Product model A5; positioning "the rules decide" | Buyers either refuse AI anywhere in the payment path, or want AI to approve | None yet | Assumption |
| H7 | Compliance leads need evidence an auditor accepts: replay and an append-only trail | Product model A1 (evidence), A2 Prove | Existing tooling already satisfies auditors | None yet | Assumption |
| H8 | The buyer will try a tool that sits beside the rails and starts in shadow mode, with no change to their providers | Product model A3, A6 | Buyers want their rail provider to supply this, or won't share exports | None yet | Assumption |

## Riskiest assumptions, in order

1. **H1 and H3 together: is the pain big enough to pay for?** If irreversible payouts are a worry but rare, or
   review is cheap, there's no budget. Test first.
2. **H8: will they share data for a shadow report?** The whole go-to-market (free shadow report, then Pilot)
   depends on it.
3. **Who owns the budget** (payments lead, compliance or finance). See `customer-discovery.md`.
4. **Regulatory perimeter:** that "payment controls beside the rails, never holding funds or keys" stays
   outside payment-institution and e-money licensing in the UK and EU. This is a feasibility risk, not a
   pain hypothesis, and needs counsel (`founder/business-context.md` § Open; operating model B1).

## How we validate

| Experiment | Tests | Cost | Pass signal |
| --- | --- | --- | --- |
| 8 problem interviews with heads of payments or payments ops (script in `customer-discovery.md`) | H1 to H7 | Founder time only | 5 of 8 describe H1 and H2 unprompted, with a recent example |
| Ask each interviewee for a 30-day anonymised payout export for a free shadow report | H8, H3 | Founder time; uses the existing S7 import and replay | 3 of 8 agree to share an export |
| 10-minute demo (spec/11) after the problem interview, never before | H6, H7 | The S9 deployed prototype | 3 of 8 ask for a pilot or a next meeting with compliance |
| Perimeter opinion from UK counsel (and FCA PASS if useful) | Feasibility | Spend: needs the `spend` gate | Written view that the model needs no licence |

## Decision rule

- **Passed:** at least 5 of 8 confirm H1 and H2 with examples, and at least 3 agree to a shadow report.
- **Pivot:** pain is real but sits in a different segment (for example only crypto service providers) or a
  different job (for example reconciliation only). Narrow the ICP and re-run.
- **Kill or rethink:** fewer than 3 of 8 recognise the pain, or nobody will share data.

The founder marks stage 1 Passed or Deferred in `founder/playbook.md`.
