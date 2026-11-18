# 06 · Rails, routing, failover and fault injection

**Product:** agentic payment controls in three layers: decision, orchestration and operations (see `CLAUDE.md`). **This spec covers:** the **orchestration** layer.

## Adapter contract (RAL-01)

```python
class RailAdapter(Protocol):
    rail_id: str
    def eligible(self, intent: IntentView) -> Eligibility: ...          # currency, network, limits, cut-off, health
    def quote(self, intent: IntentView) -> Quote: ...                  # fee_minor, expected_seconds
    def submit(self, attempt: AttemptView) -> SubmitResult: ...        # may raise RailTimeout
    def status(self, attempt: AttemptView) -> StatusResult: ...        # CONFIRMED | PENDING | FAILED(class) | NOT_FOUND
    def health(self) -> Health: ...                                    # success_rate, p95_latency, balance
```

**Normalised failure classes:**

| Class | Meaning | Execution layer response |
|---|---|---|
| `TECHNICAL_RETRYABLE` | Known not executed: nonce too low before broadcast, 503 before acceptance, insufficient gas detected pre-send | Retry per config (same payment ID) |
| `TECHNICAL_FINAL` | Definitively failed on this rail: receipt status 0, rail says failed | Failover if allowed; otherwise FAILED_FINAL |
| `REJECTED_BY_RAIL` | Rail compliance or account rejection | FAILED_FINAL; never retried, never re-routed |
| `TIMEOUT` | Outcome unknown | Attempt UNKNOWN; resolver only |

**Rule of thumb:** if the request might have reached the rail, it is TIMEOUT, not a failure.

## Idempotency keys passed to rails

- **Bank simulator:** `Idempotency-Key = {payment_id}`, the same across retries on the same rail, so the rail itself deduplicates. A failover to a different rail uses `{payment_id}:{rail_id}`.
- **EVM rails:** deduplication is by nonce. The attempt stores the nonce before broadcast. Re-broadcasting the same signed raw transaction is allowed (it is the same transaction). Signing a new transaction for the same payment needs the previous attempt definitively FAILED.

## Rails in the MVP

| Rail | ID | Currency | Settlement | Notes |
|---|---|---|---|---|
| Base Sepolia | `base-sepolia` | USDC (testnet) | About 2 s blocks; confirmations threshold 3 (config) | Test USDC from Circle's faucet |
| Ethereum Sepolia | `eth-sepolia` | USDC (testnet) | About 12 s blocks; threshold 2 (config) | Higher fee profile in routing |
| Bank simulator, Faster Payments-style | `banksim-fps` | GBP | Instant; cut-off none; limits configurable | Separate app `apps/banksim` |
| Bank simulator, SEPA Instant-style | `banksim-sepa-inst` | EUR | Instant | Same app, second scheme |
| Simulated chain (sandbox) | `simchain` | USDC | Instant | Default for sandbox organisations |
| Local chain (tests) | `local-evm` | MockUSDC | anvil, automine | CI and fault suite |

**Bank simulator behaviour (RAL-04):**
- fees: flat plus percentage, per scheme
- per-payment and daily limits
- cut-off windows (configurable; off by default)
- failure rate (configurable; 0 in demo mode)
- `POST /payments` (idempotent), `GET /payments/{key}`, `GET /statements/{date}`
- a settlement webhook to Detent

The test values apply.

## Routing (RAL-06)

1. Run only after EXECUTE.
2. Filter candidates with `eligible`:
   - the currency matches
   - the network is in the intent's `network_constraint` or the mandate's networks
   - the rail is within its limits and inside cut-off
   - its circuit is closed
   - the pre-funded limit has room
3. Score each candidate: `score = w_cost * norm(fee) + w_speed * norm(expected_seconds) + w_success * (1 - success_rate) + w_liquidity * (1 - liquidity_headroom)`. The lowest score wins. Weights come from `fixtures/rails.yaml`.
4. Store all candidates, their scores and the reason for the winner on the decision (`route` jsonb).

