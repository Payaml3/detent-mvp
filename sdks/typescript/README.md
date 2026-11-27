# DekernAI TypeScript SDK

The TypeScript SDK for the DekernAI API: agentic payment controls. It works with the sandbox and test networks only, and it refuses live keys. It needs Node 18 or later and has no runtime dependencies. It ships both ES module and CommonJS builds.

```bash
cd sdks/typescript && npm ci && npm run build   # from this repository; a registry release comes later
```

```ts
import { DekernAI } from "dekernai";

const client = new DekernAI({ apiKey: "sk_test_...", baseUrl: "http://localhost:8000" });
const intent = await client.paymentIntents.create({
  kind: "payout",
  source: "platform",
  counterparty_id: "cpt_lumen",
  destination: { kind: "evm_wallet", network: "base-sepolia", destination_id: "dst_lumen_base" },
  amount: { amount: "50.00", currency: "USDC" },
});
console.log(intent.status, intent.decision?.outcome);
```

It has the same features as the Python SDK:

- **Typed:** request and response types are generated from the OpenAPI file (`tools/build_sdks.py`). There is one method per API operation, grouped by resource, for example `client.exceptions.approve(caseId, { reason })` or `client.killSwitch.engage()`.
- **Idempotent creates:** every create sends an `Idempotency-Key`. It is a new UUID unless you pass `{ idempotencyKey }`.
- **Safe retries:** the SDK retries only on 429, 503 and connection errors before the request reaches the API. Each retry reuses the same key. It never retries a timeout or a dropped connection. Set `maxRetries` to change the number of retries (2 by default).
- **Errors:** `APIError` has `status`, `type`, `code`, `message`, `param` and `requestId`. `APIConnectionError` means the API was never reached.
- **Webhooks:** `verifyWebhook(secret, header, rawBody, tolerance = 300)` returns the event. It throws `WebhookSignatureError` when the signature fails.

`npm test` builds both outputs and runs the tests. It also runs the sandbox tests when `DEKERNAI_BASE_URL` and `DEKERNAI_API_KEY` are set; CI sets them.
