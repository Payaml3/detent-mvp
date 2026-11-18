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
  travel_rule: {threshold: {amount: "1000.00", currency: USDC}, required: [originator.name, originator.account, beneficiary.name, beneficiary.account]}
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
| resubmission_after_block | ESCALATE | RESUBMISSION_AFTER_BLOCK | blocked payment ID |
| system | ESCALATE | SYSTEM_UNAVAILABLE | dependency and error class |

**Deposit checks** (LED-05) reuse the same engine with a deposit profile:

- token and network match (BLOCK on a mismatch, then a deposit exception)
- sender screening (BLOCK on a hit)
- amount tolerance against the deposit intent (ESCALATE)

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
3. A second, different user approves. If the change is loosening, one of the two users must be the compliance lead.
4. On activation, the attestation text, approvers and timestamps are recorded, and the previous version becomes `superseded`. Decisions in flight keep the version they started with. The pre-send re-check uses the new one.
