# Decisions register: company

**Rule:** product and engineering decisions go in `specs/001-detent-mvp/decisions.md` (IDs `C-`, `G-`, `A-`, `D-`).
Business, GTM, pricing, brand, legal and hiring decisions go here (IDs `B-nn`, numbered from 01).
Nothing is Approved until the founder approves it in words; quote those words in Source.

Status: **Approved**, **Proposed**, **Assumption** or **Open** (`founder/operating-protocol.md` §3).
Layers: Business → Product → MVP → Architecture → Tasks → Tests → Release.

## Register

| ID | Decision | Status | Date | Source | Affected layers |
|---|---|---|---|---|---|
| B-01 | The brand name is **Dekernai** (from Latin *dēcernere*, to decide), replacing the working name Detent. Domains dekernai.com (primary) and dekernai.co.uk, registered by the founder on 2026-11-26. Story rule: the client's rules decide, never the AI | Approved | 2026-11-26 | Founder, on the decision card "Lock in Dekernai as the brand name now?": "Yes, lock in Dekernai". Evidence: `docs/brand/name-review-2026-11.md` | Business, Product, Release (site, docs, console copy, `BRAND_NAME`) |

## Business decisions already in the specs register (indexed, not moved)

| Topic | See |
|---|---|
| Build the marketing website (P4) before S1, with honest placeholders | see D-14 |
| Pricing: free shadow report, Pilot, Growth, Scale; no prices, "Talk to us" | see D-15 |
| Booking link and access form are marked placeholders until the founder supplies them | see D-16 |
| Name from one setting (working name "Detent"); the domain stays a placeholder | see D-17 (name superseded by B-01) |
| Brand tokens (ink, paper, orange, blue; Space Grotesk, Inter, JetBrains Mono) | see D-18 |
| Website built in-house in a cinematic dark-blue style | see D-19 |
| Site look: halftone-dot detent wheel (references "Flora", "Stackside") | see D-20 (to be revisited for B-01) |
| Hero: halftone-dot agent figure with three layer cards in the founder's wording | see D-21 |
| Site hosted on Vercel, no-index until launch | see D-22 |
