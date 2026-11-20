# Founder status

Last updated: 2026-11-20

Statuses follow `founder/operating-protocol.md` §3: Approved, Proposed, Assumption, Open.

## Objectives (Open, for the founder to fill)

- **Open:** company objectives for this quarter (customer, commercial, fundraising).
- **Open:** what "demo-ready" must prove, and to whom, by when.

## Where the build is

- **Slices done:** S0 to S8, all on `main` (prototype engine plus the S8 proof and release gate).
- **S9:** code built and rehearsed locally (scenario runner, reset, demo check, health check, Render blueprint); the deployed EU instance and the live testnet run wait on the founder items below.
- **Criteria done:** 219 of 308 with evidence (`make spec`, 2026-11-20). 103 requirements: 98 confirmed, 5 proposed.
- **Next:** finish S9 live (deploy, fund wallets, run spec/11 on the Sepolias), then P1 Sandbox API.
- **After that:** P1 Sandbox API, P2 Dashboard, P3 Docs and SDKs, P4 Website launch, L After launch.

## Top risks

1. **No customer evidence yet.** Pricing, positioning and the first design partners are Open (`founder/business-context.md`).
2. **Agent figures are stand-ins.** With no `ANTHROPIC_API_KEY`, every agent answer is a labelled hand-written stand-in, so the interpretation and agreement scores measure Detent's checks, not a model.
3. **Real testnet runs are missing.** RAL-02/03 (Sepolia) and RAL-07 (switching networks) need funded wallets. S9 depends on them.
4. **Concurrency gap.** Parallel intents can deadlock on the audit head and counter rows. The loser fails closed and nothing is paid twice, but a burst can return some 500s.
5. **Prototype is not production.** The gaps carried forward are POL-06 retry and re-route endpoints, EXC-07 incident notices, CON-03 route display, the untested CON-05 PDF path, the DSH-03 dashboard half, manual refund payouts, bank deposits pending until the statement import, and the flaky `test_banksim.py::test_contract`.
6. **Source documents are absent.** The product model, operating model, MVP scope and portal spec exist only as extracts (`founder/sources/README.md`).

## Open founder items

| Item | Owner | Needed by |
|---|---|---|
| `ANTHROPIC_API_KEY`, also as a GitHub secret for the nightly eval (AGT-01, EVL-04) | Founder | S9 |
| Funded test wallets for Base Sepolia and Ethereum Sepolia: a sender and a demo payer on each (RAL-02, RAL-03, DEM-04) | Founder | S9 live run |
| Render (Frankfurt) and Neon (EU) accounts, the plans (worker is not on Render's free plan: Proposed), the `render.yaml` secrets (FND-07) | Founder | S9 live run |
| Testnet RPC endpoints and wallets as secrets for the nightly eval (EVL-07 criterion 0) | Founder | S9 |
| C-13 scope choice; C-10, C-12, C-14, C-16, G-10, G-17 to G-20, G-23, G-25 still Proposed or Open | Founder | S9 (C-10, C-13), P1 to P2 (rest) |
| Publish measured results on the website (`detent eval publish`, EVL-06 criterion 1) | Founder, then Claude | P4 |
| Booking URL, inbox, final name and domain (`BRAND_NAME`), legal review of the site | Founder | P4 |
| Delete the merged branches (`m0-foundation`, `s1-decision-layer`, `s2-send-once`, `s3-review-loop`, `s3-unknown-resolved`, `s4-unknown-resolved`, `s5-agent-mandates`, `s6`, `s7`, `claude/project-thread-uhabrn`, `spec/001-detent-mvp`, `web/002-marketing-site`) | Founder | S9 |

## This week's focus (Proposed)

- **Proposed:** close the four S9 blockers (denylist secret, API key, funded wallets, the C-10 and C-13 choices), then start S9.
- **Proposed:** answer the business-context questions so P4 copy and pricing rest on evidence.
