<!-- /founder:landing-page · 2026-11-18 · input: none (built from spec/00-product-context.md, spec/08-developer-portal.md and the live site in apps/site) -->

# Landing page copy: DekernAI

> **Updated for B-04 (client journey, `docs/product/client-journey.md`):** there is no free shadow report. Clients come in through a seven-phase onboarding; shadow is a phase after the contract, on live traffic. The buttons are "Book a demo" and "Talk to us".

- Assumption: there are no `founder/` files yet, so the product, audience and rules come from `spec/00-product-context.md` and the site decisions already approved: plans priced "Talk to us", placeholders clearly marked, and "DekernAI" as the working name.
- Assumption: the company is pre-launch, with onboarding in seven phases (B-04). No customer, waitlist or volume numbers exist yet.
- Assumption: the main reader is the head of payments at a UK or EU platform that holds user balances. Their compliance lead and developers read second.
- Constraint from the spec's honesty rules: no testimonials, logos, customer counts or volume figures, and no certification claims. The proof and testimonial sections below follow these rules.

## 1. Hero

**Headline:** Check every payout against your rules before it can't be undone

Alternative (closer to the current site): Every payout decided, sent once, reconciled

**Subheadline:** For UK and EU platforms that hold user balances. DekernAI checks, routes and reconciles every stablecoin and instant bank payment, beside the rails you already use.

**Button:** Book a demo
**Second link:** Talk to us

**Proof line:** Sits beside your rails and never holds your funds or keys.

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
DekernAI picks the rail your policy prefers and sends each payment exactly once. If a rail times out, the payment is marked unknown and nothing is resent until the rail gives a definite answer.
*Detail:* each payment keeps one ID through every retry and switch of rail. One kill switch stops all sending.

**Reconciled and provable afterwards**
Exceptions land in one queue that shows the raw facts first. Deposits are matched across rails, and any payment can be replayed step by step for an auditor.
*Detail:* the MVP target is 99% of deposits matched automatically. That is a launch target, not a measured result.

## 4. How it works

Onboarding runs in seven phases, each with an owner on both sides and an exit check:

1. **Discovery.** A call and a live demo; we check the fit together. Exit: NDA signed.
2. **Contract and due diligence.** Our KYB on your business, the contract and DPA, and the pilot scope.
3. **Sandbox integration.** Your engineers integrate and trigger every path in the sandbox.
4. **Policy setup.** Your rules become rule set v1. Your compliance lead signs it off.
5. **Shadow on live traffic.** Every live payment is decided, nothing is sent; a weekly agreement report. You sign the move to Assist.
6. **Go-live.** Assist, then Auto, on one rail. You sign each move.
7. **Scale.** More rails, routing and failover, quarterly reviews.

## 5. Social proof

**Recommended for this stage (pre-launch):**
- The team's track record in payments operations. Describe the work, but don't name any former employer.
- Advisor quotes.
- Your own dated test-network evaluation results, labelled as such.

**Testimonial slots (placeholders only):**
- `[Quote from an advisor who has run payout operations: which irreversible payment mistake this would have caught, and how they handle that today]`
- `[Quote from a client head of payments, with written consent: what the shadow phase found in their own live traffic that their current checks missed]`

The second slot conflicts with the spec's current rule of "no testimonials". Keep it hidden until you change that rule and have written consent.

## 6. Pricing preview

**Pilot, Growth, Scale:** Talk to us. The Pilot covers phases 3 to 6 on one rail. A software fee per payment decided, never a share of the money you move.

**Is it worth it?** In the shadow phase you see, on your own live traffic, what your rules decide before anything is sent.

## 7. FAQ

**Do you hold our funds or keys?**
No. DekernAI never holds client funds or keys. It sits beside your rails and tells them what to do, so your money stays where it is today.

**Do we have to change payment providers?**
No. DekernAI works with the rails you already use and starts with stablecoins and instant bank payouts. You keep your contracts and add a control layer on top of them.

**Can the AI approve or send a payment?**
No. AI agents propose payments and draft fixes, but your rules make every decision and a person approves every exception. The approver can never be the person who started the payment.

**Where does our data go?**
The contract and a data processing agreement are signed before any of your data reaches us. Data is processed in the UK or EU and used only as the agreement sets out.

**What happens if something breaks?**
DekernAI fails closed. Any error in a decision holds the payment or sends it to your review queue; it never sends. If a rail times out, nothing is resent until the rail gives a definite answer, so no payment can go out twice.

## 8. Final call to action

**Headline:** Held until it's right. Sent exactly once.

**Button:** Book a demo

**Risk reversal:** You sign every step that moves money closer to being sent, and in the shadow phase nothing is sent at all.

## 9. SEO metadata

**Title tag (52 characters):** DekernAI: agentic payment controls for instant payouts

**Meta description (157 characters):** Check every stablecoin and instant bank payout against your own rules before it is sent. Sent once, reconciled and provable. Book a demo.

**Target keywords:**
1. payout controls
2. stablecoin payout risk
3. payment reconciliation software

These keywords are untested. Run `/marketing:seo-audit` to check search volume before you rely on them.
