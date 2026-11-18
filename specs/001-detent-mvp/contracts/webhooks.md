# Webhooks contract

Source: [spec/03 §Webhooks](../../../spec/03-api.md#webhooks) (confirmed) and FR-103. Retry schedule is **proposed**
(G-20, FR-104).

## Envelope

```json
{"id": "evt_01JD...", "type": "payment_intent.unknown", "created": 1764756000,
 "sequence": 4, "data": {"object": {"id": "pay_01JD...", "status": "UNKNOWN", "...": "PaymentIntent"}}}
```

- `id` is unique; delivery is **at least once**, so receivers deduplicate on `id`.
- `sequence` increases per payment; receivers ignore an event whose sequence is lower than the last one seen for that
  payment.
- `data.object` is the full current resource (schemas in [openapi.yaml](openapi.yaml)).

## Event types

`payment_intent.{decided, escalated, ready, submitted, unknown, confirmed, failed, blocked, rejected, cancelled}`,
`exception.{created, overdue, resolved}`, `deposit.{received, credited, exception}`, `reconciliation.break`,
`kill_switch.{engaged, released}`.

## Signature

```
Detent-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, "{t}.{raw_body}")>
```

- Receivers reject a delivery whose `t` is more than 300 s from their clock.
- The signing secret is shown once when the endpoint is created. It is stored **encrypted** (D-12), not
  hashed: Detent needs the plaintext to compute each signature.
- `send test event` (spec/08) delivers a signed sample event; marking it `"test": true` is PROPOSED (G-20).

## Delivery and retries

| Attempt | Delay after the previous attempt (PROPOSED, G-20) |
|---|---|
| 1 | immediately, from the worker after the change commits (outbox pattern) |
| 2 to 7 | 1 min, 5 min, 30 min, 2 h, 6 h, 24 h |
| after 7 | delivery marked `failed`; visible in the delivery log with a Resend button |

A 2xx response is success; anything else, or no response within 10 s (PROPOSED, G-20), is a failure. Every attempt is a
`webhook_deliveries` row with the status code or error.
