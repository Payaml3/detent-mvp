# 04 · Policy

**Product:** agentic payment controls in three layers: decision, orchestration and operations (see `CLAUDE.md`). **This spec covers:** the **decision** layer.

## Principles

- **Deterministic.** The same inputs and the same rule version always give the same decision. There are no model calls in the policy.
- **Typed inputs only.** The policy reads intent fields, counterparty facts, mandate state, screening results and counters. It never reads agent free text.
- **Precedence.** BLOCK beats ESCALATE, and ESCALATE beats EXECUTE. Every check runs, so the reviewer sees every reason. The mandate check runs first and short-circuits to BLOCK if the mandate is invalid, because the remaining checks would act on an unauthorised request.
- **Fail closed.** An exception inside any check gives ESCALATE `SYSTEM_UNAVAILABLE`, handled by the organisation's `fail_safe` setting.
- **Versioned and owned by the client.** Rule sets are YAML documents. Each one is immutable once active and needs two approvers.

## Rule-set format

See `fixtures/policy/default-policy.yaml` for the full example. The schema is in `detent/policy/schema.py`.

```yaml
version: 3
platform: demo-platform
currency_defaults: {USDC: 6, GBP: 2, EUR: 2}
fail_safe: manual_queue          # or hold
checks:
  mandate_scope: {enabled: true}                 # agent-sourced intents only
  kyb_status: {block_on: [failed, unknown], escalate_on: [pending]}
  allowlist: {escalate_if_not_listed: true}
  screening: {provider: mock, block_on_hit: true}
  travel_rule: {threshold: {USDC: "1000.00", GBP: "1000.00", EUR: "1000.00"}, required: [originator.name, originator.account, beneficiary.name, beneficiary.account]}
  allowed_networks: {USDC: [base-sepolia, eth-sepolia], GBP: [banksim-fps], EUR: [banksim-sepa-inst]}
  limits:
    auto_limit: {USDC: "10000.00", GBP: "5000.00", EUR: "5000.00"}     # above -> ESCALATE
    hard_max:   {USDC: "100000.00", GBP: "50000.00", EUR: "50000.00"}  # above -> BLOCK
  daily_caps:                                    # routine payments, confirmed + in-flight
    platform: {USDC: "50000.00"}
    per_counterparty: {USDC: "20000.00"}
  unusual:
    new_wallet_days: 7
    changed_details_days: 14
    first_payment: escalate
    above_norm_multiplier: 3.0                   # vs counterparty median of confirmed payments
    above_norm_min_history: 3                    # not evaluated with fewer confirmed payments
  resubmission_after_block: {window_hours: 24, action: escalate}
deadlines:
  payout_above_auto_limit: PT2H
  payout_other: PT4H
  deposit_exception: P1BD                        # 1 business day
owners:
  - {match: {type: payout}, owner_role: reviewer, backup_role: backup_owner}
  - {match: {type: deposit}, owner_role: reviewer, backup_role: payments_lead}
  - {match: {type: unknown_stuck}, owner_role: payments_lead, backup_role: oncall}
```

## Checks

| Check | Result | Reason code | Evidence stored |
|---|---|---|---|
| mandate_scope | BLOCK | MANDATE_MISSING, MANDATE_SIGNATURE_INVALID, MANDATE_EXPIRED, MANDATE_REVOKED, MANDATE_PAYEE_OUT_OF_SCOPE, MANDATE_AMOUNT_EXCEEDED, MANDATE_TOTAL_EXCEEDED, MANDATE_NETWORK_OUT_OF_SCOPE | mandate ID, limit, usage |
| kyb_status | BLOCK or ESCALATE | KYB_FAILED, KYB_PENDING | status and date |
| allowlist | ESCALATE | NOT_ALLOWLISTED | counterparty ID |
| screening | BLOCK | SCREENING_HIT | list entry matched (address or name) |
| travel_rule | ESCALATE | TRAVEL_RULE_MISSING | missing fields |
| allowed_networks | BLOCK | NETWORK_NOT_ALLOWED | network and currency |
| limits.auto_limit | ESCALATE | ABOVE_AUTO_LIMIT | amount and limit |
| limits.hard_max | BLOCK | ABOVE_HARD_MAX | amount and maximum |
| daily_caps | ESCALATE | DAILY_CAP_PLATFORM, DAILY_CAP_COUNTERPARTY | used, this payment and cap |
| unusual.new_wallet | ESCALATE | NEW_WALLET | full address, first_seen_at |
| unusual.changed_details | ESCALATE | CHANGED_DETAILS | old and new address, last_changed_at, changed_by |
| unusual.first_payment | ESCALATE | FIRST_PAYMENT | payment count = 0 |
| unusual.above_norm | ESCALATE | ABOVE_NORM | amount, median, ratio (only with at least `above_norm_min_history` confirmed payments) |
| resubmission_after_block | ESCALATE | RESUBMISSION_AFTER_BLOCK | blocked payment ID. Matches the same counterparty or the same destination address within the window, whatever the amount (D-10) |
| system | ESCALATE | SYSTEM_UNAVAILABLE | dependency and error class |

