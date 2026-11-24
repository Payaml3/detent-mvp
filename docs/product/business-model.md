# Business model and positioning

Playbook stage 3 (B Define). Gate: founder approves.

**Status: Proposed.** Built from the product model (A4), the operating model (B1, B3, B4, B7) and the
decisions already in the register (D-15 plans and "Talk to us", D-17 working name). Prices, unit economics
and the buyer are **Open** until discovery (`customer-discovery.md`) gives evidence. When the founder
approves stage 3, the goal tree (`founder/goals.json`) is due under the plugin's rule.

## Lean canvas

| Block | Content | Status |
| --- | --- | --- |
| Customer segment | UK and EU platforms that hold user balances and pay out on irreversible rails; first segment: crypto service providers and prop firms paying out in stablecoins | Assumption |
| Problem | Every deposit and payout decision stays with the platform; on irreversible rails a wrong one can't be undone; rules live in code, queues and spreadsheets | Assumption (`problem-validation.md`) |
| Unique value | Agentic payment controls: one layer that decides, orchestrates and operates every deposit and payout, under your rules. AI prepares; the rules decide | Approved wording (`spec/product-definition.md`) |
| Solution | Decision (execute, escalate, block), orchestration (best rail, exactly once, kill switch), operations (exceptions, reconciliation, audit with replay) | Built as a prototype (S0 to S8) |
| Channels | Founder-led sales; free shadow report as the entry offer; website and sandbox for evaluation; later back-office platform partners | Proposed |
| Revenue | Software fee per payment decided, never a share of money moved; plans Pilot, Growth, Scale; routing add-on | Proposed (A4; D-15 for plan names) |
| Cost structure | AI model usage, EU hosting, security assurance (pen test, then SOC 2), legal (perimeter opinion, contracts), founder time | Assumption |
| Key metrics | Payments decided per week under Detent (North Star); shadow-to-pilot 40%; pilot-to-paid 60%; under 10 days from pilot signed to shadow live | Proposed (B7) |
| Unfair advantage | Founder's domain experience in payment operations (personal experience only, never as Detent traction); safety invariants proven by a release gate | Assumption |

## Positioning

- **Category:** agentic payment controls (buyers); payment operations software with orchestration and AI
  agents (investors); a technology service provider under DORA (regulators and contracts). Never a payments
  company or payment provider.
- **For** heads of payments at UK and EU platforms that hold user balances, **who** can't undo a wrong
  stablecoin or instant bank payout, **Detent is** agentic payment controls **that** decide, send once and
  prove every payment under rules the platform owns. **Unlike** in-house rules and a review queue, or a rail
  provider's own checks, Detent works across every rail, never holds funds or keys, and starts in shadow mode
  on the platform's own data.
- **Alternatives the buyer uses today (hypothesis):** in-house code plus a manual queue and spreadsheets; the
  rail provider's built-in controls; general fraud or transaction-monitoring tools. No real competitor names
  in user-facing copy.

Open: the one-line alternative the buyer names in interviews.

## Revenue model

| Plan | What it is | Unit | Price |
| --- | --- | --- | --- |
| Free shadow report | Detent decides on a 30-day export; a report of what it would have done; nothing sent | Per platform, once | Free |
| Pilot | Shadow then Assist on live traffic, one rail, time-boxed | Flat pilot fee | Open ("Talk to us", D-15) |
| Growth | Assist or Auto, two or more rails, exceptions and reconciliation | Per payment decided, monthly minimum | Open |
| Scale | Orchestrate across rails, higher volumes, assurance pack | Per payment decided, volume tiers | Open |
| Routing add-on | Best-rail choice and failover | Per routed payment | Open |

Rules (Proposed, from A4): usage is measured from the ledger and billed monthly (B3); the fee is per payment
decided, not a percentage of value, so Detent never looks like a payment provider and incentives stay neutral.

Pricing changes need the `pricing` gate. Proposed next step: test a pilot fee range in the second discovery
meeting, then run `/founder:pricing-strategy` with that evidence.

## Unit economics (to fill from evidence)

| Item | Hypothesis | Status |
| --- | --- | --- |
| Cost to decide one payment (rules only) | Close to zero; hosting only | Assumption |
| Cost when an agent works on a payment | Model tokens per invoice or investigation; capped per customer (production readiness) | Open: measure once `ANTHROPIC_API_KEY` is set |
| Gross margin target | At least 75% | Assumption (B7 names gross margin; no target set) |
| Sales cycle | 1 to 3 months from first call to pilot | Assumption |

## Go-to-market sequence (Proposed)

1. Problem interviews (8), no pitching.
2. Demo (spec/11) and the offer of a free shadow report.
3. Shadow report delivered in 5 working days (B3).
4. Pilot signed; shadow live in under 10 days (B7); weekly agreement report; client signs each mode move.
5. Paid plan.

## Regulatory model

- UK limited company acting as a technology provider (B1).
- Never holds funds or keys; signing and nonces at the client's custody provider in production (A2b).
- Perimeter opinion from counsel **before the first paid pilot** (B1). Open: who, and the cost (`spend` gate).
- Contracts: MSA, DPA, DORA Article 30 annex, a clause that the client owns the rules (B1). `legal` gate.

## Open questions for the founder

1. Is the first segment right (stablecoin payouts at crypto service providers and prop firms)?
2. Who holds the budget: head of payments, compliance or finance?
3. Is the unit "per payment decided" right, or flat per platform for the pilot?
4. Show prices on the website, or keep "Talk to us" (D-15) until three pilots?
5. Does the old "Stablecoin payment acceptance" chat scope still apply, or is it superseded?
