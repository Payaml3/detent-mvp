# Milestones: build order for Claude Code

**Product:** agentic payment controls in three layers. The build order is a series of **end-to-end slices**
(founder decision D-11, 18 Nov 2026): each slice runs from a request or a click through the layers it needs and ends
in an exit check you can run or demo. The slices, their stories and exit checks are defined in
[`specs/001-detent-mvp/slices.yaml`](../specs/001-detent-mvp/slices.yaml); each story's `ms` field is its slice.
`tools/build_backlog.py` and `tools/build_spec.py` both fail if a story depends on a story in a later slice.

Work the slices in order. Inside a slice, follow the dependencies in `user-stories.md`. Day counts are backlog
estimates for one developer working with Claude Code (Estimate); see `epics.md` for the generated totals.

| Slice | Delivers | Must stories | Must days | Exit check |
|---|---|---|---|---|
| S0 | **Foundation (done)** | FND-01, FND-02, FND-03, FND-04, FND-05, FND-06, FND-09, OPS-02 | 3.25 | CI green with migrations and the local chain; mainnet chain IDs and live keys refused; demo login and role switcher work. |
| S1 | **A platform payout is decided through the API** | INT-01, INT-02, INT-03, INT-04, POL-01, POL-02, POL-03, POL-04, POL-08, POL-09, AUD-01 | 5.75 | POST /v1/payment_intents returns the correct EXECUTE, ESCALATE or BLOCK with a reason for every check across the fixture counterparties (Harbor executes, Quill escalates CHANGED_DETAILS, Nova escalates, the flagged payee is blocked); the same Idempotency-Key twice creates one payment; 20 parallel intents at the daily cap never all pass; a failing dependency never gives EXECUTE; the audit chain verifies. |
| S2 | **An EXECUTE decision is sent exactly once** | EXE-01, EXE-02, EXE-03, EXE-04, RAL-01, RAL-02 | 3.75 | On anvil: an EXECUTE payout sends one MockUSDC transfer and reaches CONFIRMED under its pay_ ID; a BLOCKED one sends nothing; the kill-switch flag or an insufficient balance holds the payment before sending; parallel send triggers produce one transaction. |
| S3 | **Escalate, review raw facts, approve with a policy re-run** | POL-05, POL-06, EXC-01, EXC-02, EXC-04, EXC-05, EXC-07, CON-01, CON-03, CON-04 | 4.75 | A first payment escalates FIRST_PAYMENT into a case with owner and deadline; in the console the reviewer sees the full address and history before anything else, approves with a reason, the re-run executes and one transfer is sent; a second parallel approval gets 409; approving or resubmitting a blocked payment never sends. |
| S4 | **Never paid twice** | EXE-05, EXE-06, EXE-07, EXE-08, RAL-03, RAL-04, RAL-05, RAL-06, RAL-07, CON-08 | 5.25 | On the local chain and banksim: a forced timeout becomes UNKNOWN and then CONFIRMED with one transfer; a reverted transaction fails over under the same payment ID; a block is never routed; the kill switch stops a batch and only the payments lead releases it. |
| S5 | **An AI agent proposes the $18,500 invoice inside a mandate** | DEM-02, MND-01, MND-02, MND-03, AGT-01, AGT-02, AGT-03, AGT-04, AGT-05, CON-05 | 4.5 | Dropping the canonical invoice gives the expected proposal with source highlights and no flags (10 of 10 runs with recorded responses); submit as agent escalates FIRST_PAYMENT and ABOVE_AUTO_LIMIT; approval sends it once; ambiguous variants are flagged; the injection variant changes nothing; an over-scope intent is BLOCKED. |
| S6 | **Operations around escalations** | EXC-03, EXC-06, POL-07, EXE-09, CON-02, CON-06 | 3.75 | An overdue case stays held, the counterparty update is in the outbox and the backup owner has it; the investigation shows only cited claims; a loosening rule change cannot activate without the compliance lead; Shadow sends nothing and Assist waits for Send. |
| S7 | **One ledger, deposits credited once, reconciliation, replay** | LED-01, LED-02, LED-03, LED-04, LED-05, LED-06, LED-07, AUD-02, CON-07 | 5 | The demo deposits credit once each (the duplicate notification included); reconciliation reaches 99% or more on the 500-item set with a proposed fix per break; the ledger always balances; every demo payment replays to its decision without a model call. |
| S8 | **Proof and release gate** | EVL-01, EVL-02, EVL-03, EVL-04, EVL-06, EVL-07, EVL-08 | 4.25 | make eval passes: 100+ attacks with 0 unauthorised, 30+ faults with 0 duplicates, canonical invoice 10/10; the dated report is generated; CI blocks a deliberately injected regression. |
| S9 | **Demo-ready prototype in the EU** | FND-07, CON-09, DEM-01, DEM-03, DEM-04, DEM-05 | 2.25 | The deployed EU instance runs spec/11 end to end on Base Sepolia and Ethereum Sepolia; mismatches are fixed in spec/11. |
| P1 | **Public sandbox API and webhooks** | API-01, API-02, API-03, API-04, API-05, API-06, WHK-01, WHK-02, WHK-03, EXC-08 | 5 | An external client with a test key creates an intent, receives signed webhooks and sees its request logs; the OpenAPI file lints and matches the code. |
| P2 | **Dashboard and sandbox** | DSH-01, DSH-02, DSH-03, DSH-04, DSH-05, DSH-06, DSH-07, DSH-09, DSH-10, DSH-11, DSH-12, SBX-01, SBX-02, SBX-04, RAL-11 | 5.75 | Admin invites an account owner after KYB, who signs up and invites a developer with a role; the developer gets keys, triggers every test value and sees results in their own console; DekernAI verifies the integration; an expired evaluation organisation is locked. |
| P3 | **Docs and SDKs** | DOC-01, DOC-02, DOC-03, DOC-04, DOC-05, SDK-01, SDK-02 | 6 | The docs site is live; the quickstart works in 5 minutes; all 8-language snippets pass in CI; both SDKs pass against the sandbox. |
| P4 | **Website launch** | WEB-01, WEB-02, WEB-03, WEB-04, WEB-05, WEB-06 | 3.25 | The site is live with dated results, booking and the access form; the honesty checklist is signed off by the founder. |
| L | **After launch (Should and Could)** | - | 0 | A shadow-phase report is produced from a CSV export and the mode-gate sign-off is recorded. |

