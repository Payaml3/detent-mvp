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
| 3 | **Account and sandbox integration** | KYB approved: DekernAI creates the organisation and the account owner gets a registration email; they sign up, invite their team and assign roles; their engineers integrate against the sandbox and trigger every test value (spec/06). See "Account and dashboard flow" | Engineering support | Account owner, client engineers | Client marks the integration ready; DekernAI verifies it |
| 4 | **Policy setup** | Policy workshop: the client's rules become rule set v1 (spec/04); counterparties and allowlists; agent mandates (spec/05); approvers, roles and backup owners; exception tiers and deadlines | Solutions lead | Compliance lead, head of payments | Client compliance lead signs off rule set v1 |
| 5 | **Shadow on live traffic** | Mode 1 Shadow (product model A3): every live payment is decided and recorded, nothing is sent; weekly agreement report against the client's own outcomes | Solutions lead | Payments operations | Client signs the move to Assist: agreement % and zero unsafe approvals |
| 6 | **Go-live** | Mode 2 Assist (staff click every decision), then Mode 3 Auto, on one rail; go-live checklist: kill-switch owner, backup owners, exception tiers, incident runbook (spec/10) | Founder (go-live decision) | Head of payments | Client signs each mode move (Assist, then Auto) |
| 7 | **Scale** | More rails; Mode 4 Orchestrate (routing and failover); reconciliation across rails; support levels and quarterly business reviews | Solutions lead | Head of payments | Reviewed each quarter |

## Account and dashboard flow

Founder's flow (2026-11-26), with policy sign-off and shadow kept before any live send:

1. **KYB approved** (phase 2). DekernAI's admin creates the client's organisation. There is no public sign-up.
2. **Registration email** to the client's account owner: a single-use invite link.
3. **Sign up.** The account owner verifies their email, sets a password and lands in the client dashboard.
4. **One dashboard** holds everything for that client: the developer portal (keys, request logs, webhooks,
   docs), sandbox controls, the policy engine (rule sets, counterparties, mandates) and the console.
5. **Team.** The account owner invites team members and assigns roles and permissions (spec/02 and spec/08: account owner,
   admin, developer, payments lead, compliance lead, reviewer, backup owner, auditor). Two-person rules still apply (spec/04, spec/07).
6. **Sandbox integration.** Engineers use sandbox keys (`sk_test_`) and trigger every test value. The client
   marks the integration ready; DekernAI verifies it against the integration checklist.
7. **Production mode.** Once DekernAI has verified the integration **and** the client's compliance lead has
   signed off rule set v1 (phase 4), the account owner can enable production. Production starts in Shadow
   (phase 5): live payments are decided, nothing is sent. Assist and Auto follow, each signed by the client
   (phase 6).

## What this changes

- **Entry offer:** "Book a demo" / "Talk to us" replaces "Get a free shadow report" on the site. The site
  shows these seven phases where it showed the shadow-report offer.
- **Plans:** Pilot, Growth and Scale stay; every plan says "Talk to us" (D-15 otherwise unchanged). The Pilot
  covers phases 3 to 6 on one rail.
- **Shadow mode:** stays (D-24, SHD stories), used on live traffic in phase 5 and, where the client wants it,
  on an exported month during policy setup to calibrate rule set v1. It is never a free pre-sale product.
- **Targets (B7):** "under 10 days from pilot signed to shadow live" now reads as phase 2 exit to phase 5
  start.

## Where it is specified

- spec/08 (dashboard access, team and roles, integration verification, production mode), spec/02 (roles),
  spec/00 (personas), `specs/001-detent-mvp/spec.md` (W-11, FR-105).
- Stories: DSH-01 to DSH-03 rewritten; DSH-11 team and roles, DSH-12 integration verification (P2);
  DSH-13 production mode (slice L, Could). P1 (API keys) is unchanged: live keys already return
  `live_mode_unavailable`.
- Production mode and live keys are after the MVP: the prototype runs on test networks only (invariant 14).

## Open question for the founder

- **Does production start in Shadow?** This journey (B-04) says yes: production begins in phase 5 with nothing
  sent, then Assist, then Auto. The founder's flow says the client "enables production mode and starts". If
  production should send from day one (straight to Assist), phase 5 moves before production, on sandbox or
  exported data.

## Follow-ups (not in this change)

- Site copy, nav, CTA and the Onboarding page: PR #74 (landing redesign).
