# Decisions register: Dekernai MVP

**Feature**: [spec.md](spec.md) · **Inventory**: [inventory.md](inventory.md) · **Created**: 2026-11-18

This register separates what the founder's documents **confirm** from what is **proposed** or **open**.
Nothing marked Proposed or Open is treated as a business rule until the founder approves it
(constitution, Principle VII).

| Status | Meaning |
|---|---|
| **Confirmed** | Stated in a source document, or approved by the founder in this project (dated) |
| **Proposed** | My recommendation to close a gap or contradiction. Not binding until approved |
| **Open** | The founder must decide; the documents allow more than one answer |

## Sources and their limits

| Source | Where it is | Read in full? |
|---|---|---|
| Product model (sections A1 to A7) | Extracted into `backlog/model-items.yaml` (one line per item) and `spec/00` | **No.** The original document is not in the package |
| Operating model (B1 to B8) | Extracted into `backlog/model-items.yaml` | **No.** Original not in the package |
| MVP scope (`mvp-scope.md`: launch criteria, section 3 flow, triage) | Extracted into `spec/00` (L1 to L8) and `model-items.yaml` | **No.** Original not in the package |
| Developer portal spec (`venture/05-developer-portal.md`) | Restated in `spec/08`; items in `model-items.yaml` | **No.** Original not in the package |
| `facts.md` (16 and 17 Nov), case study v2 | Cited by `spec/product-definition.md` and one model item | **No.** Not in the package |
| Engineering specs `spec/00` to `spec/11`, `spec/product-definition.md` | Repository | Yes |
| Backlog (146 stories with acceptance criteria), milestones, fixtures, eval templates | Repository | Yes |
| `CLAUDE.md` (17 invariants, definition of done) | Repository | Yes |

**A-01 (assumption, affects everything):** the requirement inventory is built from the extracts above.
Where an extract is one line, the full rule may have more detail that I cannot see. Uploading the four
original documents would let me check every Proposed item below against them.

## Contradictions (C)

