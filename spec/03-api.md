# 03 · Public API (sandbox)

**Product:** agentic payment controls in three layers: decision, orchestration and operations (see `AGENTS.md`). **This spec covers:** the public API for all three layers. Decision: `/payment_intents`, `/decisions`, `/mandates`, `/policy`. Orchestration: `/send`, `/kill_switch`. Operations: `/exceptions`, `/deposit_intents`, `/reconciliation`, `/replay`, `/events`.

Base URL (hosted sandbox, founder 2026-11-28): `https://app.dekernai.com/v1`. Every request uses TLS and carries `Authorization: Bearer sk_test_...`. The OpenAPI 3.1 file is generated from the code and then polished (API-05). This page is the contract it must match.

## Standards

| Topic | Rule |
|---|---|
| **Authentication** | Bearer test key. Keys are hashed at rest. Scopes: `read`, `intents:create`, `exceptions:approve`, `admin`. `sk_live_` keys always return 403 `live_mode_unavailable` |
| **Idempotency** | An `Idempotency-Key` header is required on every POST that creates something. The same key with the same body returns the stored response. The same key with a different body returns 409 `idempotency_conflict` |
| **Versioning** | `DekernAI-Version: 2026-12-01` (dated). Each organisation has a pinned default. An unknown version returns 400 `unknown_version` |
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
| POST `/payment_intents/{id}/cancel` | intents:create | INT-05 | Cancel before sending; a BLOCKED payment answers 409 `payment_blocked` |
| POST `/payment_intents/{id}/send` | exceptions:approve | EXE-09 | Assist mode: a human confirms sending; a BLOCKED payment answers 409 `payment_blocked` |
| GET `/payment_intents/{id}/replay` | read | AUD-02 | Step-by-step replay and its match result |
| POST `/decisions` | intents:create | POL-08 | Decision only; nothing is executed |
| GET `/exceptions` | read | EXC-08 | List cases; filters `status`, `owner`, `tier`, `overdue` |
| GET `/exceptions/{id}` | read | EXC-08 | Raw facts, rule hits and agent evidence |
| POST `/exceptions/{id}/approve` | exceptions:approve | EXC-04, EXC-08, RAL-07 | Approve with `reason`; re-runs policy. Optional `allow_network_switch: true` approves a failover to another network |
| POST `/exceptions/{id}/reject` | exceptions:approve | EXC-04, EXC-08 | Reject with `reason` |
| POST `/deposit_intents` | intents:create | LED-03 | Create deposit instructions |
| GET `/deposit_intents/{id}` | read | LED-03 | Status and credits |
| PUT `/user_accounts/{ref}`, GET `/user_accounts/{ref}` | intents:create (read for GET) | USR-01 | Register an end user's one payout destination and the platform's typed `user_verified` flag; agent keys are refused |
| GET `/mandates`, POST `/mandates`, POST `/mandates/{id}/revoke` | admin | MND-01, MND-03 | Manage agent mandates |
| GET `/policy/versions`, GET `/policy/versions/{v}` | read | POL-01 | Read rule versions (changes happen in the console) |
| POST `/kill_switch` and DELETE `/kill_switch` | admin | EXE-08 | Engage, and release (payments lead only) |
| GET `/reconciliation/runs`, GET `/reconciliation/breaks` | read | LED-06 | Results and breaks |
| GET `/events`, GET `/events/{id}` | read | API-07 | Polling alternative to webhooks; filters `type`, `payment_id`, `test` |
| POST `/webhook_endpoints`, GET `/webhook_endpoints`, GET and DELETE `/webhook_endpoints/{id}` | admin (read for GET) | WHK-01 | Register (`Idempotency-Key` required; the secret is in the first response only), list, read and disable endpoints |
| POST `/webhook_endpoints/{id}/test`, POST `/webhook_endpoints/{id}/resend` | admin | WHK-03 | Send a `webhook.test` event; resend one event by `event_id` |
| GET `/webhook_endpoints/{id}/deliveries` | read | WHK-03 | Delivery log: attempt, status, response time, outcome |
| POST `/sandbox/reset` | admin | SBX-04 | Reset the organisation's test data by starting a new data generation; nothing is deleted (D-08) |
| POST `/sandbox/scenarios` | admin | DSH-07 | Force the next payment's scenario: `timeout_unknown`, `rail_failure`, `flagged_address` |

