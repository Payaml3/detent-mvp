# Customer discovery

Playbook stage 2 (A Discover). Gate: 5 to 8 interviews show pain and willingness to pay.

**Status: Proposed. No interviews have been run yet.** The segments, personas and buying roles below are
hypotheses from `spec/00-product-context.md` and the product model. The interview log at the bottom is empty
until the founder runs the interviews. No real company or person names go in this file: use a code (P01, P02)
and keep the mapping outside the repo.

## Who we think the customer is (ICP hypothesis)

| Field | Hypothesis | Status |
| --- | --- | --- |
| Geography | UK and EU | Assumption |
| Company type | Platforms that hold user balances and pay out on irreversible rails: payout platforms, fintechs, crypto service providers, brokers, prop firms, marketplaces | Assumption |
| Size signal | 5k to 500k payouts a month; a payments ops team of 2 to 20 | Assumption |
| Trigger | Adding stablecoin or instant bank payouts; a recent duplicate or wrong payout; an audit finding; review queue growing faster than the team | Assumption |
| Already have | One or more rail providers; KYB/KYC and screening vendors; in-house rules in code | Assumption |

**First segment to test (Proposed):** crypto service providers and prop firms paying out in stablecoins,
because the irreversibility pain is sharpest there and the prototype already runs on stablecoin test networks.

## Buying roles (hypothesis)

| Role | In the deal | What they need to hear |
| --- | --- | --- |
| Head of payments | Champion and likely buyer | Fewer manual reviews; never paid twice; kill switch they own |
| Compliance lead | Must agree; can veto | They own the rules; a block is final; evidence an auditor accepts |
| CFO or finance | Signs the budget above a threshold | Cost per payout and failure rate down; software fee, not a cut of volume |
| CTO or engineering lead | Must agree on integration | Sits beside the rails; one API; sandbox; no custody |
| Operations reviewers | Daily users | Raw facts first; clear owner and deadline per case |

Open: which role holds the budget. Interview question 9 tests it.

## Interview plan

- **Who:** 8 heads of payments or payments ops leads in the first segment, plus 2 compliance leads.
  Screening: they personally own payout or deposit decisions today, and their platform sends at least 5k
  payouts a month.
- **Where to find them:** the founder's own network first (no former-employer clients or documents,
  operating model B1), then payments and compliance communities. Outreach needs the `external` gate.
- **Format:** 25 minutes, video, notes in this file within 24 hours. Problem interview first; the demo only
  in a second meeting.
- **Rules (The Mom Test):** ask about the past, not the future; no pitching; ask for specifics and numbers;
  end with a concrete next step (shadow report export, second meeting with compliance).

### Script (Proposed)

1. Walk me through what happens from a payout request to the money landing. Who touches it?
2. When was the last time a payout or deposit went wrong? What happened, and what did it cost?
3. How do you decide that a payout needs a human? Where do those rules live?
4. Last week, roughly how many payments did someone review by hand? How long does one take?
5. When a rail times out, what does your team do? Has that ever led to paying twice?
6. How do you match deposits to accounts? What happens to the ones that don't match?
7. When an auditor or regulator asks why a payment was held or sent, how do you answer?
8. Where does AI help in your payments operation today, and where would you never allow it?
9. If you fixed this, whose budget would it come from? Who else would have to say yes?
10. Would you share a 30-day anonymised export so we can show you what our rules engine would have decided?

### Red flags

- "That would be nice to have" with no past example.
- Pain belongs to the rail provider, not the platform.
- No one owns the decision, so no one owns the budget.
- They want Dekernai to hold funds or act as their payment provider (out of model).

## Willingness to pay (how we test it)

Pricing is Open beyond D-15 (free shadow report, Pilot, Growth, Scale; "Talk to us"). In discovery we test
willingness, not price:

- **Strong:** agrees to a paid pilot, or a letter of intent naming a budget range.
- **Medium:** shares an export for the free shadow report and books a second meeting with compliance.
- **Weak:** likes the demo, no next step.

The gate passes on at least 3 strong or medium signals out of 8.

## Interview log

| Code | Date | Segment | Role | Pain confirmed (H#) | Workaround today | Signal | Next step |
| --- | --- | --- | --- | --- | --- | --- | --- |

_No interviews yet._

## Synthesis

Filled after 5 interviews: the hypotheses each interview confirmed or disproved, quotes in the customers'
own words (to replace the drafted lines in `founder/landing-page.md`), and the updated ICP.
