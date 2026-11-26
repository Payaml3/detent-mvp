<!-- /founder:landing-page · 2026-11-18 · input: none (built from spec/00-product-context.md, spec/08-developer-portal.md and the live site in apps/site) -->

# Landing page copy: Dekernai

- Assumption: there are no `founder/` files yet, so the product, audience and rules come from `spec/00-product-context.md` and the site decisions already approved: plans priced "Talk to us", placeholders clearly marked, and "Dekernai" as the working name.
- Assumption: the company is pre-launch, with a design-partner offer (the free shadow report). No customer, waitlist or volume numbers exist yet.
- Assumption: the main reader is the head of payments at a UK or EU platform that holds user balances. Their compliance lead and developers read second.
- Constraint from the spec's honesty rules: no testimonials, logos, customer counts or volume figures, and no certification claims. The proof and testimonial sections below follow these rules.

## 1. Hero

**Headline:** Check every payout against your rules before it can't be undone

Alternative (closer to the current site): Every payout decided, sent once, reconciled

**Subheadline:** For UK and EU platforms that hold user balances. Dekernai checks, routes and reconciles every stablecoin and instant bank payment, beside the rails you already use.

**Button:** Get your free shadow report
**Second link:** Book a 10-minute demo

**Proof line:** Starts in shadow mode: Dekernai decides beside your team and sends nothing.

There is no real number to show yet. If you later publish one, use a dated evaluation figure in this exact form: `[Figure], test-network evaluation on synthetic data, [date]`. Don't show a design-partner count until each partner has agreed in writing.

## 2. Problem

**Headline:** Your rails send the money. Every decision is still yours.

1. "**Once a stablecoin payout is sent, it's gone.** If our check was wrong, there's no chargeback and no recall."
2. "**Our rules live in code, a review queue and a spreadsheet.** When a payment is held, nobody can show me which rule held it or why."
3. "**When a rail times out, we don't know if the money went.** If we resend, we might pay twice. If we wait, the customer chases us."

These lines are drafted from the spec, not from real interviews. Replace them with customers' own words after running `/founder:user-interviews`.

## 3. Solution

**Headline:** One layer that decides, sends and proves every payment

**Your rules decide, not AI**
Every deposit and payout is executed, escalated or blocked under a rule set your compliance lead owns. AI agents prepare payments and investigate cases, but they can never send money or approve a payment.
*Detail:* loosening a rule needs two named approvers. One of them is your compliance lead.

**Sent once, even when rails fail**
Dekernai picks the rail your policy prefers and sends each payment exactly once. If a rail times out, the payment is marked unknown and nothing is resent until the rail gives a definite answer.
*Detail:* each payment keeps one ID through every retry and switch of rail. One kill switch stops all sending.

**Reconciled and provable afterwards**
Exceptions land in one queue that shows the raw facts first. Deposits are matched across rails, and any payment can be replayed step by step for an auditor.
*Detail:* the MVP target is 99% of deposits matched automatically. That is a launch target, not a measured result.

## 4. How it works

1. **Book a call.** In 10 minutes, tell us which rails you pay out on and how you decide payments today.
2. **Send one month of exports.** Anonymised payout and deposit files, under a data processing agreement signed first.
3. **Read your shadow report.** Within five working days, see what your rules would have decided, payment by payment.
4. **Choose your pace.** Shadow mode, then Assist (your team clicks Send), then Auto within the rules you approve.

Your part of steps 1 and 2 takes under an hour. Step 3 is our work, not yours.

## 5. Social proof

**Recommended for this stage (pre-launch):**
- The team's track record in payments operations. Describe the work, but don't name any former employer.
- Advisor quotes.
- Your own dated test-network evaluation results, labelled as such.

**Testimonial slots (placeholders only):**
- `[Quote from an advisor who has run payout operations: which irreversible payment mistake this would have caught, and how they handle that today]`
- `[Quote from a design-partner head of payments, with written consent: what the shadow report found in their own month of data that their current checks missed]`

The second slot conflicts with the spec's current rule of "no testimonials". Keep it hidden until you change that rule and have written consent.

## 6. Pricing preview

**Free shadow report:** one month of your past payments, decided under your rules. Nothing is sent.
**Pilot, Growth, Scale:** Talk to us.

**Is it worth it?** You'll see, on your own data, what your rules would have held, before you pay anything.

## 7. FAQ

**Do you hold our funds or keys?**
No. Dekernai never holds client funds or keys. It sits beside your rails and tells them what to do, so your money stays where it is today.

**Do we have to change payment providers?**
No. Dekernai works with the rails you already use and starts with stablecoins and instant bank payouts. You keep your contracts and add a control layer on top of them.

**Can the AI approve or send a payment?**
No. AI agents propose payments and draft fixes, but your rules make every decision and a person approves every exception. The approver can never be the person who started the payment.

**Where does our data go?**
Shadow report exports are anonymised and processed in the UK or EU, under a data processing agreement signed before anything is sent. They are used only for your report and deleted on the schedule the agreement sets out.

**What happens if something breaks?**
Dekernai fails closed. Any error in a decision holds the payment or sends it to your review queue; it never sends. If a rail times out, nothing is resent until the rail gives a definite answer, so no payment can go out twice.

## 8. Final call to action

**Headline:** See which of last month's payouts your rules would have stopped

**Button:** Get your free shadow report

**Risk reversal:** The report is free and sends nothing. You only need one month of anonymised exports.

## 9. SEO metadata

**Title tag (52 characters):** Dekernai: agentic payment controls for instant payouts

**Meta description (157 characters):** Check every stablecoin and instant bank payout against your own rules before it is sent. Sent once, reconciled and provable. Start with a free shadow report.

**Target keywords:**
1. payout controls
2. stablecoin payout risk
3. payment reconciliation software

These keywords are untested. Run `/marketing:seo-audit` to check search volume before you rely on them.