| ID | Conflict | Sources | Resolution | Status |
|---|---|---|---|---|
| C-01 | Approval re-runs the policy, but the re-run finds the same escalation reasons (FIRST_PAYMENT, ABOVE_AUTO_LIMIT), so an approved payment re-escalates forever | spec/04 Principles; EXC-04; spec/02 state machine | Re-run executes only if every remaining ESCALATE reason was approved with unchanged evidence; new reasons re-escalate; BLOCK still blocks. Written into spec/04 "Re-runs after approval" | **Confirmed** 2026-11-18 (founder "approve" of pre-M0 item 1) |
| C-02 | `timeout_before_forward` expects a retry, but the resolver has no evidence path when the transaction never left | spec/06 UNKNOWN resolution vs fault table | Resolver re-broadcasts the same signed raw transaction (same hash); never signs a new one while UNKNOWN. Written into spec/06 | **Confirmed** 2026-11-18 (item 2) |
| C-03 | `fail_safe: hold` must hold a payment whose *decision* failed, but RECEIVED has no transition to HELD | spec/01 Fail-safe; POL-09; spec/02 state machine | Add RECEIVED → HELD (reason SYSTEM_UNAVAILABLE) for `hold`; `manual_queue` uses RECEIVED → ESCALATED | **Confirmed** 2026-11-18 (founder, D-09) |
| C-04 | Sandbox reset "deletes intents, cases, ledger and logs", but ledger and audit rows are never deleted | SBX-04 vs invariant 12, "Things never to do" | Reset starts a new data generation for the sandbox organisation: rows stay, every query filters on the current generation, the audit chain records the reset. No row is deleted | **Confirmed** 2026-11-18 (founder, D-08) |
| C-05 | Resubmission after block matches "same payee, same amount", but the attack suite expects "tiny amount changes" to be caught | POL-06 AC3 vs spec/09 Block bypass | Match on same counterparty **or** same destination address within the window, any amount → ESCALATE `RESUBMISSION_AFTER_BLOCK` | **Confirmed** 2026-11-18 (founder, D-10) |
| C-06 | Rule activation: spec/04 needs the compliance lead only for loosening changes; POL-07 records the compliance lead's attestation on every activation | spec/04 Rule changes step 3; POL-07 AC2, AC3 | The compliance lead is one of the two approvers on every activation (satisfies both texts) | **Confirmed** 2026-11-19 (founder, D-30) |
| C-07 | Owners and deadlines "by tier" and "by type and amount" (EXC-01), but the rule set configures deadlines by case type only and "tier" is never defined | EXC-01 vs spec/04 `deadlines`, `owners` | Tier = deadline class from the rule set (`payout_above_auto_limit` = tier 1, `payout_other` = tier 2, `deposit_exception` = tier 3, `unknown_stuck` = tier 1); no amount bands in the MVP | **Confirmed** 2026-11-18 (founder, D-27) |
| C-08 | The loosening detector's list differs between spec/04 (six bullets) and POL-07 ("shorter screening scope") | spec/04; POL-07 AC2 | Use the union of both lists | **Confirmed** 2026-11-19 (founder, D-30) |
| C-09 | Who changes the mode: "payments lead sets the mode" (spec/00) vs "needs the payments lead and the compliance lead" (EXE-09) vs "needs two roles" (spec/07) | spec/00 Personas; EXE-09 AC2; spec/07 Settings | Follow EXE-09: proposed by one, approved by the other. The M0 permission table now enforces this (`mode_change_approved`, tested) | **Confirmed** 2026-11-19 (founder, D-30) |
| C-10 | Demo says "27 of 28 items matched", but in the batch one payout is blocked and two escalate, so they never move money | spec/11 minute 7 to 9; demo-batch-20.yaml | Count only items that moved money; if both escalations are approved in the demo: 17 + 2 payouts and 8 deposits = 27 items, 26 matched, 1 designed break. Update spec/11 in DEM-05 | **Confirmed** 2026-11-20 (founder, D-35) |
| C-11 | The policy fixture has keys the spec/04 format lacks: `retry`, `execution.max_decision_age_seconds`, `execution.unknown_stuck_after`, deadline `unknown_stuck`, owner rule `reconciliation` | fixtures/policy/default-policy.yaml vs spec/04 | Adopt the fixture's keys into the spec/04 schema (the fixture is the more complete source) | **Confirmed** 2026-11-18 (founder, D-23) |
| C-12 | Examples use rule version 3 (spec/03, spec/04); the fixture and demo use version 1 | spec/03, spec/04, fixture, spec/11 | Cosmetic: examples are illustrative; seed version 1 | **Confirmed** 2026-11-24 (founder, D-38) |
| C-13 | Effort: MVP scope estimated 22.5 + 16.5 days; the decomposed Must backlog is 61.25 days | backlog/milestones.md "If time is short" | Founder chose option 2 (prototype first) on 2026-11-20 (D-34), then option 1 (full scope: every slice S0 to S9, P1 to P4 and L) on 2026-11-23 (D-37, supersedes D-34) | **Confirmed** 2026-11-23 (founder, D-37) |
| C-14 | The Auditor persona reads the audit log, replays and exports, but the role list has no auditor | spec/00 Personas; spec/02 `users.role` | Add a read-only `auditor` role | **Confirmed** 2026-11-24 (founder, D-38) |
| C-15 | The rule set blocks KYB status `unknown`, but spec/02 lists only verified, pending, failed | default-policy.yaml `kyb_status`; spec/02 | Allow `unknown` (already in the M0 migration's CHECK) | **Confirmed** 2026-11-18 (founder, D-23) |
| C-16 | The changed-wallet invoice's expected decision is "ESCALATE or BLOCK", which is not a deterministic test oracle | fixtures/invoices/expected-outputs.yaml | Resolved by G-01: an unregistered address is recorded as a new destination and escalates NEW_WALLET (plus the agent flag) | **Confirmed** 2026-11-24 (founder, D-38) |
| C-17 | Milestones M1 to M5 build the layers in order, so no money moves end to end until M3 and nothing is clickable until M4; your request asks for small end-to-end milestones | backlog/milestones.md | Re-slice the same stories into vertical slices S1 to S9 ([plan.md](plan.md#milestones), [slices.yaml](slices.yaml)). No story changes, only its milestone | **Confirmed** 2026-11-18 (founder, D-11) |
| C-18 | `spec/product-definition.md` named a competitor in its wording rules; the founder doesn't want competitor names in the repository | product-definition.md "Rules for wording" | Keep the rule, drop the name: "Avoid the terms 'trust layer' and 'guardrails' (a competitor's wording)". Not a former employer, so no independence issue | **Confirmed** 2026-11-18 (founder: "our competitor and we don't need it here") |
| C-19 | Webhook signing secrets are "hashed and shown once", but Detent must sign every delivery with the plaintext secret, which a hash can't give back | spec/02 `webhook_endpoints`; spec/10 `WEBHOOK_SECRET_PEPPER`; spec/03 signature | Store the secret encrypted with the credentials key (Fernet, as for rail credentials, RAL-09); still shown once | **Confirmed** 2026-11-18 (founder, D-12) |

## Missing business rules (G)

| ID | Gap | Where it bites | Proposed rule | Status |
|---|---|---|---|---|
| G-01 | An intent names a destination address that isn't registered for the counterparty | spec/03 request carries an address, not a `dst_` ID; changed-wallet invoice; attacks "wallet change race" | Never trust it silently: record it as a new destination (`first_seen_at` = now), so NEW_WALLET escalates; the agent also flags WALLET_DIFFERS_FROM_REGISTRY. No new reason code | **Confirmed** 2026-11-18 (founder, D-23) |
| G-02 | "The counterparty is told" when a case goes overdue, but counterparties have no contact field | EXC-06; spec/02 `counterparties` | Add a fictional `contact_email` to counterparties; user payouts address the platform's `account_ref`. Outbox only | **Confirmed** 2026-11-19 (founder, D-30) |
| G-03 | Business-day calendar for `P1BD` | spec/04 `deadline.deposit_exception` | Monday to Friday, UTC, no public holidays in the MVP | **Confirmed** 2026-11-19 (founder, D-31) |
| G-04 | The backup owner's new deadline after takeover, and what happens if it also passes | EXC-06 AC1 | Same duration as the original deadline, from takeover; a second overdue escalates ownership to the payments lead; the payment stays held throughout | **Confirmed** 2026-11-19 (founder, D-30) |
| G-05 | Who may approve after the deadline ("approval after deadline by a non-owner" is an attack) | spec/09 Approval abuse | Only the case's current owner (the backup owner after takeover) or the payments lead; never the initiator | **Confirmed** 2026-11-19 (founder, D-30) |
| G-06 | Which roles may approve or reject exceptions | spec/00 Personas (reviewer owns cases; backup owner takes over) | Reviewer, backup owner, payments lead. **Note:** this is already in the M0 permission table (`exception.approve`) and is unconfirmed; the compliance lead is excluded unless you say otherwise | **Confirmed** 2026-11-18 (founder, D-27) |
| G-07 | Screening match method (exact or fuzzy) | spec/04 `screening`; screening-list.yaml | Exact match: addresses case-insensitive; names case-folded with whitespace collapsed. No fuzzy matching in the MVP | **Confirmed** 2026-11-18 (founder, D-23) |
| G-08 | Approval by API: "the approver can't be the initiator", but an API key isn't a person | spec/03 `/exceptions/{id}/approve`; EXC-04 AC3 | Every key is issued to a named user; that user is the actor for approvals and audit | **Confirmed** 2026-11-18 (founder, D-23) |
| G-09 | Who may click Send in Assist mode, and may the initiator click it | spec/02 Assist mode; spec/03 `/send` scope `exceptions:approve` | Same roles as exception approval (G-06); not the initiator | **Confirmed** 2026-11-19 (founder, D-31) |
| G-10 | User payouts: destinations of end users and their verification status | spec/04 user payout profile; demo batch p07 to p20 | Seed one destination per user account; the platform supplies a typed `user_verified` flag; false → ESCALATE. **Note:** `user_verified` was added to spec/04 after your approval of the user-payout profile, so that detail is still Proposed | **Confirmed** 2026-11-24 (founder, D-38) |
| G-11 | Deposit amount tolerance | LED-05 AC1; spec/04 deposit checks | Exact match by default; per-organisation tolerance setting, default 0 | **Confirmed** 2026-11-19 (founder, D-31) |
| G-12 | Mandate `max_total` period | spec/05 mandate scope | The mandate's whole validity window; counts confirmed plus in-flight; released on FAILED_FINAL, CANCELLED, BLOCKED, REJECTED | **Confirmed** 2026-11-19 (founder, D-29) |
| G-13 | Above-norm with history in another currency | POL-05; counterparties fixture (Harbor median in EUR) | Compare only with confirmed payments in the same currency; otherwise "not evaluated" | **Confirmed** 2026-11-18 (founder, D-23) |
| G-14 | Daily cap day boundary | spec/04 `daily_caps` | UTC calendar day | **Confirmed** 2026-11-18 (founder, D-23) |
| G-15 | After the kill switch is released, do held payments resume automatically | spec/02 HELD → READY; EXE-08 | Automatically: each held payment re-runs the policy (audited); EXECUTE resumes, anything else stays held or escalates | **Confirmed** 2026-11-19 (founder, D-28) |
| G-16 | Mode change while payments are READY | EXE-09 | The mode is read inside the send lock: a payment READY under Auto waits for a Send click if the mode is now Assist | **Confirmed** 2026-11-19 (founder, D-30) |
| G-17 | Who may cancel, and until when | spec/02 CANCELLED transitions; INT-05 | Platform via API (`intents:create`) or payments lead in the console; only before SUBMITTED | **Confirmed** 2026-11-24 (founder, D-38) |
| G-18 | Data in a new sandbox organisation (which payees exist) | SBX, DSH-01 | Seed the fictional counterparties and test values on creation | **Confirmed** 2026-11-24 (founder, D-38) |
| G-19 | Retention of sandbox data and any personal data entered by developers | spec/08 (request logs 30 days only) | Request logs 30 days; other sandbox data until the organisation expires plus 30 days. Needs your legal review (already a founder input before M8) | **Confirmed** 2026-11-24 (founder, D-38; legal review still to come before P4 launch) |
| G-21 | How long a deposit intent (its address or reference) stays valid before EXPIRED | spec/03 `/deposit_intents`; data-model deposit states | 7 days, configurable per organisation; a deposit arriving after expiry opens a deposit exception, never a silent credit | **Confirmed** 2026-11-19 (founder, D-31) |
| G-20 | Webhook retry schedule, give-up point and response timeout | WHK-03; spec/03 "at least once"; spec/08 "send test event" | Exponential: 1 min, 5 min, 30 min, 2 h, 6 h, 24 h, then marked failed and shown in the delivery log; 10 s response timeout; test events carry `"test": true` | **Confirmed** 2026-11-24 (founder, D-38) |
| G-22 | The investigation agent's possible recommendations | spec/05 example shows only `approve` | approve, reject, needs_info; the recommendation never changes the decision | **Confirmed** 2026-11-19 (founder, D-30) |
| G-23 | Who may edit a counterparty's payout details in the console | INT-04 AC3 ("editable in the console"); no role named | Payments lead only (the narrowest choice; the change is audited and the next payment escalates CHANGED_DETAILS). Built this way in S1 | **Confirmed** 2026-11-24 (founder, D-38) |
| G-24 | Which user owns a case when several users have the owner role | EXC-01 "owner assignment rules"; spec/04 `owners` names a role, not a person | The user in that role with the fewest open cases; ties go to the earliest-created user | **Confirmed** 2026-11-18 (founder, D-27) |
| G-25 | Who may resolve an agent proposal's flags before it is submitted | AGT-02 "until a human resolves each flag"; no role named | The same roles that approve exceptions (G-06): reviewer, backup owner, payments lead; the resolution needs a note and is audited. Built this way in S5 | **Confirmed** 2026-11-24 (founder, D-38) |
| G-26 | How "reset demo data" (CON-09) works without deleting audit or ledger rows | CON-09 AC1; D-08; invariant 12 | A new data generation: a fresh fictional organisation seeded from the fixtures; the console follows the newest; the old one keeps its data and has its kill switch engaged; refused while an attempt is in flight; payments lead only. Built this way in S9 | **Confirmed** 2026-11-20 (founder, D-36) |
| G-27 | Which test USDC the live testnet demo uses: the script needs about $20,000 of test USDC per run, and Circle's faucet gives about 20 per request | DEM-04; spec/11; chain/src/MockUSDC.sol (refuses any chain but 31337) | Our own test token, labelled as a stand-in for USDC, deployable on Base Sepolia and Ethereum Sepolia; alternatives: Circle test USDC with smaller amounts, or collect ~1,000 faucet requests | **Confirmed** 2026-11-20 (founder, D-33) |

## Assumptions (A)

| ID | Assumption | Source of the default |
|---|---|---|
| A-01 | The inventory relies on extracts; see "Sources and their limits" | Package contents |
| A-02 | One demo organisation; sandbox organisations are separate and never share data with it | spec/08 "Keep the sandbox strictly separate"; M0 org isolation |
| A-03 | Desktop only, one demo login, cold starts and several seconds of AI delay are acceptable | spec/00 "Can be rough" |
| A-04 | Estimates in specs marked "Estimate" (quotas, latency targets, faucet amounts) are defaults that may change | spec/01, spec/08, spec/10 |
| A-05 | All demo and sandbox data is fictional; no real personal data enters the prototype | spec/00 honesty rules |
| A-06 | The investment-diligence workflow, real rails, custody integration, real screening vendors, cards, ML risk scores, treasury, certifications, SSO and multi-tenant production use are out of scope | spec/00 "Out of scope" |

## Decision log

### Confirmed by the founder

| ID | Decision | Date | Evidence |
|---|---|---|---|
| D-01 | C-01 re-run rule (spec/04 "Re-runs after approval") | 2026-11-18 | "approve" reply to the pre-M0 plan; commit 73de33b |
| D-02 | C-02 resolver re-broadcasts the same transaction (spec/06) | 2026-11-18 | Same; commit 73de33b |
| D-03 | Travel-rule data from organisation settings and the registry, never agents (spec/04) | 2026-11-18 | Same; commit 73de33b |
| D-04 | A user payout profile exists (spec/04), excluding the `user_verified` detail (see G-10) | 2026-11-18 | Same; commit 73de33b |
| D-05 | `counters` table, `VARCHAR(8)` currency, `org_id` on every table (spec/02) | 2026-11-18 | Same; commit b90b953 |
| D-06 | FND-08 (structured logs) is part of M0 | 2026-11-18 | Same; commit 19ed765 |
| D-07 | C-18: the named company is a competitor, not a former employer; keep the wording rule without its name, and keep competitor names out of the repository | 2026-11-18 | Founder reply in this session |
| D-08 | C-04: sandbox reset starts a new data generation; nothing is deleted; audit and ledger stay append-only (SBX-04 criterion rewritten) | 2026-11-18 | Founder answer to the decision questions |
| D-09 | C-03: a failed decision moves RECEIVED → HELD under fail-safe `hold`, RECEIVED → ESCALATED under `manual_queue` (spec/01, spec/02, `domain/states.py`) | 2026-11-18 | Same |
| D-10 | C-05: resubmission after a block matches the same counterparty or the same destination address within the window, whatever the amount (POL-06 criterion rewritten, spec/04) | 2026-11-18 | Same |
| D-11 | C-17: build in end-to-end slices S0 to S9 and P1 to P4; each story's milestone is its slice; milestones.md and the prompts follow them | 2026-11-18 | Same |
| D-12 | C-19: webhook signing secrets are stored encrypted with the credentials key, not hashed; still shown once (spec/02, spec/10) | 2026-11-18 | Same |
| D-13 | EVL-08 (latency benchmark) is promoted from Should to Must | 2026-11-18 | Same |
| D-14 | Build the marketing website (slice P4) before S1; stories whose dependencies aren't built yet (WEB-03 results, WEB-04 tested snippets, WEB-06 access inbox, WEB-07 status page) ship with honest placeholders and stay open | 2026-11-18 | Founder: "can we build first the website landing and its internal pages?" |
| D-15 | Pricing section names the free shadow report, Pilot, Growth and Scale; no prices; every plan says "Talk to us" (resolves the open "prices or Talk to us" question for now) | 2026-11-18 | Founder answer |
| D-16 | Booking link and access form point to clearly marked placeholders in one config file until the founder supplies the booking URL and sales inbox; nothing is sent anywhere | 2026-11-18 | Founder answer |
| D-17 | The site takes the name from one setting (working name "Detent"); the domain stays a placeholder; nothing is deployed | 2026-11-18 | Founder answer |
| D-18 | The site uses the spec/07 brand tokens (ink, paper, orange, blue; Space Grotesk and Inter; JetBrains Mono only for code) | 2026-11-18 | Founder answer |
| D-19 | The website is built in-house in a cinematic dark-blue style modelled on the GetLayers references reviewed (template like "Kelder", 3D scene like "Watch Movement", sections like "Blueprint Tabs", "Relay" and "Segment Stack"); nothing is bought or copied from them. Glows, gradients and WebGL are allowed on the site (overriding the design skill's house rules); the honesty rules still apply in full | 2026-11-18 | Founder: "build it in-house in this style" |
| D-20 | Site look: the founder's references "Flora" (dark night field, one object drawn in light, scroll camera move, huge display line, live readout panel) and "Stackside" (halftone-dot rendering). Built in-house as a halftone-dot detent wheel whose catch holds the payment and releases one tooth when it is sent; the readout shows a real payment's states. Their invented proof (volume figures, user counts, "trusted by") is not reproduced | 2026-11-18 | Founder: "something like this" with screenshots of both |
| D-21 | Hero follows the founder's Stackside reference: a halftone-dot AI agent figure with three cards in the founder's wording (Decision: "Should this payment happen?"; Orchestration: "How and where should it execute?"; Operations: "How is it monitored, reconciled and proven?"). The agent is shown preparing, investigating and reconciling; each card also shows what the rules decided, so the page never implies the AI decides (constitution I, product-definition wording rules). The detent wheel moves to the "Built for irreversible payments" demo | 2026-11-18 | Founder: "can we use this but showing an AI agent ..." with the Stackside screenshot |
| D-22 | The marketing site is hosted on Vercel, built from `apps/site` (vercel.json at the repository root and in apps/site). Until launch every page is no-index and robots.txt disallows all crawlers (`indexable: false` in site.config.mjs); the privacy draft names Vercel as host | 2026-11-18 | Founder: "why not deploy it on vercel" / "vercel is ready" |
| D-23 | Approved for S1: G-01 (an unregistered address becomes a new destination and escalates NEW_WALLET), G-07 (exact screening match, case-insensitive), G-13 (above-norm compares same-currency history only), G-14 (daily caps use the UTC calendar day), C-15 (KYB `unknown` blocks), C-11 (the fixture's extra rule-set keys join the schema), G-08 (every API key is issued to a named user, who is the actor) | 2026-11-18 | Founder answer before S1 |
| D-24 | `POST /v1/decisions` stores its decision against a payment intent in the terminal SHADOWED state (or BLOCKED), so it is audited and can never execute; the contract wording "nothing is created" becomes "nothing is executed" | 2026-11-18 | Founder answer before S1 |
| D-25 | The travel-rule threshold is per currency: 1,000.00 USDC, 1,000.00 GBP and 1,000.00 EUR (`travel_rule.threshold` is a currency map) | 2026-11-18 | Founder answers before S1 |
| D-26 | User payouts (`user_account_ref`) are deferred until G-10 is decided; the API returns 422 `user_payouts_unavailable` until then | 2026-11-18 | Founder answer before S1 |
| D-27 | Approved for S3: G-06 (reviewer, backup owner and payments lead approve or reject; never the initiator), C-07 (tier = deadline class from the rule set; owners by case type, no amount bands), G-24 (owner = fewest open cases in the role) | 2026-11-18 | Founder answers before S3 |
| D-28 | G-15 approved: when the payments lead releases the kill switch, every payment it held re-runs the policy (audited); EXECUTE resumes sending, anything else stays held or goes to the exceptions queue | 2026-11-19 | Founder answer before S4 |
| D-29 | G-12 approved: a mandate's `max_total` counts over the mandate's whole validity window; confirmed plus in-flight payments count, released on BLOCKED, REJECTED, CANCELLED or FAILED_FINAL | 2026-11-19 | Founder answer before S5 |
| D-30 | Approved for S6: C-06 (the compliance lead is one of the two people on every rule activation, and attests), C-08 (loosening = the union of the spec/04 and POL-07 lists), C-09 (a mode change is proposed by one lead and approved by the other), G-02 (fictional counterparty contact_email; outbox only), G-04 (the backup owner gets a deadline of the same length from takeover; a later miss goes to the payments lead; the payment stays held), G-05 (after the deadline only the current owner or the payments lead may approve; never the initiator), G-16 (the mode is read inside the send lock), G-22 (investigation recommends approve, reject or needs_information; advisory only). G-09 (who clicks Send) was not asked and stays Proposed; S6 builds its proposed answer, the narrowest one | 2026-11-19 | Founder answers before S6 |
| D-31 | Approved for S7: G-11 (deposit amounts match exactly; per-organisation tolerance setting, default 0), G-21 (a deposit intent is valid 7 days, configurable per organisation; later arrivals open a deposit exception), G-03 (P1BD = Monday to Friday, UTC, no public holidays), and G-09 confirmed (Send in Assist: reviewer, backup owner or payments lead, never the initiator) | 2026-11-19 | Founder answers before S7 |
| D-32 | The S9 demo batch pays counterparties only: p07 to p20 become payouts to two new fictional counterparties (Lumen Data Services BV on both test chains, Kestrel Print Ltd on Faster Payments); user payouts stay deferred (D-26, G-10) | 2026-11-20 | Founder chose "Keep deferred, use counterparty payouts" on the S9 decision card (thread "Build slice S9 demo prototype") |
| D-33 | G-27: the live testnet demo pays in its own labelled test token: `chain/src/MockUSDC.sol`, renamed "Detent Demo USD (test stand-in, not USDC)", symbol tUSDC, deployable on Base Sepolia (84532) and Ethereum Sepolia (11155111) as well as anvil (31337), reverting on any other chain; only the deployer can mint. `detent demo token deploy` and `fund` set it up; `USDC_ADDRESS_*` point at it for the demo | 2026-11-20 | Founder chose "Our own labelled test token" on the S9 decision card "Which test USDC should the live testnet demo use for the $18,500 payment?" (thread "Build slice S9 demo prototype") |
| D-34 | ~~C-13: prototype first. Ship S0 to S9 as the proof of work, then decide on the developer portal (P1 to P4) after the first demos~~ Superseded by D-37 | 2026-11-20 | Founder chose "Prototype first (S0 to S9)" on the decision card "Choose the MVP scope path (C-13)" (thread "Build slice S9 demo prototype") |
| D-35 | C-10: the demo's match line counts only items that moved money: 24 of 25 as scripted (17 payouts, 8 deposits, one designed break); 26 of 27 if both held escalations are approved before Close the day | 2026-11-20 | Founder chose "Count only money-moving items" on the decision card "How should the demo count matched items (C-10)?" (thread "Build slice S9 demo prototype") |
| D-36 | G-26: "Reset demo data" starts a new data generation: a fresh fictional organisation seeded from the fixtures; the console follows the newest; the old one keeps all its data and has its kill switch engaged; refused while an attempt is in flight (checked under the kill switch lock, in the same transaction as the engage); payments lead only | 2026-11-20 | Founder chose "Confirm G-26, fix PR #6" on the decision card "Confirm G-26 (demo reset makes a new generation) and let me fix PR #6?" (thread "Review open PRs before merging") |
| D-37 | C-13: full scope. Build the whole MVP backlog in slice order: finish S9, then P1 Sandbox API and webhooks, P2 Dashboard and sandbox, P3 Docs and SDKs, P4 Website launch, then L After launch. Supersedes D-34. P1 starts while the S9 live run waits on the founder's accounts and wallets (no P1 story depends on S9; WEB-07 in P4 depends on FND-07) | 2026-11-23 | Founder: "we want to complete the build everything" (thread "Switch Detent to the full MVP build") |
| D-38 | Approved as proposed before P1 and P2: C-12 (examples' rule version 3 is illustrative; the fixture and demo seed version 1), C-14 (add a read-only `auditor` role), C-16 (the changed-wallet invoice escalates NEW_WALLET, per G-01), G-10 (one destination per user account; the platform supplies a typed `user_verified` flag; false escalates), G-17 (cancel by the platform via API with `intents:create` or by the payments lead in the console, only before SUBMITTED), G-18 (a new sandbox organisation is seeded with the fictional counterparties and test values), G-19 (request logs 30 days; other sandbox data until the organisation expires plus 30 days; the founder's legal review of retention is still due before the P4 launch), G-20 (webhook retries at 1 min, 5 min, 30 min, 2 h, 6 h, 24 h, then failed and shown in the delivery log; 10 s response timeout; test events carry `"test": true`), G-23 (payments lead only edits a counterparty's payout details; audited; the next payment escalates CHANGED_DETAILS), G-25 (reviewer, backup owner or payments lead resolve an agent proposal's flags, with a note, audited). With G-10 decided, D-26's deferral can end: user payouts still need building (the API returns 422 `user_payouts_unavailable` until then), and the demo batch stays counterparty-only (D-32) | 2026-11-24 | Founder: "for answer apply all your suggestions" (thread "Switch Detent to the full MVP build") |

### Technical decisions already implemented in M0 (no business rule involved)

UUIDv7 IDs in Crockford base32; Clock with a persisted demo offset; Postgres job queue with a lease and a
fencing check; an engine guard that refuses unscoped queries; composite `(org_id, id)` foreign keys;
`attempts.raw_tx` for re-broadcast; JSON logs with redaction; gitleaks plus the denylist check in CI.
Details: [research.md](research.md).

### Items in the M0 code that depend on Proposed rules

| Code | Rule it encodes | Register item |
|---|---|---|
| `detent/domain/roles.py` `exception.approve`, `exception.reject` | Reviewer, backup owner, payments lead | G-06 |
| ~~`detent/domain/roles.py` `org.change_mode`~~ | Fixed 2026-11-18: replaced by `org.change_mode.propose` plus `mode_change_approved()` (both leads, two different people), as EXE-09 confirms | C-09 |
| `detent/domain/roles.py` `demo.clock.advance` | Any role may fast-forward the demo clock | Proposed here as D-P01 |
| Migration 0001 `exception_cases.resolution` values (approved, rejected, cancelled, superseded) | Case resolutions | Proposed here as D-P02 |
| Migration 0001 `deposit_intents.status` values (OPEN, RECEIVED, CREDITED, EXCEPTION, EXPIRED) | Deposit lifecycle | Proposed here as D-P03 |
| Migration 0001 `recon_breaks.status` values (OPEN, APPROVED, REJECTED, APPLIED) | Break lifecycle | Proposed here as D-P04 |
| Migration 0001 `leads.org_id` = operator organisation `org_detent` | Website leads belong to Detent | Proposed here as D-P05 |
| Migration 0001 `kyb_status` includes `unknown` | | C-15 |

All of these are reversible with a new forward migration if you decide otherwise.

## Questions for the founder, by impact

1. **G-06, G-05, G-08, G-09: approval authority.** Confirm who may approve, approve after a deadline, approve by API and click Send.
2. All other Proposed items: approve as a batch, or list the ones to change.
