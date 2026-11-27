# DekernAI Python SDK

The Python SDK for the DekernAI API: agentic payment controls. It works with the sandbox and test networks only, and it refuses live keys.

```bash
pip install ./sdks/python        # from this repository; a package index release comes later
```

```python
from dekernai import DekernAI

client = DekernAI(api_key="sk_test_...", base_url="http://localhost:8000")
intent = client.payment_intents.create({
    "kind": "payout",
    "source": "platform",
    "counterparty_id": "cpt_lumen",
    "destination": {"kind": "evm_wallet", "network": "base-sepolia", "destination_id": "dst_lumen_base"},
    "amount": {"amount": "50.00", "currency": "USDC"},
})
print(intent["status"], intent["decision"]["outcome"])
```

- **Typed:** requests and responses are `TypedDict` models generated from the OpenAPI file (`tools/build_sdks.py`). There is one method per API operation, grouped by resource. For example: `client.exceptions.approve(case_id, {"reason": "..."})`, `client.kill_switch.engage()` and `client.events.list(type="payment_intent.unknown")`.
- **Idempotent creates:** every create sends an `Idempotency-Key`. It is a new UUID unless you pass `idempotency_key=`.
- **Safe retries:** the SDK retries only on 429, 503 and connection errors before the request reaches the API. Each retry reuses the same idempotency key, so a retry never creates a second payment. It never retries a read timeout. Set `max_retries=` to change the number of retries (2 by default).
- **Errors:** `APIError` has `status`, `type`, `code`, `message`, `param` and `request_id`. `APIConnectionError` means the API was never reached.
- **Webhooks:** `verify_webhook(secret, header, raw_body, tolerance=300)` checks the `DekernAI-Signature` header and returns the event. It raises `WebhookSignatureError` when the signature fails.

`DEKERNAI_API_KEY` and `DEKERNAI_BASE_URL` are read from the environment when they are not passed. The SDK sends the API version it was generated for (`DekernAI-Version: 2026-12-01`).
