# 03 · Public API (sandbox)

**Product:** agentic payment controls in three layers: decision, orchestration and operations (see `CLAUDE.md`). **This spec covers:** the public API for all three layers. Decision: `/payment_intents`, `/decisions`, `/mandates`, `/policy`. Orchestration: `/send`, `/kill_switch`. Operations: `/exceptions`, `/deposit_intents`, `/reconciliation`, `/replay`, `/events`.

Base URL (placeholder): `https://sandbox.api.<domain>/v1`. Every request uses TLS and carries `Authorization: Bearer sk_test_...`. The OpenAPI 3.1 file is generated from the code and then polished (API-05). This page is the contract it must match.

## Standards

| Topic | Rule |
|---|---|
| **Authentication** | Bearer test key. Keys are hashed at rest. Scopes: `read`, `intents:create`, `exceptions:approve`, `admin`. `sk_live_` keys always return 403 `live_mode_unavailable` |
| **Idempotency** | An `Idempotency-Key` header is required on every POST that creates something. The same key with the same body returns the stored response. The same key with a different body returns 409 `idempotency_conflict` |
| **Versioning** | `Detent-Version: 2026-12-01` (dated). Each organisation has a pinned default. An unknown version returns 400 `unknown_version` |
| **Errors** | `{"error": {"type", "code", "message", "payment_id", "request_id", "param"}}`. Types: `invalid_request`, `authentication`, `permission`, `not_found`, `conflict`, `rate_limit`, `quota`, `internal` |
| **Pagination** | `?limit=` (max 100) and `?starting_after=<id>`. Responses carry `{"data": [...], "has_more": bool, "next_cursor": "..."}` |
| **Rate limits** | Per key: `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`; 429 with `Retry-After` |
| **Request IDs** | A `Request-Id` header on every response |
| **Money** | `{"amount": "18500.00", "currency": "USDC"}` as a decimal string in the API; stored as minor units |

## Endpoints

| Method and path | Scope | Story | What it does |
|---|---|---|---|
| POST `/payment_intents` | intents:create | INT-01, INT-02 | Create a payout intent, decide it synchronously and return the decision |
| GET `/payment_intents/{id}` | read | INT-03 | Intent with decisions, checks, route, attempts, postings and events |
| GET `/payment_intents` | read | INT-03 | List with filters `status`, `rail`, `created[gte]`, `created[lte]` |
| POST `/payment_intents/{id}/cancel` | intents:create | INT-05 | Cancel before sending |
| POST `/payment_intents/{id}/send` | exceptions:approve | EXE-09 | Assist mode: a human confirms sending |
| GET `/payment_intents/{id}/replay` | read | AUD-02 | Step-by-step replay and its match result |
| POST `/decisions` | intents:create | POL-08 | Decision only; nothing is executed |
| GET `/exceptions` | read | EXC-08 | List cases; filters `status`, `owner`, `tier`, `overdue` |
| GET `/exceptions/{id}` | read | EXC-08 | Raw facts, rule hits and agent evidence |
| POST `/exceptions/{id}/approve` | exceptions:approve | EXC-04, EXC-08 | Approve with `reason`; re-runs policy |
| POST `/exceptions/{id}/reject` | exceptions:approve | EXC-04, EXC-08 | Reject with `reason` |
| POST `/deposit_intents` | intents:create | LED-03 | Create deposit instructions |
| GET `/deposit_intents/{id}` | read | LED-03 | Status and credits |
| GET `/mandates`, POST `/mandates`, POST `/mandates/{id}/revoke` | admin | MND-01, MND-03 | Manage agent mandates |
| GET `/policy/versions`, GET `/policy/versions/{v}` | read | POL-01 | Read rule versions (changes happen in the console) |
| POST `/kill_switch` and DELETE `/kill_switch` | admin | EXE-08 | Engage, and release (payments lead only) |
| GET `/reconciliation/runs`, GET `/reconciliation/breaks` | read | LED-06 | Results and breaks |
| GET `/events` | read | API-07 | Polling alternative to webhooks |
| POST `/sandbox/reset` | admin | SBX-04 | Reset the organisation's test data |
| POST `/sandbox/scenarios` | admin | DSH-07 | Force the next payment's scenario: `timeout_unknown`, `rail_failure`, `flagged_address` |

## Create a payout intent

Request:

```http
POST /v1/payment_intents
Authorization: Bearer sk_test_...
Idempotency-Key: 4f7c1e1a-inv-2026-0142
Detent-Version: 2026-12-01
Content-Type: application/json

{
  "kind": "payout",
  "source": "agent",
  "mandate_id": "mnd_01JD...",
  "counterparty_id": "cpt_01JD...",
  "destination": {"kind": "evm_wallet", "network": "base-sepolia", "address": "0x5aAe...9F3c"},
  "amount": {"amount": "18500.00", "currency": "USDC"},
  "allow_network_switch": false,
  "reference": "INV-2026-0142",
  "notes": "Q4 components order",
  "travel_rule": {"originator": {...}, "beneficiary": {...}}
}
```

Response, 201:

```json
{
  "id": "pay_01JD...",
  "status": "ESCALATED",
  "decision": {
    "id": "dec_01JD...",
    "outcome": "ESCALATE",
    "policy_version": 3,
    "checks": [
      {"check": "mandate_scope", "result": "PASS"},
      {"check": "kyb_status", "result": "PASS"},
      {"check": "screening", "result": "PASS"},
      {"check": "first_payment", "result": "ESCALATE", "reason": "FIRST_PAYMENT",
       "evidence": {"counterparty_payment_count": 0}},
      {"check": "auto_limit", "result": "ESCALATE", "reason": "ABOVE_AUTO_LIMIT",
       "evidence": {"amount": "18500.00", "auto_limit": "10000.00"}},
      {"check": "above_norm", "result": "PASS", "evidence": {"note": "not evaluated: fewer than 3 confirmed payments"}}
    ]
  },
  "exception": {"id": "exc_01JD...", "owner": "usr_...", "deadline_at": "2026-12-03T12:00:00Z"},
  "created_at": "2026-12-03T10:00:00Z"
}
```

## Webhooks

Event types:

- `payment_intent.decided`
- `payment_intent.escalated`
- `payment_intent.ready`
- `payment_intent.submitted`
- `payment_intent.unknown`
- `payment_intent.confirmed`
- `payment_intent.failed`
- `payment_intent.blocked`
- `payment_intent.rejected`
- `payment_intent.cancelled`
- `exception.created`
- `exception.overdue`
- `exception.resolved`
- `deposit.received`
- `deposit.credited`
- `deposit.exception`
- `reconciliation.break`
- `kill_switch.engaged`
- `kill_switch.released`

Event envelope:

```json
{"id": "evt_...", "type": "payment_intent.unknown", "created": 1764756000,
 "sequence": 4, "data": {"object": {...payment intent...}}}
```

The signature header is `Detent-Signature: t=1764756000,v1=<hex HMAC-SHA256(secret, "{t}.{raw_body}")>`. Reject any delivery whose timestamp is more than 300 s from now. Delivery is at least once, so deduplicate on `id`. `sequence` increases per payment.

## Error codes (starter catalogue)

- `idempotency_conflict`
- `payment_blocked`
- `already_resolved`
- `invalid_transition`
- `insufficient_scope`
- `live_mode_unavailable`
- `organisation_expired`
- `quota_exceeded`
- `unknown_version`
- `mandate_invalid`
- `self_approval_forbidden`
- `kill_switch_engaged`
- `not_cancellable`
- `validation_error`