## Create a payout intent

Request:

```http
POST /v1/payment_intents
Authorization: Bearer sk_test_...
Idempotency-Key: 4f7c1e1a-inv-2026-0142
DekernAI-Version: 2026-12-01
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

The signature header is `DekernAI-Signature: t=1764756000,v1=<hex HMAC-SHA256(secret, "{t}.{raw_body}")>`. Reject any delivery whose timestamp is more than 300 s from now. Delivery is at least once, so deduplicate on `id`. `sequence` increases per payment.

`deposit.received` (funds seen, not yet credited) is planned; nothing emits it yet, so endpoints cannot subscribe to it.

## Error codes

The catalogue of every code the API returns, with its status, type and what the client should do, lives in
`apps/api/src/detent/api/error_codes.py`. `make error-docs` generates `docs/api/errors.md` from it, a unit test fails
if the page drifts, and the test session fails if the API returns a code that is not in the catalogue (API-02).

Codes planned by later stories join the catalogue with the code that returns them: `invalid_transition`,
`not_cancellable` (INT-05), `quota_exceeded` (SBX), `kill_switch_engaged`.

## As built (P1 group 1)

- **Versions (API-03):** `DekernAI-Version`. Without the header, the organisation's pinned `api_version` applies and
  is echoed on the response; an unknown version is 400 `unknown_version` before any work. Only `2026-12-01` exists.
- **Rate limits (API-04):** a fixed 60-second window per key (120 requests) in process memory, plus a ceiling per
  client address (10 times the key limit) so rotating junk tokens cannot dodge it. Fine for the single sandbox
  instance; a shared store is needed before running more than one API instance.
- **Request logs (API-06):** `GET /v1/request_logs` (scope `read`), newest first, filters `status`, `payment_id`,
  `idempotency_key`, paged with `limit` and `starting_after`. Metadata only: no bodies, no query strings, no keys.
  The worker deletes rows older than 30 days (`detent/db/retention.py`); reads never show them.
- **Errors (API-02):** framework errors (404, 405 and others) use the same envelope as every other error.

## As built (P1 group 2)

- **OpenAPI (API-05):** `docs/api/openapi.json` (OpenAPI 3.1) is generated from the routes by
  `detent/api/openapi.py` (`make openapi`), which adds summaries, success schemas, every catalogued error with an
  example, rate-limit headers and one `webhooks` entry per event type. A unit test fails if the file drifts or a
  `/v1` route has no entry; CI lints it with Redocly (`redocly.yaml`). The server is localhost until the public
  sandbox address exists (S9).
- **Events (WHK-01, API-07):** written by `audit.log.append` in the same transaction as the change, so a rolled-back
  change has no event. `sequence` is per payment (per subject for events without one). Stored events are
  append-only (database triggers). `GET /v1/events` returns the same envelope the webhook delivers.
- **Endpoints (WHK-01):** at most 16 enabled per organisation; https only; no credentials, private, loopback,
  link-local or `.local`/`.internal` hosts (`WEBHOOK_ALLOW_PRIVATE_URLS` lifts this in dev and test only). Secrets
  are stored encrypted with `CREDENTIALS_ENCRYPTION_KEY`; without the key, creation is 503 `webhooks_unavailable`.
  An idempotent replay of the create call returns `secret: null`.
- **Delivery (WHK-03):** one `webhook.deliver` job per endpoint and event, at least once. Timeout 10 s, no
  redirects; any 2xx succeeds. Retries after 1 m, 5 m, 30 m, 2 h, 6 h and 24 h, then the delivery is `failed`
  (G-20). Each attempt is logged with status code, latency and outcome. Known limit: the host's addresses are
  checked when the delivery runs, so a DNS answer that changes between the check and the connection (rebinding)
  is not caught; pinning the resolved address is a follow-up before production.
- **Signing (WHK-02):** `detent/webhooks/signing.py` signs and verifies. The verify helpers in each docs language,
  with their tests, come with the docs snippets (DOC-04), so WHK-02 stays open until then.
- **Exceptions (EXC-08):** `GET /v1/exceptions` filters `status` (open, resolved), `owner`, `tier`, `overdue`, paged
  with `starting_after`; `GET /v1/exceptions/{id}` shows raw facts first, then rule hits, the investigation and
  history.
