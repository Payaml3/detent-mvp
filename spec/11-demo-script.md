# 11 · The 10-minute demo (matches the built screens, DEM-05)

**Product:** agentic payment controls in three layers: decision, orchestration and operations (see `AGENTS.md`). **This spec covers:** a demo that shows all three layers: decision (escalation and approval), orchestration (best rail, timeout to UNKNOWN, never paid twice) and operations (held overdue case, reconciliation, replay).

Every screen named below is in the console nav. Every "Demo" step is one button on the **Demo** screen (CON-09), and each runs once per demo generation. The same steps run from the command line as `detent demo run <id>`.

**Before the demo (10 minutes ahead):**
1. Open the app 2 minutes early so it wakes (the free web service sleeps). `/healthz` must show `database`, `base-sepolia` and `eth-sepolia` as `ok`.
2. Run `detent demo check`: every wallet line must say `OK` (test USDC and gas for one full run; it says what to top up and where). Once per network, the demo's own test token is deployed with `detent demo token deploy` and topped up with `detent demo token fund` (D-33).
3. Act as **Priya (payments lead)**, open **Demo** and click **Reset demo data**. This starts a new data generation; nothing is deleted. Then act as Priya again.
4. On **Demo**, click **Download the invoice** (it is also offered after the first scenario) so the $18,500 invoice is ready to drop.

| Minute | Screen | What the viewer sees | What to say |
|---|---|---|---|
| 0 to 1 | Overview, then Rails and Mandates | A fictional platform (Demo Platform Ltd, fictional): rules v1, the rails Base Sepolia, Ethereum Sepolia and the simulated bank (Faster Payments and SEPA Instant), an AP agent with a signed mandate. Banner: prototype, test networks, simulated bank rail. Footer: the hosting and database regions | "This is payment controls for money you can't take back. The AI proposes; your rules decide." |
| 1 to 3 | Invoices | Drop the $18,500 USDC invoice from Bluefin Components (fictional). The agent's fields appear with their source text; no flags; the mandate covers it. Click **Submit as agent**. (Shortcut: Demo, **The $18,500 invoice**, then open the proposal) | "The agent can only propose, inside a mandate you signed. It has no way to send money." |
| 3 to 4 | Exceptions, then the case | The decision is ESCALATE: FIRST_PAYMENT and ABOVE_AUTO_LIMIT ($18,500 against a $10,000 auto limit). Owner: the reviewer; 2-hour deadline. Raw facts first: the full wallet address, first seen 41 days ago, never changed. The agent's cited evidence below, collapsed | "Your reviewer sees the facts before the AI's opinion. Unusual means checkable rules." |
| 4 to 6 | Demo, then the case, then Payment detail | Demo: **Forced timeout** (the next chain send reaches the chain but its answer is lost). Act as **Sam (reviewer)** and approve with a reason. Policy re-runs, so EXECUTE; routed to Base Sepolia. The attempt goes UNKNOWN; nothing is resent; the resolver finds the receipt, so CONFIRMED. One attempt, one transaction, with the explorer link | "A timeout is never a failure. We wait for the chain. A retry can never become a second payment." |
| 6 to 7 | Demo, then Exceptions and Outbox | Demo: **20-payment batch with deposits**. Two payouts escalate: Quill Studio's bank details changed 3 days ago, and Nova Freelance Collective is unverified on a new wallet. Click **+1d** on the demo clock: both cases are overdue, so they stay held (never approved by the timeout), the counterparty gets an update in the Outbox, and the backup owner (Lea) is assigned | "A timeout never becomes an approval." |
| 7 to 9 | Payments, then Demo, then Reconciliation | Payments: the batch on three rails; one block (Example Sanctioned Trading Co, screening hit, never re-routed, no attempt); p08 (75.42 USDC) reverts on Base Sepolia and fails over to Ethereum Sepolia under the same payment ID. Demo: **Close the day** (bank statements, then reconciliation): 24 of 25 money-moving items matched (17 payouts and 8 deposits; the block and the two held escalations never moved money) and one designed break, dep-07, a deposit sent to another user's address, with a proposed fix. Act as Priya and approve the fix. Open any payment and click **Replay** | "One ledger across rails. Every payment can be replayed. The 99% match rate is measured on the 500-item evaluation set." |
| 9 to 10 | Demo, then the release-gate report | Demo: **Attack sample**: a screened payee is blocked, forcing the block to send is refused, the agent's $60,000 proposal above its mandate is blocked, and an injected invoice only produces flags. Then the results report from the latest release-gate run (`report.html`, the CI artifact of `detent eval`): 0 unauthorised executions in 120 attacks; 0 duplicates in 52 faults; dated, test-network, synthetic | "Would you share one month of anonymised exports for a free shadow report?" |

**The signal:** a "yes" to starting onboarding (KYB, then the sandbox; B-04). Praise for the demo isn't the signal.

**Notes:**
- The match line counts only items that moved money (C-10, Confirmed as D-35). If the presenter approves both escalations before Close the day, the line reads 26 of 27 (covered by a test).
- The Evaluation screen in the console is not built yet (it says so); show the report file instead.
- Agent answers are hand-written stand-ins, labelled as such on screen, until an `ANTHROPIC_API_KEY` is set and real runs are recorded.
- On the live test networks the "USDC" is the demo's own test token, tUSDC ("DekernAI Demo USD, test stand-in, not USDC"; D-33); say so if asked. Local runs use the same contract on anvil.
- Every name in the demo is invented and labelled fictional. The batch pays counterparties only: user payouts are deferred (D-26, D-32).
