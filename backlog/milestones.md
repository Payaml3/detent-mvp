# Milestones: build order for Claude Code

**Product:** agentic payment controls in three layers. The prototype milestones build the layers in order:
- **decision** (M1, M2)
- **orchestration** (M3)
- **operations** (M4, M5)
- **proof across all three** (M6, M7)

Work the milestones in order. Inside a milestone, follow the dependencies in `user-stories.md`. Each milestone ends with an **exit check** you can run or demo. Day counts are Must-story estimates for one developer working with Claude Code (Estimate); see `epics.md` for the generated totals.

| # | Milestone | Must stories | Exit check |
|---|---|---|---|
| M0 | **Foundation** | FND-01, 02, 03, 04, 05, 06, 09, OPS-02 | CI is green with the migrations and local chain; the app refuses a mainnet chain ID; the demo login and role switcher work |
| M1 | **Decide** | INT-01 to 04, POL-01 to 05, POL-08, POL-09, AUD-01 | `POST /v1/payment_intents` returns correct execute, escalate and block decisions with reasons for every check in `fixtures/policy`; caps hold under concurrency; the audit chain verifies |
| M2 | **Agent and mandates** | MND-01, MND-02, AGT-01 to 05, DEM-02 | The canonical invoice gives the expected intent; ambiguous variants are flagged; injection variants change nothing; an over-scope agent intent is BLOCKED |
| M3 | **Exactly-once execution and rails** | EXE-01 to 08, MND-03, POL-06, EXC-01, RAL-01 to 07 | On the local chain and banksim: a forced timeout becomes UNKNOWN and then CONFIRMED with one transfer; a reverted tx fails over under the same ID; a BLOCK is never routed; the kill switch stops a batch |
| M4 | **Exceptions and console** | EXC-02 to 07, EXE-09, POL-07, CON-01 to 06, CON-08 | The $18,500 flow is clickable end to end in the console: escalate, raw facts, approve, re-run, send; an overdue case stays held with an outbox update; a rule change needs two approvers |
| M5 | **Ledger, deposits, reconciliation, replay** | LED-01 to 07, AUD-02, CON-07 | The deposit batch credits once each; reconciliation is at 99% or more with a proposed fix; every demo payment replays to the same decision |
| M6 | **Evaluation and release gate** | EVL-01 to 04, 06, 07 | `make eval` passes: 100+ attacks with 0 unauthorised, 30+ faults with 0 duplicates, canonical 10/10; the report is generated; CI blocks on a deliberately injected regression |
| M7 | **Demo-ready prototype** | FND-07, CON-09, DEM-01, 03, 04, 05 | The deployed EU instance runs the 10-minute script from spec/11 on real testnets. **This is the proof-of-work milestone** |
| M8 | **Public sandbox API and webhooks** | API-01 to 06, WHK-01 to 03, EXC-08 | An external client with a test key creates an intent, receives signed webhooks and sees its request logs; the OpenAPI file lints and matches the code |
| M9 | **Dashboard and sandbox** | DSH-01 to 07, DSH-09, DSH-10, SBX-01, 02, 04, RAL-11 | Admin invites a developer, who verifies, gets keys, triggers every test value and sees results in their own console; an expired organisation is locked |
| M10 | **Docs and SDKs** | DOC-01 to 05, SDK-01, SDK-02 | The docs site is live; the quickstart works in 5 minutes; all 8-language snippets pass in CI; both SDKs pass against the sandbox |
| M11 | **Website launch** | WEB-01 to 06 | The site is live with dated results, booking and the access form; the honesty checklist is signed off by the founder |
| M12 | **Should and could haves** | SHD-01 to 04, RAL-08 to 10, EXE-10, OPS-01, 03, 04, AUD-03, CON-10, DEM-06, EXC-09, INT-05, ... | The first free shadow report is produced from a CSV export |

## Parallel work

- The OpenAPI file and the docs drafts (API-05, DOC-01 to 03) can start once M1 fixes the API shape.
- The website copy and layout (WEB-01, WEB-02) don't depend on the engine and can be built at any time. Only WEB-03 waits for the results.
- Shadow mode (SHD) is the first thing to pull forward if a prospect agrees to share an export before M8.

## If time is short (founder decision)

The decomposed Must scope is larger than the earlier top-down estimate (`mvp-scope.md` 22.5 days plus `05-developer-portal.md` 16.5 days). The options are:

1. **Keep the full scope** and plan about 12 weeks.
2. **Prototype first.** Ship M0 to M7 as the proof of work (about 8.5 weeks), then decide on the portal after the first demos.
3. **Trim the prototype.** Candidates to cut or defer:
   - Ethereum Sepolia (RAL-03), keeping one chain and the bank simulator
   - POL-07 two-approver UI (keep it as a config file signed off in git)
   - CON-08 (show rails on the Overview)

   Each cut weakens a demo claim, so list it on the results report.