When a destination is a specific wallet on one network, routing is effectively fixed unless `allow_network_switch` is true and the payee has a verified destination on another network.

## Failover (RAL-07)

- Failover is allowed only when all of these hold:
  - the previous attempt is FAILED with `TECHNICAL_FINAL`, or retries are exhausted on `TECHNICAL_RETRYABLE`
  - the intent or mandate allows a network switch, or a human has approved the switch
  - another eligible rail exists
- Failover keeps the payment ID. `attempt_no` increments.
- Failover never happens from UNKNOWN, after a BLOCK, or after `REJECTED_BY_RAIL`.

## UNKNOWN resolution (EXE-06)

```
on attempt UNKNOWN:
  schedule poll at +5s, +15s, +30s, +60s, then every 2 min
  EVM:  receipt = get_transaction_receipt(tx_hash)
        if receipt and receipt.status == 1 and confirmations >= threshold -> CONFIRMED
        if receipt and receipt.status == 0 -> FAILED(TECHNICAL_FINAL)
        if no receipt and get_transaction_count(from, 'latest') > nonce
           and the tx at that nonce is a different hash -> FAILED(TECHNICAL_FINAL)   # nonce consumed by another tx
        else keep UNKNOWN
  Bank: status by idempotency key: SETTLED -> CONFIRMED; FAILED -> FAILED(class); NOT_FOUND after rail's
        stated acceptance window -> FAILED(TECHNICAL_FINAL); else keep UNKNOWN
  after unknown_stuck_after (default 15 min): open case UNKNOWN_STUCK (owner payments lead)
     options: keep waiting | approve cancel-by-replacement (EVM only: same nonce, 0-value self-transfer,
     higher fee). The outcome is still read from the chain: whichever tx lands decides CONFIRMED or FAILED.
```

## Fault injection (RAL-05)

`apps/faultproxy` sits between adapters and RPC or bank endpoints. Scenarios are selected by the `X-Detent-Fault` header (tests) or by sandbox scenario config. They are never active in demo mode unless the scenario runner sets them.

| Fault | Effect | Expected Detent behaviour |
|---|---|---|
| `timeout_after_forward` | Forwards the request; drops the response | Attempt UNKNOWN; resolver finds CONFIRMED; no second send |
| `timeout_before_forward` | Never forwards; times out | Attempt UNKNOWN; resolver finds nothing; nonce not consumed; definitive FAILED only after nonce or rail evidence; then retry with the same payment ID |
| `reset_after_forward` | Connection reset after forwarding | Same as `timeout_after_forward` |
| `http_503_before_accept` | 503 without forwarding | TECHNICAL_RETRYABLE; retry |
| `delayed_receipt:N` | Hides the receipt for N polls | UNKNOWN until revealed; no resend |
| `stuck_tx` | Hides the receipt indefinitely | UNKNOWN_STUCK case; human chooses |
| `duplicate_response` | Returns the response twice | Second ignored (idempotent handling) |
| `rail_reject` | Rail compliance rejection | FAILED_FINAL; no failover |
| `receipt_status_0` | Reverted tx | TECHNICAL_FINAL; failover if allowed |

## Sandbox test values (SBX-01)

| Input | Effect |
|---|---|
| Amount ending in `.13` | `timeout_after_forward`: UNKNOWN, then CONFIRMED |
| Amount ending in `.42` | `receipt_status_0` on the first rail: failover under the same payment ID if allowed, else FAILED_FINAL |
| Payee address ending `dEaD` (`0x000000000000000000000000000000000000dEaD`) | Screening hit: BLOCK |
| Payee not on the allowlist | ESCALATE (FIRST_PAYMENT / NOT_ALLOWLISTED) |
| Amount above the mandate's per-payment limit | BLOCK `MANDATE_AMOUNT_EXCEEDED` |
