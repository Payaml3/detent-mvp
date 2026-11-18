# Prompts to give Claude Code, one slice at a time

Paste these one at a time into Claude Code, run from the repository root. Start a fresh session for each slice, and use plan mode for the first message of each one. Don't move on until the slice's exit check in `backlog/milestones.md` passes.

The build order is the end-to-end slices in `specs/001-detent-mvp/slices.yaml` (founder decision D-11, 18 Nov 2026). The original layered milestones M0 to M12 are replaced; the prompts below keep their instructions and regroup them by slice. Every slice also follows `specs/001-detent-mvp/`: requirements and their status in `inventory.md`, decisions in `decisions.md`, tests per criterion in `traceability.md`, tasks in `tasks.md`. Never implement a rule marked Proposed or Open in `decisions.md`; ask instead.

## S0 · Foundation (done)

> Implemented on branch `m0-foundation` (FND-01 to FND-06, FND-08, FND-09, OPS-02).

## S1 · A platform payout is decided through the API

> Implement S1: INT-01 to INT-04, POL-01 to POL-04, POL-08, POL-09 and AUD-01. Use fixtures/policy/default-policy.yaml and fixtures/counterparties.yaml. Include a Hypothesis property test for policy determinism and a concurrency test for the daily caps (20 parallel intents). Every decision and state change must write a hash-chained audit event in the same transaction. A decision failure goes RECEIVED → HELD under fail-safe `hold` and RECEIVED → ESCALATED under `manual_queue` (D-09). Match the response shapes in specs/001-detent-mvp/contracts/openapi.yaml. Finish with the S1 exit check.

## S2 · An EXECUTE decision is sent exactly once

> Implement S2: EXE-01 to EXE-04, RAL-01 and RAL-02, following spec/02 and spec/06 and the internal contracts in specs/001-detent-mvp/contracts/internal.md. Before writing the sender, list every way a payment could be sent twice and show where each one is prevented: database constraint, lock or rule. Store the nonce and the signed raw transaction before broadcast. Finish with the S2 exit check on anvil.

## S3 · Escalate, review raw facts, approve with a policy re-run

> Implement S3: POL-05, POL-06, EXC-01, EXC-02, EXC-04, EXC-05, EXC-07, CON-01, CON-03 and CON-04, following spec/07-console.md. Approval re-runs the policy under the rule in spec/04 "Re-runs after approval" (D-01). Resubmission after a block matches the same counterparty or destination address, whatever the amount (D-10). Raw facts first on the case page; agent content collapsed and visually separate. Use Playwright to screenshot the Exceptions queue and the Case page and show them to me.

## S4 · Never paid twice

> Implement S4: EXE-05 to EXE-08, RAL-03 to RAL-07 and CON-08. Build apps/banksim and apps/faultproxy as separate small FastAPI apps. The UNKNOWN resolver re-broadcasts the same signed transaction when the node never saw it, and never signs a new one while UNKNOWN (D-02). Write fault tests on the local chain for timeout_after_forward, timeout_before_forward, receipt_status_0 and a worker crash after broadcast. Finish with the S4 exit check.

## S5 · An AI agent proposes the $18,500 invoice inside a mandate

> Implement S5: DEM-02, MND-01 to MND-03, AGT-01 to AGT-06 and CON-05. Follow spec/05-agents.md exactly. Put untrusted text in delimited data blocks and add the post-check that nulls any value not found at its source span. Add the import-linter contract that forbids detent.agents from importing execution, rails or approval code. Write tests that use recorded model responses, so CI doesn't call the API. Add a separate `make eval-interpretation` target that does call it. Run the canonical invoice 10 times and show me the results, then click through the whole flow in the console.

## S6 · Operations around escalations

> Implement S6: EXC-03, EXC-06, POL-07, EXE-09, CON-02 and CON-06. A timeout never becomes an approval: an overdue case stays held, the counterparty is told through the outbox and the backup owner takes over. A mode change needs the payments lead and the compliance lead (`mode_change_approved` in detent/domain/roles.py). Use Playwright to screenshot Overview, Invoice drop, Case and Payment detail, and show them to me.

## S7 · One ledger, deposits credited once, reconciliation, replay

> Implement S7: LED-01 to LED-07, AUD-02 and CON-07. Add a Hypothesis test that the ledger always balances. Run fixtures/batches/demo-batch-20.yaml and the generated 500-item reconciliation set; report the match rates and the proposed fixes. Prove that every demo payment replays to its recorded decision without calling the model.

## S8 · Proof and release gate

> Implement S8: EVL-01 to EVL-08, following spec/09. Write at least 100 attack scenarios and 30 fault scenarios as YAML data in eval/scenarios, using the two examples as templates and covering every category's minimum count. Generate the results report, including UNKNOWN resolution and decision latency (FR-114). Then prove the gate works: make a temporary branch that removes the UNKNOWN guard, show me CI failing, and discard the branch.

## S9 · Demo-ready prototype

> Implement S9: FND-07, CON-09, DEM-01 and DEM-03 to DEM-05. Deploy to the EU region per spec/10. Run the 10-minute script in spec/11 against Base Sepolia and Ethereum Sepolia and record a short screen capture with Playwright. List anything in the script that didn't match the product, and update spec/11.

## P1 to P4 · Developer portal

> Implement P1 [then P2, P3, P4] from backlog/milestones.md, following spec/03, spec/08 and specs/001-detent-mvp/contracts/. Webhook signing secrets are stored encrypted, not hashed (D-12); sandbox reset starts a new data generation and deletes nothing (D-08). Keep the sandbox strictly separate from demo data. Check the honesty checklist in spec/08 on every public page, and stop and ask me for the name, domain, email provider and booking link when you need them.

## Any time: a story at a time

> Implement story <ID> from backlog/user-stories.md. Read the specs it traces to and its rows in specs/001-detent-mvp/traceability.md first. Write the tests from the acceptance criteria, implement, run the gates, and tick the criteria in backlog/stories.yaml. If the story conflicts with an invariant in CLAUDE.md or depends on a Proposed decision, stop and tell me instead of working around it.