## Parallel work

- The OpenAPI file and the docs drafts (API-05, DOC-01 to 03) can start once S1 fixes the API shape; the target contract is `specs/001-detent-mvp/contracts/openapi.yaml`.
- The website copy and layout (WEB-01, WEB-02) don't depend on the engine and can be built at any time. Only WEB-03 waits for the results.
- Shadow mode (SHD) is the first thing to pull forward if a prospect agrees to share an export before P1.

## Scope: the full MVP (C-13 Confirmed 2026-11-23, D-37: option 1, full scope)

The founder chose the full scope on 2026-11-23 ("we want to complete the build everything"), superseding D-34
(prototype first, 2026-11-20). Every slice in the table above is in scope and is built in order:

1. **S9** Demo-ready prototype in the EU: the code is merged; the deploy and live testnet run wait on the founder
   (Render and Neon accounts, funded test wallets, `ANTHROPIC_API_KEY`).
2. **P1** Public sandbox API and webhooks. It starts now, while the S9 live run waits: no P1 story depends on S9.
3. **P2** Dashboard and sandbox.
4. **P3** Docs and SDKs.
5. **P4** Website launch. WEB-07 depends on FND-07, so P4 closes after the S9 deploy.
6. **L** After launch (Should and Could).

Remaining after S8, from `epics.md`: about 2.25 days (S9), 5.25 (P1), 6.75 (P2), 6.5 (P3), 3.75 (P4) and 7.25 (L) of
Must and Should work, about 30 days for one developer with Claude Code. The P1 and P2 rules (C-12, C-14, C-16,
G-10, G-17 to G-20, G-23, G-25) were approved as proposed on 2026-11-24 (D-38).

The options weighed under C-13 were:

1. **Keep the full scope** and plan about 12 weeks. **Chosen (D-37).**
2. **Prototype first.** Ship S0 to S9 as the proof of work, then decide on the portal (P1 to P4) after the first demos. Chosen 2026-11-20 (D-34), superseded.
3. **Trim the prototype.** Candidates to cut or defer:
   - Ethereum Sepolia (RAL-03, S4), keeping one chain and the bank simulator
   - POL-07 two-approver UI (S6; keep it as a config file signed off in git)
   - CON-08 (S4; show rails on the Overview)

   Each cut weakens a demo claim, so list it on the results report.
