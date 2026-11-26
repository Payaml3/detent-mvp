# Client journey and onboarding

Status: **Proposed; the founder approved this journey in the thread on 2026-11-26** ("Approve as proposed").
Merging this PR records it as Approved (B-04). Source: the founder's words "no we dont do that, we will have
their onboarding process", replacing the free shadow report as the entry offer (D-15, superseded by B-04).

## The rule

There is no free pre-sale report. A platform becomes a client through DekernAI's onboarding process: seven
phases, each with an owner and an exit check. The client signs every exit check that moves money closer to
being sent (phases 4 to 6). Shadow mode is a phase **inside** onboarding, on the client's live traffic, after
the contract.

## Phases

| # | Phase | What happens | DekernAI owns | Client owns | Exit check |
|---|---|---|---|---|---|
| 1 | **Discovery** | Discovery call and the 10-minute demo (spec/11); fit check on rails, volumes and how their rules work today | Founder (later the solutions lead) | Head of payments | Both sides want to go ahead; NDA signed |
| 2 | **Contract and due diligence** | DekernAI's own due diligence (KYB) on the client; MSA, DPA, DORA Article 30 annex, the clause that the client owns the rules; agreed pilot scope (rail, volumes, dates) | Founder; counsel (`legal` gate) | Legal, compliance | Contract and DPA signed; pilot scope agreed |
| 3 | **Sandbox integration** | Sales-led org, invites and sandbox keys (spec/08); the client integrates the API and webhooks and triggers every test value (spec/06) | Engineering support | Client engineers | Integration checklist passes in the sandbox |
| 4 | **Policy setup** | Policy workshop: the client's rules become rule set v1 (spec/04); counterparties and allowlists; agent mandates (spec/05); approvers, roles and backup owners; exception tiers and deadlines | Solutions lead | Compliance lead, head of payments | Client compliance lead signs off rule set v1 |
| 5 | **Shadow on live traffic** | Mode 1 Shadow (product model A3): every live payment is decided and recorded, nothing is sent; weekly agreement report against the client's own outcomes | Solutions lead | Payments operations | Client signs the move to Assist: agreement % and zero unsafe approvals |
| 6 | **Go-live** | Mode 2 Assist (staff click every decision), then Mode 3 Auto, on one rail; go-live checklist: kill-switch owner, backup owners, exception tiers, incident runbook (spec/10) | Founder (go-live decision) | Head of payments | Client signs each mode move (Assist, then Auto) |
| 7 | **Scale** | More rails; Mode 4 Orchestrate (routing and failover); reconciliation across rails; support levels and quarterly business reviews | Solutions lead | Head of payments | Reviewed each quarter |

## What this changes

- **Entry offer:** "Book a demo" / "Talk to us" replaces "Get a free shadow report" on the site. The site
  shows these seven phases where it showed the shadow-report offer.
- **Plans:** Pilot, Growth and Scale stay; every plan says "Talk to us" (D-15 otherwise unchanged). The Pilot
  covers phases 3 to 6 on one rail.
- **Shadow mode:** stays (D-24, SHD stories), used on live traffic in phase 5 and, where the client wants it,
  on an exported month during policy setup to calibrate rule set v1. It is never a free pre-sale product.
- **Targets (B7):** "under 10 days from pilot signed to shadow live" now reads as phase 2 exit to phase 5
  start.

## Follow-ups (not in this change)

- Site copy, nav, CTA and the design-partners page, with spec/08 §7, `specs/002-marketing-site` FR-210,
  `founder/landing-page.md` and `docs/design/landing-page-ux.md`: done in the landing redesign work.
- Backlog: reword the SHD epic and stories from "free shadow report" to "shadow phase" in
  `backlog/stories.yaml`, then regenerate.
