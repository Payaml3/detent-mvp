# North Star and cycle C1 objectives

**Status: Proposed.** The data lives in `founder/goals.json` (decision gate: merging the pull request with
the founder-approved label is the approval). This page explains the choices; `python tools/goals.py show`
prints the live tree and the dashboard's Goals tab shows progress.

Built from, in order: `problem-validation.md` → `customer-discovery.md` → `business-model.md` →
`product-model.md`, `operating-model.md` → `mvp-scope.md`.

## Company goal (horizon June 2027)

Prove that UK and EU platforms holding user balances will run their real payouts through DekernAI's payment
controls, and sign the first paid pilot.

## North Star

**Real platform payments decided by DekernAI per week (shadow or live).** Baseline 0, target 5,000 a week by
30 June 2027.

- **Why this metric:** it moves only when a platform trusts DekernAI with its own data, which is the riskiest
  assumption (H8). Demo runs and synthetic evaluations don't count. It grows through the same path as the
  business model: onboarding (KYB, sign-up, sandbox, policy), then shadow, then live modes (B-04).
- **Why 5,000:** roughly one mid-sized design partner in Assist mode, or two or three in shadow. This is an
  **assumption**; revisit at the end of C1 with the volumes interviewees report.
- **Guardrail metrics (never traded for growth):** 0 unauthorised executions, 0 wrong credits, 0 duplicates
  (operating model B7).

## Cycle C1: 30 Nov 2026 to 10 Jan 2027 (6 weeks)

The holidays fall inside this cycle; interview targets assume about four working weeks of outreach.

| Objective | Owner | Key results | Key actions |
| --- | --- | --- | --- |
| **O1 Prove the pain with real platforms** | research | O1.1 8 problem interviews logged (proves stage 2) · O1.2 5 confirm H1 and H2 unprompted (proves stage 1) · O1.3 3 platforms agree to share a 30-day export | I1 list 20 ICP leads, book 8 calls · I2 run the script, log within 24 h · I3 synthesise after 5 · I4 ask every interviewee for an export |
| **O2 Turn interest into the first design partner** | product | O2.1 1 design partner through KYB and signed up in the dashboard (B-04) · O2.2 3 follow-up demos from the deployed EU instance · O2.3 founder decides stages 3 and 5 (proves stage 3) | I5 shadow report format (SHD) · I6 second meeting with compliance and demo · I7 test a pilot fee range · I8 founder decides the strategy docs |
| **O3 Make the product demo-ready and integrable** | engineer | O3.1 spec/11 runs end to end on the deployed EU instance (proves stage 16) · O3.2 P1 criteria from 2 to 16 of 16 | I9 founder items for S9 · I10 deploy and live testnet run (DEM) · I11 P1 story groups (API) |

## How the tree connects

- O1 and O2 test the business; O3 keeps the approved build (D-37) moving so the demo and sandbox are ready
  when the second meetings happen. Build alone doesn't move the North Star.
- Every key action becomes a ticket with the labels `goal:O<n>` and `initiative:I<n>` once this is approved
  (`tools/tickets.py new --initiative I<n>`), owned by the role named above.
- Outreach (I1, I6) needs the `external` gate; a counsel opinion or paid tools need `spend`; any price shown
  to a customer needs `pricing`.

## End-of-cycle review

On 10 January 2027: score each key result, mark the hypotheses in `problem-validation.md`, decide stage 1
and 2 (Passed, Deferred or pivot), then draft C2 with `okr-plan` and `python tools/goals.py cycle`.
