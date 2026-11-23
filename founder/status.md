# Founder status

Last updated: 2026-11-23

Statuses follow `founder/operating-protocol.md` §3: Approved, Proposed, Assumption, Open.

## Objectives (Open, for the founder to fill)

- **Open:** company objectives for this quarter (customer, commercial, fundraising).
- **Open:** what "demo-ready" must prove, and to whom, by when.

## Where the build is

- **Slices done:** S0 to S8, all on `main` (prototype engine plus the S8 proof and release gate).
- **S9:** code built and rehearsed locally (scenario runner, reset, demo check, health check, Render blueprint); the deployed EU instance and the live testnet run wait on the founder items below.
- **Criteria done:** 219 of 308 with evidence (`make spec`, 2026-11-20). 103 requirements: 98 confirmed, 5 proposed.
- **Operating system (22 Nov):** the solo-to-scale plugin is enabled (#10), the AI team roles come from the plugin (#11, reverted by #12), and the handoff is refreshed (#9). No product code changed this week.
- **Next:** finish S9 live (deploy, fund wallets, run spec/11 on the Sepolias), then P1 Sandbox API.
- **After that:** P1 Sandbox API, P2 Dashboard, P3 Docs and SDKs, P4 Website launch, L After launch.

## Top risks

1. **No customer evidence yet.** Pricing, positioning and the first design partners are Open (`founder/business-context.md`).
2. **Agent figures are stand-ins.** With no `ANTHROPIC_API_KEY`, every agent answer is a labelled hand-written stand-in, so the interpretation and agreement scores measure Detent's checks, not a model.
3. **Real testnet runs are missing.** RAL-02/03 (Sepolia) and RAL-07 (switching networks) need funded wallets. S9 depends on them.
4. **Concurrency gap.** Parallel intents can deadlock on the audit head and counter rows. The loser fails closed and nothing is paid twice, but a burst can return some 500s.
5. **Prototype is not production.** The gaps carried forward are POL-06 retry and re-route endpoints, EXC-07 incident notices, CON-03 route display, the untested CON-05 PDF path, the DSH-03 dashboard half, manual refund payouts, bank deposits pending until the statement import, and the flaky `test_banksim.py::test_contract`.
6. **Scheduled sessions run without the plugin.** The cloud session for the 2026-11-23 weekly review could not load the solo-to-scale plugin (its repository is outside the session's GitHub scope), so it used the last repo copy of the `weekly-review` skill and skipped `publish-views`.
7. **Source documents are absent.** The product model, operating model, MVP scope and portal spec exist only as extracts (`founder/sources/README.md`).

## Open founder items

| Item | Owner | Needed by |
|---|---|---|
| `ANTHROPIC_API_KEY`, also as a GitHub secret for the nightly eval (AGT-01, EVL-04) | Founder | S9 |
| Funded test wallets for Base Sepolia and Ethereum Sepolia: a sender and a demo payer on each (RAL-02, RAL-03, DEM-04) | Founder | S9 live run |
| Render (Frankfurt) and Neon (EU) accounts, the plans (worker is not on Render's free plan: Proposed), the `render.yaml` secrets (FND-07) | Founder | S9 live run |
| Testnet RPC endpoints and wallets as secrets for the nightly eval (EVL-07 criterion 0) | Founder | S9 |
| C-12, C-14, C-16, G-10, G-17 to G-20, G-23, G-25 still Proposed or Open | Founder | P1 to P2 |
| Publish measured results on the website (`detent eval publish`, EVL-06 criterion 1) | Founder, then Claude | P4 |
| Booking URL, inbox, final name and domain (`BRAND_NAME`), legal review of the site | Founder | P4 |
| Let scheduled sessions load the solo-to-scale plugin: add `Payaml3/solo-to-scale` to the cloud environment's repositories | Founder | next weekly review |
| Confirm the `INDEPENDENCE_DENYLIST` secret is set for the OPS-02 CI check | Founder | S9 |
| Delete the merged branches (`m0-foundation`, `s1-decision-layer`, `s2-send-once`, `s3-review-loop`, `s3-unknown-resolved`, `s4-unknown-resolved`, `s5-agent-mandates`, `s6`, `s7`, `claude/project-thread-uhabrn`, `spec/001-detent-mvp`, `web/002-marketing-site`, and since 2026-11-20 `ops/operating-system`, `ops/leaner-os`, `ops/enable-solo-to-scale`, `claude/project-thread-li5pkd`, `-rbgh7v`, `-bzfdtj`, `-zjuwnv`, `-jhkdgn`, `-7ez3r4`); and the unmerged leftovers `add-spec-kit` and `claude/project-thread-5z58f0` (PR #5, closed) | Founder | S9 |

## This week's focus (Proposed)

- **Proposed:** close the S9 live-run blockers (Render and Neon accounts with the `render.yaml` secrets, four funded test wallets, `ANTHROPIC_API_KEY`), then run spec/11 live on the Sepolias and mark S9 done. The S9 code is already on `main`.
- **Proposed:** answer the business-context questions so P4 copy and pricing rest on evidence.
