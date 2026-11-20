# 11 · The 10-minute demo (update to match the built screens, DEM-05)

**Product:** agentic payment controls in three layers: decision, orchestration and operations (see `AGENTS.md`). **This spec covers:** a demo that shows all three layers: decision (escalation and approval), orchestration (best rail, timeout to UNKNOWN, never paid twice) and operations (held overdue case, reconciliation, replay).

**Before the demo:** open the app 2 minutes early so it wakes. Run `detent demo check` for wallet balances. Reset the demo data.

| Minute | Screen | What the viewer sees | What to say |
|---|---|---|---|
| 0 to 1 | Overview | A fictional platform: rules v1, 3 rails (Base Sepolia, Ethereum Sepolia, simulated bank), an AP agent with a mandate. Banner: prototype, test networks | "This is payment controls for money you can't take back. The AI proposes; your rules decide." |
| 1 to 3 | Invoice drop | Drop the $18,500 USDC invoice. Fields appear with source highlights; no flags; the mandate covers it. "Submit as agent" | "The agent can only propose, inside a mandate you signed. It has no way to send money." |
| 3 to 4 | Case | The decision is ESCALATE: FIRST_PAYMENT and ABOVE_AUTO_LIMIT ($18,500 against a $10,000 auto limit). Owner and 2-hour deadline. Raw facts first: the full wallet address, first seen 41 days ago, never changed. The agent's cited evidence below | "Your reviewer sees the facts before the AI's opinion. Unusual means checkable rules." |
| 4 to 6 | Case, then payment detail | Approve with a reason. Policy re-runs, so EXECUTE. Routed to Base Sepolia (scores shown). The forced timeout makes the attempt UNKNOWN. Nothing is resent. The resolver finds the receipt, so CONFIRMED, with the explorer link | "A timeout is never a failure. We wait for the chain. A retry can never become a second payment." |
| 6 to 7 | Demo, then Exceptions | Fast-forward 3 hours on a second escalation: it is held, the counterparty gets an update (Outbox), and the backup owner is assigned | "A timeout never becomes an approval." |
| 7 to 9 | Demo, then Reconciliation | Run the 20-payment batch with deposits: three rails, one block (never re-routed), one failover under the same payment ID, 27 of 28 items matched and one designed break with a proposed fix (the 99% match rate is measured on the 500-item evaluation set). Approve it. Replay any payment | "One ledger across rails. Every payment can be replayed." |
| 9 to 10 | Evaluation | The results report: 0 unauthorised executions in 100+ attacks; 0 duplicates in 30+ faults; dated, test-network, synthetic | "Would you share one month of anonymised exports for a free shadow report?" |

**The signal:** a "yes" to the shadow report. Praise for the demo isn't the signal.
