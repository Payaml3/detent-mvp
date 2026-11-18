# Internal contracts

Interfaces between modules that are not part of the public API. Confirmed parts cite their source; anything else is
marked PROPOSED or is a technical choice from [research.md](../research.md).

## 1. Rail adapter (confirmed, spec/06 §Adapter contract)

```python
class RailAdapter(Protocol):
    rail_id: str
    def eligible(self, intent: IntentView) -> Eligibility: ...   # currency, network, limits, cut-off, health
    def quote(self, intent: IntentView) -> Quote: ...            # fee (Money), expected_seconds
    def submit(self, attempt: AttemptView) -> SubmitResult: ...  # may raise RailTimeout
    def status(self, attempt: AttemptView) -> StatusResult: ...  # CONFIRMED | PENDING | FAILED(class) | NOT_FOUND
    def health(self) -> Health: ...                              # success_rate, p95_latency, balance
```

| Situation | Adapter returns | Execution layer does |
|---|---|---|
| Known not executed (nonce too low before broadcast, 503 before acceptance, gas shortfall pre-send) | `FAILED(TECHNICAL_RETRYABLE)` | Retry per `retry` config, same payment ID |
| Definitively failed on this rail (receipt status 0, rail says failed) | `FAILED(TECHNICAL_FINAL)` | Failover if allowed, else FAILED_FINAL |
| Rail compliance or account rejection | `FAILED(REJECTED_BY_RAIL)` | FAILED_FINAL; never retried or re-routed |
| The request might have reached the rail | raises `RailTimeout` | Attempt UNKNOWN; resolver only |

Contract test suite (RAL-01): every adapter runs the same tests for the four classes against the fault proxy.
Idempotency keys: banksim `{payment_id}` on the same rail, `{payment_id}:{rail_id}` after failover; EVM by nonce and
the stored raw transaction (D-02).

## 2. Signer (confirmed, spec/01 §Production custody boundary)

```python
class Signer(Protocol):
    address: str
    chain_id: int                       # must be in the test-network set (invariant 14)
    def sign(self, tx: UnsignedTx) -> SignedTx: ...   # SignedTx = raw bytes + hash
```

Prototype: test keys from settings. Production: a custody-provider signer replaces it.

## 3. Agent output schemas (confirmed, spec/05)

- **Instruction agent**: `proposal.{payee_name, counterparty_id, amount, currency, network, wallet_address,
  invoice_number, due_date}` each `{value | null, confidence 0..1, source_span [start, end] | null}`; `flags[]` with codes
  MISSING_NETWORK, MULTIPLE_WALLETS, TOTAL_MISMATCH, AMBIGUOUS_CURRENCY, PAYEE_NOT_IN_REGISTRY,
  WALLET_DIFFERS_FROM_REGISTRY, AMOUNT_OUTSIDE_MANDATE, POSSIBLE_INJECTION, UNREADABLE; `requires_clarification`.
  Post-check: every non-null value except `counterparty_id` must equal the document text at `source_span`, or it is
  nulled and flagged.
- **Investigation agent**: `summary`, `claims[{text, evidence_ids[]}]`, `recommendation` (spec/05 shows `approve`; the full value set
  approve, reject, needs_info is PROPOSED, G-22), `confidence`, `open_questions[]`. Claims without valid evidence IDs are removed and counted.
- **Reconciliation agent**: `proposed_fix` in {`match_to(id)`, `credit_account(account_ref)`, `return_to_sender`,
  `write_off_to_suspense`, `needs_investigation`} with a rationale citing evidence IDs. Applied by code only after
  human approval.
- **Data blocks**: untrusted text goes after the instructions inside `<document>` or `<field name="...">`, with the
  fixed sentence from spec/05 rule 3.
- **LLMClient** (research R-09): `complete(prompt_version, system, data_blocks, schema) -> Parsed`; records an
  `agent_calls` row; returns `needs_human` when the daily token budget is exhausted.

## 4. Rule-set schema (confirmed keys from spec/04; PROPOSED additions from the fixture, C-11)

| Key | Source |
|---|---|
| `version`, `platform`, `fail_safe`, `attestation` | spec/04, fixture |
| `checks.{mandate_scope, kyb_status, allowlist, screening, travel_rule, allowed_networks, limits, daily_caps, unusual, resubmission_after_block}` | spec/04 |
| `deadlines.{payout_above_auto_limit, payout_other, deposit_exception}` | spec/04 |
| `deadlines.unknown_stuck` | fixture only (C-11, proposed) |
| `owners[{match.type, owner_role, backup_role}]` for payout, deposit, unknown_stuck | spec/04 |
| `owners` rule for `reconciliation` | fixture only (C-11, proposed) |
| `retry.{max_attempts, retryable, backoff_seconds}` | fixture only (C-11, proposed) |
| `execution.{max_decision_age_seconds, unknown_stuck_after}` | fixture only (C-11, proposed); spec/06 default 15 min |

Validation: `detent/policy/schema.py` (POL-01) rejects unknown keys, so a typo can't silently disable a check.

## 5. Policy evaluation (research R-08)

```python
def evaluate(rules: RuleSet, snapshot: DecisionInputs, approved_reasons: frozenset[Reason] = frozenset()) -> Decision
```

Pure and deterministic. `DecisionInputs` holds only typed fields: intent fields, counterparty facts, destination
history, mandate state, screening result, counters. The service that gathers inputs turns any exception into
`ESCALATE SYSTEM_UNAVAILABLE` (FR-033).

## 6. Job kinds (worker)

| Kind | Slice | Dedupe key | Payload |
|---|---|---|---|
| `send_payment` | S2 | `send:{payment_id}` | payment_id |
| `resolve_attempt` | S4 | `resolve:{attempt_id}:{poll_no}` | attempt_id, poll_no |
| `sweep_deadlines` | S6 | `sweep:{minute}` | none |
| `investigate_case` | S6 | `investigate:{case_id}` | case_id |
| `watch_deposits` | S7 | `watch:{rail_id}:{block}` | rail_id, from_block |
| `run_reconciliation` | S7 | `recon:{date}` | date |
| `deliver_webhook` | P1 | `whd:{delivery_id}` | delivery_id |
| `monitor_invariants` | L | `monitor:{minute}` | none |

Handlers write their database effects in the job's transaction (M0 queue contract); external calls use idempotency
keys.

## 7. Audit event kinds

Naming: `<area>.<past-tense verb>`. Existing (M0): `console.acting_user_selected`, `demo.clock_advanced`,
`seed.demo_applied`. Planned per slice: `payment.received`, `payment.decided`, `payment.transitioned`,
`attempt.created`, `attempt.submitted`, `attempt.resolved`, `case.opened`, `case.assigned`, `case.overdue`,
`case.resolved`, `kill_switch.engaged`, `kill_switch.released`, `policy.drafted`, `policy.approved`,
`policy.activated`, `mandate.issued`, `mandate.revoked`, `destination.changed`, `deposit.credited`,
`recon.fix_approved`, `mode.changed`, `api_key.created`, `api_key.revoked`, `sandbox.reset`. Every payload names the
actor's user ID and role and holds no floats.

## 8. Permission actions

`detent/domain/roles.py` `PERMISSIONS` is the single table; an action missing from it is denied. Current cells and
their status: [spec.md](../spec.md#roles-and-permissions).
