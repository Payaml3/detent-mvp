# Prompts to give Claude Code, one milestone at a time

Paste these one at a time into Claude Code, run from the repository root. Start a fresh session for each milestone, and use plan mode for the first message of each one. Don't move on until the milestone's exit check in `backlog/milestones.md` passes.

## Before M0 (once)

> Read CLAUDE.md, every file in spec/, and backlog/milestones.md. The product is agentic payment controls in three layers (decision, orchestration, operations); keep code packages inside their layer as CLAUDE.md maps them. Don't write code yet. Summarise the invariants in your own words, list anything in the specs that is contradictory or unclear, and propose the exact repository skeleton and Makefile targets for M0. Wait for my approval.

## M0 · Foundation

> Implement milestone M0 from backlog/milestones.md: stories FND-01, FND-02, FND-03, FND-04, FND-05, FND-06, FND-09 and OPS-02, in dependency order. For each story, write the tests from its acceptance criteria first, then the code. Follow spec/02-domain-model.md for the first migration, including the partial unique indexes and the terminal-state and append-only triggers. When done, run `make lint typecheck test`, show me the output, and tick the criteria in backlog/stories.yaml.

## M1 · Decide

> Implement M1: INT-01 to INT-04, POL-01 to POL-05, POL-08, POL-09 and AUD-01. Use fixtures/policy/default-policy.yaml and fixtures/counterparties.yaml. Include a Hypothesis property test for policy determinism and a concurrency test for the daily caps (20 parallel intents). Every decision and state change must write a hash-chained audit event in the same transaction. Finish with the M1 exit check.

## M2 · Agent and mandates

> Implement M2: MND-01, MND-02, AGT-01 to AGT-05 and DEM-02. Follow spec/05-agents.md exactly. Put untrusted text in delimited data blocks and add the post-check that nulls any value not found at its source span. Add the import-linter contract that forbids detent.agents from importing execution, rails or approval code. Write tests that use recorded model responses, so CI doesn't call the API. Add a separate `make eval-interpretation` target that does call it. Run the canonical invoice 10 times and show me the results.

## M3 · Exactly-once execution and rails

> Implement M3: EXE-01 to EXE-08, POL-06, MND-03, EXC-01 and RAL-01 to RAL-07, following spec/02 and spec/06. Build apps/banksim and apps/faultproxy as separate small FastAPI apps. Before writing the sender, list every way a payment could be sent twice and show where each one is prevented: database constraint, lock or rule. Write fault tests on the local chain for timeout_after_forward, timeout_before_forward, receipt_status_0 and a worker crash after broadcast. Finish with the M3 exit check.

## M4 · Exceptions and console

> Implement M4: EXC-02 to EXC-07, EXE-09, POL-07, CON-01 to CON-06 and CON-08, following spec/07-console.md. Raw facts first on the case page; agent content collapsed and visually separate. Make the $18,500 flow clickable end to end. Use Playwright to take screenshots of Overview, Invoice drop, Case and Payment detail, and show them to me.

## M5 · Ledger, deposits, reconciliation, replay

> Implement M5: LED-01 to LED-07, AUD-02 and CON-07. Add a Hypothesis test that the ledger always balances. Run fixtures/batches/demo-batch-20.yaml and the generated 500-item reconciliation set; report the match rates and the proposed fixes. Prove that every demo payment replays to its recorded decision without calling the model.

## M6 · Evaluation and release gate

> Implement M6: EVL-01 to EVL-04, EVL-06 and EVL-07, following spec/09. Write at least 100 attack scenarios and 30 fault scenarios as YAML data in eval/scenarios, using the two examples as templates and covering every category's minimum count. Generate the results report. Then prove the gate works: make a temporary branch that removes the UNKNOWN guard, show me CI failing, and discard the branch.

## M7 · Demo-ready prototype

> Implement M7: FND-07, CON-09, DEM-01, DEM-03, DEM-04 and DEM-05. Deploy to the EU region per spec/10. Run the 10-minute script in spec/11 against Base Sepolia and Ethereum Sepolia and record a short screen capture with Playwright. List anything in the script that didn't match the product, and update spec/11.

## M8 to M11 · Developer portal

> Implement M8 [then M9, M10, M11] from backlog/milestones.md, following spec/03 and spec/08. Keep the sandbox strictly separate from demo data. Check the honesty checklist in spec/08 on every public page, and stop and ask me for the name, domain, email provider and booking link when you need them.

## Any time: a story at a time

> Implement story <ID> from backlog/user-stories.md. Read the specs it traces to first. Write the tests from the acceptance criteria, implement, run the gates, and tick the criteria in backlog/stories.yaml. If the story conflicts with an invariant in CLAUDE.md, stop and tell me instead of working around it.
