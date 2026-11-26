# Operating model

Playbook stage 5 (B Define, with the product model). Gate: founder approves.

**Status: Proposed.** Rebuilt from the one-line extracts of the founder's operating model (sections B1 to B8)
in `backlog/model-items.yaml`. The founder's original is not in the repo; when it is added as
`founder/sources/operating-model.md`, it wins. Business, legal and hiring items are not software and stay
Open until the founder acts on them.

## B1. Legal and entity

| Item | Proposed position | Status |
| --- | --- | --- |
| Entity | UK limited company acting as a technology provider | Open (non-software) |
| Perimeter | Counsel's opinion before the first paid pilot; consider FCA PASS | Open; needs `spend` and `legal` gates |
| Contracts | MSA, DPA, DORA Article 30 annex, a clause that the client owns the rules | Open; `legal` gate |
| Client due diligence | Own due diligence on each client before a pilot | Later |
| Independence | No former-employer documents, names or designs; dated design log; CI denylist (OPS-02) | In place |

## B2. Organisation

Today: the founder plus the AI team in `founder/team.md` (architect, engineer, qa, product, growth,
research), working through tickets. Proposed hiring order once revenue or funding allows: a payments
operations or solutions lead (onboarding and policy workshops), then a second engineer, then compliance
support. Every hire goes through the `hire` gate.

## B3. Core processes

| Process | How it runs | Built |
| --- | --- | --- |
| Lead to shadow report | Discovery call, demo, export received, report delivered in 5 working days | Partly: import, decide and replay exist (S7); the report format is L-slice work |
| Client onboarding | Rail connection, policy workshop, rules signed off, shadow | Partly |
| Mode gates | Weekly agreement report; client signs each move from Shadow to Assist to Auto | Partly |
| Rule changes | Versioned; two approvers; loosening needs the compliance lead | Built (S6) |
| Agent evaluation | Attack and regression suite per release; weekly quality sample | Built (S8) |
| Exceptions | Owner, deadline by tier, held past deadline, counterparty update, backup owner | Built (S3, S6) |
| Kill switch | Client payments lead or DekernAI on-call engages; restart needs client approval | Built (S4) |
| Incidents | Severity levels; Sev 1 for unauthorised execution, wrong credit or duplicate; replay to investigate | Partly |
| Adapter maintenance | Daily contract tests against each rail | Partly |
| Support | Support levels and quarterly business reviews | Open |
| Billing | Monthly; usage measured from the ledger | Partly |

## B4. Partners

- **Rails:** partners; the client holds the accounts. DekernAI connects, never holds.
- **Licensed execution partner:** later, for bank rails (v2).
- **Risk data:** screening vendors on the client's contract; integrate, don't resell.
- **Distribution:** back-office platforms used by brokers and prop firms (later).
- **Infrastructure:** UK or EU hosting, AI model provider, secrets vault.

## B5. Security and resilience

UK or EU cloud region with residency stated; vaulted credentials, least privilege, IP allowlists,
append-only audit, encryption. Assurance path: pen test and security pack, then SOC 2 Type I, then Type II,
then ISO 27001. Targets: 99.9% uptime, p95 decision under 5 s rules-only, RTO under 1 h, no lost decisions.
Per-client fail-safe: hold or manual queue, never execute unchecked.

## B6. Risks

| Risk | Mitigation |
| --- | --- |
| Wrong automatic decision | Client-owned rules; staged modes with signed gates |
| Regulatory reclassification of routing | Perimeter opinion; routing stays policy-driven; never hold funds |
| AI misbehaviour or prompt injection | Read-only tools; data blocks; 100+ attack scenarios gate each release |
| Dependence on one rail or AI provider | Adapter contract; models from settings; rules-only fallback |
| Former-employer claim | Independence rules, denylist, dated design log |

## B7. KPIs

| Area | KPI | Target |
| --- | --- | --- |
| Safety | Unauthorised executions, wrong credits, duplicates | 0 |
| Exceptions | Auto-approved after timeout: 0; resolved by deadline | 95% |
| UNKNOWN | Median time to resolve | Under 15 min |
| Quality | Agreement with client decisions | 95% or more |
| Automation | Share decided without a human | 70% or more |
| Reconciliation | Automatic match rate | 99% or more |
| Reliability | Uptime and p95 latency | B5 targets |
| Commercial | Shadow-to-pilot; pilot-to-paid | 40%; 60% |
| Speed | Pilot signed to shadow live | Under 10 days |
| Economics | Gross margin, net revenue retention | Open |

## B8. Milestones and gates

Quarterly milestones follow the playbook (`founder/playbook.md`) and the 6-week cycles in
`founder/goals.json`. The current cycle's objectives are the operating plan; this page doesn't repeat them.
