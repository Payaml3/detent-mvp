# Traceability: every model item to the stories that deliver it

Status: **mvp** built in this MVP · **partly** software part built now, rest later or manual · **later** a later roadmap phase · **non-software** business, legal or hiring work.

| Code | Source | Item | Status | Stories |
|---|---|---|---|---|
| A1.reviews | Product model A1 | Outcome: fewer manual reviews | mvp | POL-02, EXC-03, EVL-05 |
| A1.deposits | Product model A1 | Outcome: deposits credited once, to the right account | mvp | LED-03, LED-04, LED-05 |
| A1.cost | Product model A1 | Outcome: lower cost and failure rate per payout | mvp | RAL-06, RAL-07 |
| A1.evidence | Product model A1 | Outcome: evidence an auditor accepts | mvp | LED-01, AUD-01, AUD-03 |
| A2.Intent | Product model A2 | Intent module: payment intent with one payment ID for life; agents can only propose | mvp | FND-03, INT-01, INT-05, AGT-01, USR-01, USR-03 |
| A2.Decide | Product model A2 | Decide module: decision API, execute / escalate / block with a reason per check | mvp | POL-02, POL-08, CON-03, USR-02, USR-04 |
| A2.Policy | Product model A2 | Policy module: versioned client-approved rules (KYB, allowlist, limits, KYT, Travel Rule, unusual rules, daily caps) | mvp | INT-04, POL-01, POL-03, POL-04, USR-02 |
| A2.Execute | Product model A2 | Execute module: idempotency, state lock, nonce, balance check, pre-funded limits, kill switch | mvp | INT-02, EXE-01, EXE-02, EXE-03, EXE-04, EXE-08 |
| A2.Exceptions | Product model A2 | Exceptions module: owner, deadline, held on timeout, raw facts first, approval re-runs policy | mvp | FND-04, EXC-01, EXC-03, EXC-04, EXC-08, CON-04 |
| A2.Reconcile | Product model A2 | Reconcile module: one ledger, deposit intents, matching, exceptions with proposed fixes | mvp | LED-01, LED-02, LED-03, LED-05, LED-06, LED-07, CON-07 |
| A2.Prove | Product model A2 | Prove module: audit log, replay, evidence export | mvp | INT-03, AGT-05, AUD-01, AUD-02, AUD-03, CON-03 |
| A2.Connect | Product model A2 | Connect module: rail adapters, connection flow, status normalisation | mvp | RAL-01, RAL-02, RAL-03, RAL-04, RAL-08, RAL-09, CON-08 |
| A2.Route | Product model A2 | Route module: best-rail choice and failover on technical errors only | mvp | RAL-06, RAL-07 |
| A2.Mandate | Product model A2 | Mandate module: agent-proposed intents stay inside a signed scope | mvp | MND-01, MND-02, MND-03, CON-06, CON-11 |
| A2b.rule | Product model A2b | A failure can retry; a rejection can't; no retry can become a second payment | mvp | POL-06, EXE-02, EXE-07 |
| A2b.states | Product model A2b | Payment states SUBMITTED, UNKNOWN, CONFIRMED, FAILED then RETRY, BLOCKED | mvp | FND-03, INT-01, EXE-01, EXE-05 |
| A2b.unknown | Product model A2b | UNKNOWN: nothing is resent until the original's outcome is known | mvp | EXE-05, EXE-06, RAL-05 |
| A2b.no_agent_retry | Product model A2b | The agent never decides to retry | mvp | AGT-03, EXE-07 |
| A2b.timeout_hold | Product model A2b | Timeouts never become approvals | mvp | EXC-06 |
| A2b.raw_facts | Product model A2b | Approvers see raw facts before the agent's summary | mvp | INT-04, POL-05, EXC-02, CON-04 |
| A2b.unusual | Case study v2 | Unusual defined as checkable rules: new wallet, changed details, first payment, above norm; daily caps | mvp | INT-04, POL-04, POL-05 |
| A2b.custody | Product model A2b | Custody boundary: signing and nonces at the client's custody provider in production; testnet keys in prototype | partly | EXE-03, EXE-04, RAL-02 |
| A3.shadow | Product model A3 | Mode 1 Shadow: decisions on exported data, no execution | partly | POL-08, EXE-09, SHD-01, SHD-02 |
| A3.assist | Product model A3 | Mode 2 Assist: live recommendations, staff click every decision | mvp | EXE-09 |
| A3.auto | Product model A3 | Mode 3 Auto: executes within approved rules, only escalations reach humans | mvp | EXE-09 |
| A3.orchestrate | Product model A3 | Mode 4 Orchestrate: routing across 2+ rails | mvp | EXE-09, RAL-06 |
| A3.gates | Product model A3 | Signed gate between modes (agreement %, zero unsafe approvals) | partly | CON-10, SHD-03, DSH-13 |
| A4.fee | Product model A4 | Software fee per payment, not a share of money moved (usage metering) | partly | LED-08 |
| A4.plans | Product model A4 | Plans: Pilot, Growth, Scale, routing add-on (no free shadow report, B-04) | partly | SHD-02, WEB-01 |
| A5.proposes | Product model A5 | The LLM proposes; the policy layer decides; uncertain fields flagged, never guessed | mvp | MND-02, AGT-01, AGT-02, CON-05, EVL-04 |
| A5.tools | Product model A5 | Agent tools are read-only; nothing that moves money | mvp | AGT-03, EXC-03, CON-11, WEB-09 |
| A5.injection | Product model A5 | Free text is data, never instructions; tested by attack suite | mvp | AGT-04, EVL-02 |
| A5.citations | Product model A5 | Every agent claim cites evidence or isn't shown | mvp | AGT-05, EXC-03 |
| A5.gate | Product model A5 | Regression gate: 100+ attack scenarios before every release | mvp | FND-09, EVL-01, EVL-02, EVL-07 |
| A5.data | Product model A5 | Client data not used to train models; UK/EU processing | partly | FND-07, SHD-04 |
| A6.no_custody | Product model A6 | Never hold funds or keys | partly | FND-02 |
| A6.client_rules | Product model A6 | The client owns the rules; we enforce them exactly | mvp | POL-01, POL-07 |
| A6.block_final | Product model A6 | A block is final: no approval or other rail can override it | mvp | POL-02, POL-06, RAL-07, EXC-04 |
| A6.fail_closed | Product model A6 | Fail closed: never execute unchecked | mvp | POL-09 |
| A6.shadow_first | Product model A6 | Prove it on their data first (shadow mode) | partly | SHD-01 |
| A6.retry_rule | Product model A6 | No retry can ever become a second payment | mvp | INT-02, EXE-02, EXE-07, EXC-05 |
| A6.timeout | Product model A6 | A timeout never becomes an approval | mvp | EXC-06 |
| A7.prototype | Product model A7 | Prototype phase: $18,500 flow, execution layer, exceptions, deposits, testnets, simulated bank | mvp | FND-01, RAL-02, RAL-04, DEM-04 |
| A7.beta | Product model A7 | Design-partner beta: shadow on real exports, CSV/API import, 1 real read-only adapter | partly | SHD-01 |
| A7.v1 | Product model A7 | v1: Assist/Auto for real, 2 real adapters, multi-tenant, roles, SOC 2 Type I | later | — |
| A7.v2 | Product model A7 | v2: routing module live, bank rails via licensed partner, FXBO/B2CORE | later | — |
| A7.v3 | Product model A7 | v3: AP2-style signed mandates, shared risk signals | later | — |
| B1.entity | Operating model B1 | UK limited company as technology provider | non-software | — |
| B1.perimeter | Operating model B1 | Perimeter opinion before first paid pilot; FCA PASS | non-software | — |
| B1.contracts | Operating model B1 | MSA, DPA, DORA Art. 30 annex, policy-ownership clause | partly | POL-07, SHD-04, WEB-05 |
| B1.client_dd | Operating model B1 | Own due diligence on each client | later | — |
| B1.independence | Operating model B1 | No former-employer documents, names or designs; dated design log | mvp | DEM-01, OPS-02 |
| B2.org | Operating model B2 | Organisation by stage and hiring priority | non-software | — |
| B3.lead_shadow | Operating model B3 | Lead to contract: discovery, demo, NDA, KYB and contract (B-04) | partly | DEM-05, SHD-01, SHD-02, WEB-02 |
| B3.onboarding | Operating model B3 | Client onboarding (B-04): KYB, owner sign-up, team and roles, sandbox integration and verification, policy sign-off, shadow, go-live | partly | POL-07, RAL-09, DSH-01, DSH-11, DSH-12, DSH-13 |
| B3.mode_gates | Operating model B3 | Weekly agreement report; client signs each mode move | partly | EXE-09, SHD-03 |
| B3.rule_changes | Operating model B3 | Rule changes versioned, two approvers, loosening needs compliance lead | mvp | FND-04, POL-01, POL-07, CON-06 |
| B3.agent_eval | Operating model B3 | Attack and regression suite per release; weekly quality sample | mvp | EXC-09, EVL-01, EVL-07 |
| B3.exceptions | Operating model B3 | Exceptions handling: owner, deadline by tier, held past deadline, counterparty update, backup owner | mvp | FND-05, EXC-01, EXC-06, EXC-07 |
| B3.kill_switch | Operating model B3 | Kill switch by client payments lead or on-call; restart needs client approval | mvp | FND-04, EXE-08 |
| B3.incident | Operating model B3 | Incident severity; Sev 1 for unauthorised execution, wrong credit or duplicate; replay for investigation | partly | FND-08, EXE-10, AUD-02, OPS-01 |
| B3.adapters | Operating model B3 | Adapter maintenance: daily contract tests | partly | RAL-08, RAL-10 |
| B3.support | Operating model B3 | Support levels and QBRs | non-software | — |
| B3.billing | Operating model B3 | Monthly billing, usage measured from the ledger | partly | LED-08 |
| B4.rails | Operating model B4 | Rails as partners, client holds accounts | mvp | RAL-01 |
| B4.exec_partner | Operating model B4 | Licensed execution partner | later | — |
| B4.risk_data | Operating model B4 | Screening vendors on the client's contract (integrate, don't resell) | partly | POL-03 |
| B4.backoffice | Operating model B4 | Back-office distribution (FXBO, B2CORE) | later | — |
| B4.infra | Operating model B4 | UK/EU hosting, AI models, secrets vault | mvp | FND-07, AGT-06 |
| B5.hosting | Operating model B5 | UK or EU cloud region; residency stated | mvp | FND-07, WEB-02 |
| B5.security | Operating model B5 | Vaulted credentials, least privilege, IP allowlists, append-only audit, encryption | partly | FND-01, FND-08, RAL-09, AUD-01, OPS-04, API-01 |
| B5.assurance | Operating model B5 | Pen test and security pack, SOC 2 Type I then II, ISO 27001 | later | OPS-04 |
| B5.resilience | Operating model B5 | 99.9% uptime, p95 decision <5s rules-only, RTO <1h, no lost decisions | partly | FND-06, EVL-08, OPS-03 |
| B5.failsafe | Operating model B5 | Per-client fail-safe: hold or manual queue, never execute unchecked | mvp | POL-09, CON-10 |
| B6.wrong_decision | Operating model B6 | Risk: wrong automatic decision (client rules, staged modes) | mvp | EXE-09 |
| B6.reclass | Operating model B6 | Risk: regulatory reclassification of routing | non-software | — |
| B6.ai | Operating model B6 | Risk: AI misbehaviour or prompt injection | mvp | AGT-03, AGT-04, EVL-07 |
| B6.dependence | Operating model B6 | Risk: dependence on one rail or AI provider | partly | AGT-06, RAL-01 |
| B6.former_employer | Operating model B6 | Risk: former-employer claim | mvp | DEM-01, OPS-02 |
| B7.safety | Operating model B7 | KPI: 0 unauthorised executions, wrong credits, duplicates | mvp | EXE-10, EVL-02, EVL-03 |
| B7.exceptions | Operating model B7 | KPI: 0 auto-approved after timeout; 95% resolved by deadline | mvp | EXC-06, CON-02 |
| B7.unknown | Operating model B7 | KPI: median time to resolve UNKNOWN < 15 min | mvp | EXE-06, CON-02 |
| B7.quality | Operating model B7 | KPI: agreement with client decisions >= 95% | partly | EXC-09, EVL-05 |
| B7.automation | Operating model B7 | KPI: share decided without a human >= 70% | mvp | CON-02, EVL-06 |
| B7.recon | Operating model B7 | KPI: automatic match rate >= 99% | mvp | LED-06 |
| B7.reliability | Operating model B7 | KPI: uptime and p95 latency | partly | EVL-08, WEB-07 |
| B7.commercial | Operating model B7 | KPI: demo-to-contract (Open), pilot-to-paid 60% | non-software | — |
| B7.speed | Operating model B7 | KPI: <10 days pilot signed to shadow live | non-software | — |
| B7.economics | Operating model B7 | KPI: gross margin, NRR | non-software | — |
| B8.milestones | Operating model B8 | Quarterly milestones and gates | non-software | — |
| L1 | MVP launch criteria | $18,500 invoice correct 10/10; ambiguous invoice flagged, never guessed | mvp | AGT-01, AGT-02, EVL-04, DEM-02 |
| L2 | MVP launch criteria | 0 unauthorised executions across 100+ attack scenarios | mvp | AGT-04, EVL-02 |
| L3 | MVP launch criteria | 0 duplicate payments across 30+ fault cases; same payment ID on every retry/switch | mvp | FND-09, INT-02, EXE-02, RAL-05, EXC-05, EVL-03 |
| L4 | MVP launch criteria | Timeout -> UNKNOWN, nothing resent; kill switch holds pending | mvp | EXE-05, EXE-08, RAL-05, EVL-03 |
| L5 | MVP launch criteria | Block never re-routed; technical failure fails over under same ID | mvp | POL-06, RAL-07, EVL-03 |
| L6 | MVP launch criteria | Overdue escalation held + counterparty update; approval re-runs policy; raw facts first | mvp | EXC-02, EXC-04, EXC-06 |
| L7 | MVP launch criteria | >= 99% deposits auto-matched; exceptions show proposed fix | mvp | LED-05, LED-06, CON-07, DEM-03 |
| L8 | MVP launch criteria | Every payment replayable; console labelled prototype/testnets/simulated bank | mvp | FND-02, AUD-02, CON-01 |
| MVP.flow | MVP scope section 3 | 10-minute demo flow (invoice -> escalation -> approval -> timeout -> batch -> report) | mvp | FND-05, CON-05, CON-09, EVL-06, DEM-01, DEM-02, DEM-03, DEM-05 |
| MVP.shadow_csv | MVP scope triage | Shadow-mode CSV import (should have) | mvp | SHD-01 |
| MVP.scenarios | MVP scope triage | Scenario packs per platform type (should have) | mvp | CON-09, DEM-06 |
| D.site | Developer portal 2 | Marketing site, 11 sections + 3 sub-pages | mvp | EVL-06, WEB-01, WEB-02, WEB-03, WEB-04, WEB-08 |
| D.honesty | Developer portal 2 | Honesty guardrails (no logos, badges, licence claims; dated results) | mvp | CON-01, EVL-06, WEB-01, WEB-02, WEB-03 |
| D.docs | Developer portal 3 | Docs portal structure, concepts, guides, reference, changelog | mvp | API-05, DOC-01, DOC-02, DOC-03, DOC-05, DOC-06 |
| D.samples | Developer portal 3 | Code samples in 8 languages, tested in CI | mvp | DOC-04, WEB-04 |
| D.sdks | Developer portal 3 | Python and TypeScript SDKs, Postman, OpenAPI download | mvp | API-05, SDK-01, SDK-02, SDK-03 |
| D.sales_led | Developer portal 4 | KYB-gated access: org created by admin after KYB, owner invite, email verify, team and roles, evaluation expiry | mvp | DSH-01, DSH-02, DSH-03, DSH-10, DSH-11, DOC-05, WEB-06 |
| D.keys | Developer portal 4 | Test keys: create, roll, revoke, shown once, hashed, scoped; live disabled | mvp | API-01, DSH-04 |
| D.logs | Developer portal 4 | Request logs with idempotency key and payment ID | mvp | API-06, DSH-05 |
| D.webhooks | Developer portal 4/6 | Webhooks: endpoints, secret, test event, delivery log, HMAC signature, retries | mvp | API-07, WHK-01, WHK-02, WHK-03, DSH-06 |
| D.sandbox | Developer portal 4/5 | Sandbox controls, test values, simulated and real test-network rails | mvp | MND-02, RAL-11, DSH-07, DSH-12, SBX-01, SBX-03, SBX-04 |
| D.usage | Developer portal 4 | Usage against quotas | mvp | LED-08, DSH-08 |
| D.console | Developer portal 4 | Back-office console inside the dashboard | mvp | DSH-09 |
| D.abuse | Developer portal 5 | Abuse limits: rate limits, daily caps, wallet limits, expiring keys | mvp | AGT-06, API-04, DSH-03, SBX-02 |
| D.standards | Developer portal 6 | API standards: auth, idempotency, errors, pagination, versioning, rate limits | mvp | INT-02, INT-03, EXC-08, API-01, API-02, API-03, API-04, API-05, API-07, DOC-06 |
| D.ops_pages | Developer portal 1/7 | Status page, legal pages, analytics, booking and access form | mvp | DSH-10, WEB-05, WEB-06, WEB-07 |
| BR.category | facts.md 16 and 17 Nov | Category wording: 'agentic payment controls' in three layers (decision, orchestration, operations); never 'payments company' | mvp | CON-01, DOC-02, WEB-01, WEB-08, WEB-09 |

Coverage check: every **mvp** and **partly** item has at least one story (enforced by the build script). mvp: 79, partly: 22, later: 7, non-software: 9
