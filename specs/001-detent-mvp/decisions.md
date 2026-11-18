# Decisions register: Detent MVP

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
| C-03 | `fail_safe: hold` must hold a payment whose *decision* failed, but RECEIVED has no transition to HELD | spec/01 Fail-safe; POL-09; spec/02 state machine | Add RECEIVED → HELD (reason SYSTEM_UNAVAILABLE) for `hold`; `manual_queue` uses RECEIVED → ESCALATED | **Proposed** |
| C-04 | Sandbox reset "deletes intents, cases, ledger and logs", but ledger and audit rows are never deleted | SBX-04 vs invariant 12, "Things never to do" | Reset starts a new data generation for the sandbox organisation: rows stay, every query filters on the current generation, the audit chain records the reset. No row is deleted | **Open** (needs founder: this touches an invariant) |
| C-05 | Resubmission after block matches "same payee, same amount", but the attack suite expects "tiny amount changes" to be caught | POL-06 AC3 vs spec/09 Block bypass | Match on same counterparty **or** same destination address within the window, any amount → ESCALATE `RESUBMISSION_AFTER_BLOCK` | **Proposed** |
| C-06 | Rule activation: spec/04 needs the compliance lead only for loosening changes; POL-07 records the compliance lead's attestation on every activation | spec/04 Rule changes step 3; POL-07 AC2, AC3 | The compliance lead is one of the two approvers on every activation (satisfies both texts) | **Proposed** |
| C-07 | Owners and deadlines "by tier" and "by type and amount" (EXC-01), but the rule set configures deadlines by case type only and "tier" is never defined | EXC-01 vs spec/04 `deadlines`, `owners` | Tier = deadline class from the rule set (`payout_above_auto_limit` = tier 1, `payout_other` = tier 2, `deposit_exception` = tier 3, `unknown_stuck` = tier 1); no amount bands in the MVP | **Proposed** |
| C-08 | The loosening detector's list differs between spec/04 (six bullets) and POL-07 ("shorter screening scope") | spec/04; POL-07 AC2 | Use the union of both lists | **Proposed** |
| C-09 | Who changes the mode: "payments lead sets the mode" (spec/00) vs "needs the payments lead and the compliance lead" (EXE-09) vs "needs two roles" (spec/07) | spec/00 Personas; EXE-09 AC2; spec/07 Settings | Follow EXE-09: proposed by one, approved by the other. **Note:** the M0 permission table lets either role act alone (`org.change_mode`); it is unused so far and will be changed to two-person approval in EXE-09 | **Proposed** |
| C-10 | Demo says "27 of 28 items matched", but in the batch one payout is blocked and two escalate, so they never move money | spec/11 minute 7 to 9; demo-batch-20.yaml | Count only items that moved money; if both escalations are approved in the demo: 17 + 2 payouts and 8 deposits = 27 items, 26 matched, 1 designed break. Update spec/11 in DEM-05 | **Proposed** (deferred to M5 at the pre-M0 review) |
| C-11 | The policy fixture has keys the spec/04 format lacks: `retry`, `execution.max_decision_age_seconds`, `execution.unknown_stuck_after`, deadline `unknown_stuck`, owner rule `reconciliation` | fixtures/policy/default-policy.yaml vs spec/04 | Adopt the fixture's keys into the spec/04 schema (the fixture is the more complete source) | **Proposed** |
| C-12 | Examples use rule version 3 (spec/03, spec/04); the fixture and demo use version 1 | spec/03, spec/04, fixture, spec/11 | Cosmetic: examples are illustrative; seed version 1 | **Proposed** |
| C-13 | Effort: MVP scope estimated 22.5 + 16.5 days; the decomposed Must backlog is 61.25 days | backlog/milestones.md "If time is short" | Founder chooses option 1 (full scope, ~12 weeks), 2 (prototype first) or 3 (trim). Not yet chosen | **Open** |
| C-14 | The Auditor persona reads the audit log, replays and exports, but the role list has no auditor | spec/00 Personas; spec/02 `users.role` | Add a read-only `auditor` role | **Proposed** |
| C-15 | The rule set blocks KYB status `unknown`, but spec/02 lists only verified, pending, failed | default-policy.yaml `kyb_status`; spec/02 | Allow `unknown` (already in the M0 migration's CHECK) | **Proposed** |
| C-16 | The changed-wallet invoice's expected decision is "ESCALATE or BLOCK", which is not a deterministic test oracle | fixtures/invoices/expected-outputs.yaml | Resolved by G-01: an unregistered address is recorded as a new destination and escalates NEW_WALLET (plus the agent flag) | **Proposed** |
| C-17 | Milestones M1 to M5 build the layers in order, so no money moves end to end until M3 and nothing is clickable until M4; your request asks for small end-to-end milestones | backlog/milestones.md | Re-slice the same stories into vertical slices S1 to S9 ([plan.md](plan.md#milestones), [slices.yaml](slices.yaml)). No story changes, only its milestone | **Proposed** |
| C-18 | `spec/product-definition.md` names "Ralio". If that is a former employer, the file breaks the independence rule and will fail OPS-02 | product-definition.md "Rules for wording"; CLAUDE.md | Founder to confirm; if it is on the denylist, rephrase without the name | **Open** (asked 2026-11-18, unanswered) |
| C-19 | Webhook signing secrets are "hashed and shown once", but Detent must sign every delivery with the plaintext secret, which a hash can't give back | spec/02 `webhook_endpoints`; spec/10 `WEBHOOK_SECRET_PEPPER`; spec/03 signature | Store the secret encrypted with the credentials key (Fernet, as for rail credentials, RAL-09); still shown once | **Proposed** |

## Missing business rules (G)

| ID | Gap | Where it bites | Proposed rule | Status |
|---|---|---|---|---|
| G-01 | An intent names a destination address that isn't registered for the counterparty | spec/03 request carries an address, not a `dst_` ID; changed-wallet invoice; attacks "wallet change race" | Never trust it silently: record it as a new destination (`first_seen_at` = now), so NEW_WALLET escalates; the agent also flags WALLET_DIFFERS_FROM_REGISTRY. No new reason code | **Proposed** |
| G-02 | "The counterparty is told" when a case goes overdue, but counterparties have no contact field | EXC-06; spec/02 `counterparties` | Add a fictional `contact_email` to counterparties; user payouts address the platform's `account_ref`. Outbox only | **Proposed** |
| G-03 | Business-day calendar for `P1BD` | spec/04 `deadline.deposit_exception` | Monday to Friday, UTC, no public holidays in the MVP | **Proposed** |
| G-04 | The backup owner's new deadline after takeover, and what happens if it also passes | EXC-06 AC1 | Same duration as the original deadline, from takeover; a second overdue escalates ownership to the payments lead; the payment stays held throughout | **Proposed** |
| G-05 | Who may approve after the deadline ("approval after deadline by a non-owner" is an attack) | spec/09 Approval abuse | Only the case's current owner (the backup owner after takeover) or the payments lead; never the initiator | **Proposed** |
| G-06 | Which roles may approve or reject exceptions | spec/00 Personas (reviewer owns cases; backup owner takes over) | Reviewer, backup owner, payments lead. **Note:** this is already in the M0 permission table (`exception.approve`) and is unconfirmed; the compliance lead is excluded unless you say otherwise | **Proposed** |
| G-07 | Screening match method (exact or fuzzy) | spec/04 `screening`; screening-list.yaml | Exact match: addresses case-insensitive; names case-folded with whitespace collapsed. No fuzzy matching in the MVP | **Proposed** |
| G-08 | Approval by API: "the approver can't be the initiator", but an API key isn't a person | spec/03 `/exceptions/{id}/approve`; EXC-04 AC3 | Every key is issued to a named user; that user is the actor for approvals and audit | **Proposed** |
| G-09 | Who may click Send in Assist mode, and may the initiator click it | spec/02 Assist mode; spec/03 `/send` scope `exceptions:approve` | Same roles as exception approval (G-06); not the initiator | **Proposed** |
| G-10 | User payouts: destinations of end users and their verification status | spec/04 user payout profile; demo batch p07 to p20 | Seed one destination per user account; the platform supplies a typed `user_verified` flag; false → ESCALATE. **Note:** `user_verified` was added to spec/04 after your approval of the user-payout profile, so that detail is still Proposed | **Proposed** |
| G-11 | Deposit amount tolerance | LED-05 AC1; spec/04 deposit checks | Exact match by default; per-organisation tolerance setting, default 0 | **Proposed** |
| G-12 | Mandate `max_total` period | spec/05 mandate scope | The mandate's whole validity window; counts confirmed plus in-flight; released on FAILED_FINAL, CANCELLED, BLOCKED, REJECTED | **Proposed** |
| G-13 | Above-norm with history in another currency | POL-05; counterparties fixture (Harbor median in EUR) | Compare only with confirmed payments in the same currency; otherwise "not evaluated" | **Proposed** |
| G-14 | Daily cap day boundary | spec/04 `daily_caps` | UTC calendar day | **Proposed** |
| G-15 | After the kill switch is released, do held payments resume automatically | spec/02 HELD → READY; EXE-08 | Automatically: each held payment re-runs the policy (audited); EXECUTE resumes, anything else stays held or escalates | **Proposed** |
| G-16 | Mode change while payments are READY | EXE-09 | The mode is read inside the send lock: a payment READY under Auto waits for a Send click if the mode is now Assist | **Proposed** |
| G-17 | Who may cancel, and until when | spec/02 CANCELLED transitions; INT-05 | Platform via API (`intents:create`) or payments lead in the console; only before SUBMITTED | **Proposed** |
| G-18 | Data in a new sandbox organisation (which payees exist) | SBX, DSH-01 | Seed the fictional counterparties and test values on creation | **Proposed** |
| G-19 | Retention of sandbox data and any personal data entered by developers | spec/08 (request logs 30 days only) | Request logs 30 days; other sandbox data until the organisation expires plus 30 days. Needs your legal review (already a founder input before M8) | **Open** |
| G-21 | How long a deposit intent (its address or reference) stays valid before EXPIRED | spec/03 `/deposit_intents`; data-model deposit states | 7 days, configurable per organisation; a deposit arriving after expiry opens a deposit exception, never a silent credit | **Proposed** |
| G-20 | Webhook retry schedule, give-up point and response timeout | WHK-03; spec/03 "at least once"; spec/08 "send test event" | Exponential: 1 min, 5 min, 30 min, 2 h, 6 h, 24 h, then marked failed and shown in the delivery log; 10 s response timeout; test events carry `"test": true` | **Proposed** |
| G-22 | The investigation agent's possible recommendations | spec/05 example shows only `approve` | approve, reject, needs_info; the recommendation never changes the decision | **Proposed** |

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

### Technical decisions already implemented in M0 (no business rule involved)

UUIDv7 IDs in Crockford base32; Clock with a persisted demo offset; Postgres job queue with a lease and a
fencing check; an engine guard that refuses unscoped queries; composite `(org_id, id)` foreign keys;
`attempts.raw_tx` for re-broadcast; JSON logs with redaction; gitleaks plus the denylist check in CI.
Details: [research.md](research.md).

### Items in the M0 code that depend on Proposed rules

| Code | Rule it encodes | Register item |
|---|---|---|
| `detent/domain/roles.py` `exception.approve`, `exception.reject` | Reviewer, backup owner, payments lead | G-06 |
| `detent/domain/roles.py` `org.change_mode` | Either lead alone (to be replaced by two-person approval) | C-09 |
| `detent/domain/roles.py` `demo.clock.advance` | Any role may fast-forward the demo clock | Proposed here as D-P01 |
| Migration 0001 `exception_cases.resolution` values (approved, rejected, cancelled, superseded) | Case resolutions | Proposed here as D-P02 |
| Migration 0001 `deposit_intents.status` values (OPEN, RECEIVED, CREDITED, EXCEPTION, EXPIRED) | Deposit lifecycle | Proposed here as D-P03 |
| Migration 0001 `recon_breaks.status` values (OPEN, APPROVED, REJECTED, APPLIED) | Break lifecycle | Proposed here as D-P04 |
| Migration 0001 `leads.org_id` = operator organisation `org_detent` | Website leads belong to Detent | Proposed here as D-P05 |
| Migration 0001 `kyb_status` includes `unknown` | | C-15 |

All of these are reversible with a new forward migration if you decide otherwise.

## Questions for the founder, by impact

1. **C-13: scope and timeline.** Full scope (about 12 weeks), prototype first (M0 to M7, about 8.5 weeks), or trim?
2. **C-17: milestone order.** Adopt the end-to-end slices S1 to S9 instead of the layered M1 to M7?
3. **C-04: sandbox reset.** May reset bypass the append-only rule for sandbox organisations, or should it start a new data generation (my proposal)?
4. **C-18:** is "Ralio" a former employer (and on the denylist)?
5. **G-06, G-05, G-08, G-09: approval authority.** Confirm who may approve, approve after a deadline, approve by API and click Send.
6. All other Proposed items: approve as a batch, or list the ones to change.
