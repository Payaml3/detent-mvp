# Landing page: UX structure (DekernAI)

> **Changed 2026-11-28 (D-44):** "Request access" is now the one primary action everywhere; "Book a demo" was removed. Read "Book a demo" below as "Request access".

Status: **Proposed.** Becomes Approved when the founder merges the PR. Scope: the structure, flow and copy
outline of the home page (`apps/site/src/pages/index.astro`). Visuals (palette, type, motif) come from the
design-system work and are applied in a follow-up PR; nothing here changes code yet.

**Amended by B-04 (client journey, `docs/product/client-journey.md`):** there is no free shadow report. The
primary CTA is "Book a demo" and the secondary is "Talk to us"; the offer section (§3.6) becomes the seven
onboarding phases; the nav item "Shadow report" becomes "Onboarding"; `/design-partners/` is the onboarding
page. Shadow is a phase after the contract, on live traffic. Where this document still says otherwise, B-04 wins.

Sources: `spec/08-developer-portal.md` (WEB), `founder/brand.md` (on the brand-name PR #58 branch), `docs/product/shadow-report.md`
(I5), `docs/product/customer-discovery.md` (buying roles), decisions D-15, D-19 to D-21.

## 1. Who the page is for

| Reader | Arrives asking | Needs to leave with | Next step we offer |
|---|---|---|---|
| Head of payments (champion, buyer) | "Will this stop manual reviews and double payouts?" | One payment followed end to end; how onboarding works | Book a demo |
| Compliance lead (can veto) | "Who decides, and can I prove it to an auditor?" | Their rules decide; a block is final; audit and replay | Security page, then the onboarding phases |
| CTO or engineering lead | "How hard is it to plug in, and does it touch our funds?" | One API, sits beside the rails, no custody, sandbox | Docs and sandbox access |

The page has to work for the head of payments first, give compliance a clear answer on "who decides" without
scrolling far, and give engineers a fast exit to the docs.

## 2. What the current page does well, and where it loses people

Keep:
- The live example payment in the hero (one `pay_` ID through every step). It is the strongest proof on the page.
- The irreversible-payments demo (a timeout is UNKNOWN, nothing is resent, one transfer on the rail).
- The honesty discipline: fictional supplier, test network, roadmap items labelled.

Problems:
1. **The main CTA leads nowhere yet.** "Book a demo" points at a placeholder (D-16). The offer a buyer can say
   yes to today, the free shadow report (I5), sits on a sub-page.
2. **The core line is said four times** (hero lead, "How it works" title, "Three layers" lead, hero card footnote).
   Repetition flattens it. Say it once, loudly, then prove it.
3. **"How it works" and "Three layers" explain the same flow twice.** Readers scroll past the second one.
4. **The hero says "payout" only.** The product decides deposits too.
5. **"Measured results" is an empty section before launch.** An empty state on a landing page reads as "nothing
   to show". It belongs on the page only once `results.json` holds dated figures.
6. **Pricing is a decision we haven't made** (D-15: "Talk to us"). A pricing section without prices costs a scroll.
7. **One path for three readers.** Compliance and engineering proof is spread across three sections.
8. **The hero figure is an AI agent** (D-21). With the brand rule "the rules decide, never the AI", putting the
   agent at the centre of the first screen tells the opposite story. See open question Q2.
9. **Eleven sections.** The proposal below has eight.

## 3. Proposed structure

The brand story gives the page its spine: **sift** (decision), **settle** (orchestration), **prove** (operations).

```
NAV       DekernAI · Product · Solutions · Security · Developers · Onboarding   Talk to us [Book a demo]
1 HERO    Headline + category line · CTA pair · live example payment (kept) · honesty strip
2 PROBLEM On rails you can't reverse, every mistake is permanent (4 pains)
3 SPINE   Sift. Settle. Prove.  the three layers, one payment ID, "agents prepare, your rules decide"
  AI TEAM Your AI team comes with the service: three agents, what each does and can't do (CON-11)
4 PROOF   Built for payments you can't take back  (irreversible demo, kept)
5 ROLES   Tabs: Payments · Compliance · Engineering  (absorbs Developers + Security)
6 ONBOARD Seven onboarding phases, owners and exit checks; plans "Talk to us" (B-04)
7 FIT     Who it's for (4 use cases, compact) + FAQ
8 CLOSE   Final CTA + footer
```

### 1. Hero

- **Headline** (pick one, Q3):
  - A. "Every deposit and payout, decided by your rules." (plain, covers both directions)
  - B. "Sift every payment. Settle it once. Prove it after." (brand story, three layers)
  - C. "Your rules decide. DekernAI makes it happen." (tagline option from brand.md)
- **Category line:** "Agentic payment controls: one layer that decides, orchestrates and operates every deposit
  and payout, under your rules."
- **CTAs:** primary "Book a demo"; secondary "Talk to us" (B-04). Engineers get "Read the docs" in the nav, not a third hero button.
- **Visual:** keep the example-payment card player. Replace the AI-agent figure with the "sift then settle"
  motif (many payment dots passing a rule line, one settled outcome), subject to Q2.
- **Honesty strip** under the CTAs, small: "Prototype · test networks only · never holds your funds or keys".
- **First screen must show**, on a 1280×800 laptop and a 390px phone: headline, category line, primary CTA.
  The card player may fall below the fold on phones.

### 2. Problem: "On rails you can't reverse, every mistake is permanent."

Four short cards, each a real failure in plain words: manual review queues that grow with volume; deposits
credited to the wrong balance; a retry that becomes a second payout; a timeout guessed as a failure and resent.
One line under them: "Your rails move the money. The decisions stay with you, and today they're made by hand."

### 3. Spine: "Sift. Settle. Prove."

Three columns that read left to right as one payment's life, with the same `pay_` ID shown in each:

| | Sift (decision) | Settle (orchestration) | Prove (operations) |
|---|---|---|---|
| Question | Should this payment happen? | How and where does it go? | Can you show what happened? |
| Your rules | Execute, escalate or block | Best rail by policy; sent exactly once | Every outcome reconciled and audited |
| Agents do the groundwork | Prepare the intent from the invoice | None: routing and sending follow the rules only | Draft the reconciliation fix |

One statement across the section, said only here: **"Agents prepare. Your rules decide."** This replaces both
"How it works" and "Three layers".

### 3b. AI team: "Your AI team comes with the service." (CON-11, added 28 Nov)

After the rules demo. The three AI agents a client gets, with the same names as the console's AI team page:
the instruction agent (decision), the investigation and reconciliation agents (operations). Each card says what the
agent does, what the client gets and what it can't do. A note says orchestration has no agent, then the built-in
limits (read-only tools, untrusted text as data, a daily AI budget, recorded calls that replay without the model).

### 4. Proof: "Built for payments you can't take back."

Keep the current irreversible demo and its statement ("A failure can retry. A rejection can't. No retry ever
becomes a second payment."). Add the kill switch as a one-line fact here, since it is a mechanics claim.

### 5. Roles: tabs for Payments, Compliance, Engineering

Each tab: three facts and one link. Tabs are buttons with `aria-selected`; without script all three show stacked.

- **Payments:** fewer manual reviews (only escalations reach a person); never paid twice (one ID, one confirmed
  attempt); a kill switch you own. Link: book a demo.
- **Compliance:** your rules, versioned, re-run on approval; a block is final and nobody can override it;
  append-only audit that replays every decision without calling a model. Link: `/security/`.
- **Engineering:** one request returns the decision with a reason per check (current code sample, shortened);
  sits beside your rails and custody; sandbox on test networks. Links: docs, `/access/`.

This absorbs the current Developers and Security sections; the roadmap list (SOC 2 and the rest, all
"planned") moves to `/security/` only.

### 6. Onboarding: "From first call to every rail, in seven phases." (B-04)

The seven phases of `docs/product/client-journey.md`, each with both owners and its exit check; phases 4 to 6
marked "You sign"; the Pilot band over phases 3 to 6. Plans: Pilot, Growth, Scale, "Talk to us", no prices.
The text below described the superseded shadow-report offer and is kept for history only.

The shadow report (I5) as the page's main offer, in three steps: **send** one month's CSV export (DPA signed
first; names hashed on import) · **we decide** every row under your written rules, nothing is sent ·
**you get** the report in 5 working days: decision mix, agreement with your own decisions, unsafe approvals,
unreconciled items. A fictional sample page of the report beside it, labelled "sample, fictional
data". CTA: "Get a free shadow report". Under it, one line: "Paid plans after the pilot. Talk to us." (D-15).
This replaces the Pricing section.

### 7. Fit and FAQ

- **Who it's for**, one compact row: payout platforms, crypto service providers, brokers and prop firms,
  marketplaces, each with one line.
- **FAQ** (5 to 7, collapsible `<details>`): Is DekernAI a payment provider? (No: agentic payment controls,
  beside your rails.) Does the AI approve payments? (No: agents propose; your rules decide.) Do you hold funds
  or keys? Which rails? How does onboarding work? What does it cost?

### 8. Close and footer

Close: one line ("Held until it's right." stays a candidate) and the primary CTA again. Footer per spec/08.

## 4. Behaviour and accessibility

- One primary action colour, used only for "Book a demo". Every other link is secondary.
- Motion: entrance reveals and the card player respect `prefers-reduced-motion` (show the final state).
- Every animated demo has a static, readable final state without script (as today).
- Status chips never rely on colour alone: the state word is always printed.
- Contrast WCAG AA for text and chips in the chosen palette (checked in the design-system work).
- Phone: sections stack in the same order; the role tabs become an accordion; no horizontal scroll at 360px.

## 5. What to measure (once analytics is chosen)

Primary: demo bookings. Secondary: demo bookings, docs and sandbox
clicks from the Engineering tab, scroll depth to the offer section. No tracking ships without the cookie
decision on `/cookies/`.

## 6. Other pages, in order after this one

1. `/design-partners/` is the onboarding page (the seven phases in full, data handling, plans) (B-04).
2. `/product/` and `/security/` follow the same spine (sift, settle, prove) and take the roadmap list.
3. Dashboard, docs and console: a separate pass once the design-system tokens land, since they share components.

## 7. Open questions for the founder

- **Q1.** Make "Get a free shadow report" the primary CTA and "Book a demo" secondary? Recommended: yes, it is the
  one offer that works before the booking link exists, and it is the lead path in the operating model.
- **Q2.** Replace the halftone AI-agent hero figure (D-21) with the "sift then settle" motif? Recommended: yes,
  so the first screen shows rules deciding, not an AI. This would supersede part of D-21.
- **Q3.** Hero headline: A, B or C above. Recommended: A for the headline, B as the section-3 title.
- **Q4.** Hide "Measured results" until `results.json` has dated figures? Recommended: yes.