**Deposit checks** (LED-05) reuse the same engine with a deposit profile:

- token and network match (BLOCK on a mismatch, then a deposit exception)
- sender screening (BLOCK on a hit)
- amount tolerance against the deposit intent (ESCALATE)

## Re-runs after approval (EXC-04, EXE-03)

A re-run evaluates every check again with the active rule version. Without a rule for what the approval already covered, the reasons that caused the escalation (for example FIRST_PAYMENT and ABOVE_AUTO_LIMIT) would still hold and the payment would escalate forever. So:

- The approval records the escalation reasons the approver saw, as `approved_reasons` on the next decision.
- The re-run gives **EXECUTE** only if every remaining ESCALATE reason is in `approved_reasons` and the evidence behind it is unchanged (same amount, destination and counterparty facts).
- **A new reason**, or changed evidence behind an approved one (for example, the destination changed after approval), escalates again and opens a new case.
- **Any BLOCK still blocks.** An approval never covers a BLOCK.
- The pre-send re-check in the execution layer applies the same rule with the same `approved_reasons`.
- **As built (S8):** the pre-send re-check runs when the decision is older than `max_decision_age_seconds`, when the active rule version changed, **or when the destination's address or masked account differs from the one in the last decision's inputs** (found by the wallet-change race attacks; before S8 a destination edited after the decision was paid on the old decision).

## Travel-rule data (travel_rule check)

The threshold is per currency (D-25); a payment above the threshold for its own currency needs every required field.

The travel-rule fields are typed data, never agent free text:

- **Originator:** the platform's own registered name and account, from organisation settings.
- **Beneficiary:** the counterparty's registered name and the destination's address or account, from the counterparty registry.
- A platform-sourced intent can supply `travel_rule` itself; the supplied values must match the registry, or the check escalates `TRAVEL_RULE_MISSING`.

An agent-proposed intent never supplies travel-rule data. Only registry data is used, so the $18,500 demo intent passes this check.

## User payouts (payouts to the platform's own end users)

A payout with `user_account_ref` instead of `counterparty_id` uses a **user payout profile**:

- **Skipped:** kyb_status, allowlist, unusual.first_payment and unusual.above_norm. These checks are about business counterparties.
- **Kept:** screening of the destination, allowed_networks, limits, daily caps (platform scope), unusual.new_wallet and unusual.changed_details on the user's destination, and resubmission_after_block.
- **Platform's job:** the end user's own KYC stays with the platform, which is accountable for it. The policy only reads the platform's typed `user_verified` flag, and it escalates if the flag is false.

## Counters and concurrency

Daily caps and mandate totals use one row per (org, scope, day) in `counters`, updated with `UPDATE ... RETURNING` inside the decision transaction. Concurrent decisions serialise on that row. The amount counted is confirmed plus in-flight (READY, SUBMITTED or UNKNOWN). It is released on FAILED_FINAL, CANCELLED, BLOCKED or REJECTED.

## Rule changes (POL-07)

1. A user with the payments_lead or compliance_lead role creates a draft from the active version.
2. The console shows a structured diff. The loosening detector marks the change as loosening if it does any of the following:
   - raises any limit or cap
   - removes or disables a check
   - lengthens a time window that makes a check pass sooner
   - shrinks `block_on` or `escalate_on`
   - raises the travel-rule threshold or removes a required field
   - widens the allowed networks
   - shortens the screening scope (any change to the screening list counts), or raises the above-norm multiplier or minimum history (POL-07; C-08: the union of both lists)
3. A second, different user approves. The compliance lead is one of the two on **every** activation, loosening or not (C-06, confirmed 2026-11-19), and attests when proposing or approving.
4. On activation, the attestation text, the attesting compliance lead, both approvers and their roles, and timestamps are recorded, and the previous version becomes `superseded`. A draft nobody approves is `withdrawn`; nothing is deleted. Decisions in flight keep the version they started with. The pre-send re-check uses the new one.
5. Only one draft is open at a time, its version is the next number, and a draft based on a version that is no longer active can't be activated.
