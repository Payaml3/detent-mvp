# Epics

Product: agentic payment controls in three layers (decision, orchestration, operations). Each epic's layer is shown.

| Epic | Layer | Track | Goal | Stories | Must | Should | Could | Days |
|---|---|---|---|---|---|---|---|---|
| FND Foundation | All three (foundation) | prototype | A tested, deployable skeleton with the safety guards in place from day one | 9 | 8 | 1 | 0 | 3.75 |
| INT Payment intents | Decision | prototype | Every payment starts as an intent with one payment ID for life | 5 | 4 | 1 | 0 | 2 |
| POL Policy and decisions | Decision | prototype | A deterministic, versioned, client-owned policy layer decides execute, escalate or block | 9 | 9 | 0 | 0 | 5 |
| AGT Mandates and instruction agent | Decision (agents serve all three) | prototype | An AI agent can propose payments from invoices, only inside a signed mandate, and can never move money | 9 | 8 | 1 | 0 | 4 |
| EXE Exactly-once execution | Orchestration | prototype | A payment is sent once: timeouts become UNKNOWN, retries keep the payment ID, the kill switch stops everything | 10 | 9 | 1 | 0 | 5.75 |
| RAL Rails, routing and faults | Orchestration | prototype | Three rails behind one adapter contract, best-rail routing, failover on technical errors only, and fault injection to prove it | 11 | 8 | 3 | 0 | 6 |
| EXC Exceptions and investigation | Operations | prototype | Every escalation has an owner and a deadline, shows raw facts first, and a timeout never becomes an approval | 9 | 8 | 0 | 1 | 4 |
| LED Ledger, deposits and reconciliation | Operations | prototype | One ledger across rails; deposits credited once; mismatches become exceptions with proposed fixes | 8 | 7 | 0 | 1 | 4.25 |
| AUD Audit and replay | Operations | prototype | Every step is recorded append-only and any payment can be replayed and exported | 3 | 2 | 1 | 0 | 2 |
| CON Back-office console | All three (console) | prototype | The screens where the 10-minute demo happens | 10 | 9 | 1 | 0 | 4.75 |
| EVL Evaluation harness | All three (proof) | prototype | Measured proof: attacks, faults, interpretation and agreement, gated in CI and published as a results report | 8 | 6 | 2 | 0 | 4.75 |
| DEM Demo data and scenarios | All three (demo) | prototype | Fictional, repeatable demo data and a one-click scenario runner | 6 | 5 | 1 | 0 | 1.75 |
| SHD Shadow mode | Decision (shadow mode) | prototype | Run decisions on a prospect's exported data and produce the free shadow report | 4 | 0 | 3 | 1 | 2.25 |
| OPS Operational controls | Operations | prototype | The operating-model processes that need software: incidents, independence check, recovery | 4 | 1 | 1 | 2 | 1.25 |
| API Public sandbox API | All three (public API) | portal | A provider-grade API: keys, scopes, errors, versioning, limits, logs, OpenAPI | 7 | 6 | 1 | 0 | 3.75 |
| WHK Webhooks | All three (public API) | portal | Signed, retried, logged event delivery | 3 | 3 | 0 | 0 | 1.25 |
| DSH Developer dashboard | All three (developer access) | portal | Sales-led access, keys, logs, webhooks, sandbox controls, usage and the console per organisation | 10 | 9 | 1 | 0 | 3.5 |
| SBX Sandbox | All three (developer access) | portal | Developers trigger every path with test values, inside quotas | 4 | 3 | 1 | 0 | 1.5 |
| DOC Docs portal | All three (developer access) | portal | Concepts, guides and reference with tested samples in 8 languages | 6 | 5 | 1 | 0 | 4.25 |
| SDK SDKs | All three (developer access) | portal | Typed Python and TypeScript clients with automatic idempotency and webhook helpers | 3 | 2 | 1 | 0 | 2.25 |
| WEB Marketing site | Go-to-market | portal | A public face that looks real and stays honest | 8 | 6 | 2 | 0 | 3.75 |

## Totals (Estimate)

| | Stories | Days |
|---|---|---|
| All stories | 146 | 71.75 |
| Must only | 118 | 61.25 |
| Must, prototype track | 84 | 43 |
| Must, portal track | 34 | 18.25 |

## By milestone

| Milestone | Stories | Must days | All days |
|---|---|---|---|
| M0 Foundation | 9 | 3.25 | 3.5 |
| M1 Decide | 12 | 6.25 | 6.25 |
| M2 Agent and mandates | 9 | 3.75 | 4 |
| M3 Exactly-once execution and rails | 18 | 10 | 10 |
| M4 Exceptions and console | 15 | 7.75 | 7.75 |
| M5 Ledger, deposits, reconciliation, replay | 9 | 5 | 5 |
| M6 Evaluation and release gate | 8 | 4 | 4.75 |
| M7 Demo-ready prototype | 6 | 2.25 | 2.25 |
| M8 Public sandbox API and webhooks | 11 | 5 | 5.25 |
| M9 Dashboard and sandbox | 16 | 4.75 | 5.75 |
| M10 Docs and SDKs | 9 | 6 | 6.5 |
| M11 Website launch | 8 | 3.25 | 3.75 |
| M12 Should and could haves after launch | 16 | 0 | 7 |
