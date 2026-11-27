// SDK-02: the client's own behaviour, against a fake fetch (no server).
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { API_VERSION, APIConnectionError, APIError, DekernAI, WebhookSignatureError, verifyWebhook } from "../dist/esm/index.js";

const BODY = {
  kind: "payout",
  source: "platform",
  counterparty_id: "cpt_lumen",
  destination: { kind: "evm_wallet", network: "base-sepolia", destination_id: "dst_lumen_base" },
  amount: { amount: "50.00", currency: "USDC" },
};

function json(status, body, headers = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

function client(handler, options = {}) {
  const calls = [];
  const slept = [];
  const fetch = async (url, init) => {
    calls.push({ url: new URL(url), init });
    return handler(calls.length, url, init);
  };
  const c = new DekernAI({
    apiKey: "sk_test_abc",
    baseUrl: "https://sandbox.example.test/",
    fetch,
    sleep: async (ms) => void slept.push(ms),
    ...options,
  });
  return { c, calls, slept };
}

function connectError(code) {
  return Object.assign(new TypeError("fetch failed"), { cause: { code } });
}

test("live keys and missing keys are refused", () => {
  assert.throws(() => new DekernAI({ apiKey: "sk_live_abc" }), /live keys are refused/);
  const saved = process.env.DEKERNAI_API_KEY;
  delete process.env.DEKERNAI_API_KEY;
  try {
    assert.throws(() => new DekernAI(), /DEKERNAI_API_KEY/);
  } finally {
    if (saved !== undefined) process.env.DEKERNAI_API_KEY = saved;
  }
});

test("requests carry the key, the version and an idempotency key on creates", async () => {
  const { c, calls } = client(() => json(201, { id: "pay_1", status: "SHADOWED" }));
  assert.equal((await c.paymentIntents.create(BODY)).id, "pay_1");
  await c.paymentIntents.create(BODY, { idempotencyKey: "my-key" });
  await c.paymentIntents.retrieve("pay_1/x");
  const [first, second, get] = calls;
  assert.equal(first.url.href, "https://sandbox.example.test/v1/payment_intents");
  assert.equal(first.init.headers.Authorization, "Bearer sk_test_abc");
  assert.equal(first.init.headers["DekernAI-Version"], API_VERSION);
  assert.match(first.init.headers["Idempotency-Key"], /^[0-9a-f-]{36}$/);
  assert.equal(second.init.headers["Idempotency-Key"], "my-key");
  assert.deepEqual(JSON.parse(first.init.body), BODY);
  assert.equal(get.init.headers["Idempotency-Key"], undefined);
  assert.equal(get.url.pathname, "/v1/payment_intents/pay_1%2Fx");
});

test("query parameters skip empty values and keep their API names", async () => {
  const { c, calls } = client(() => json(200, { data: [], has_more: false, next_cursor: null }));
  await c.paymentIntents.list({ status: "UNKNOWN", "created[gte]": "2026-12-01T00:00:00Z", limit: 5, rail: null });
  await c.exceptions.list({ overdue: true });
  assert.deepEqual(Object.fromEntries(calls[0].url.searchParams), {
    status: "UNKNOWN",
    "created[gte]": "2026-12-01T00:00:00Z",
    limit: "5",
  });
  assert.deepEqual(Object.fromEntries(calls[1].url.searchParams), { overdue: "true" });
});

for (const status of [429, 503]) {
  test(`${status} is retried with the same idempotency key`, async () => {
    const { c, calls, slept } = client((n) =>
      n < 3 ? json(status, { error: { code: "busy" } }, { "Retry-After": "2" }) : json(201, { id: "pay_1" }),
    );
    assert.equal((await c.paymentIntents.create(BODY)).id, "pay_1");
    assert.equal(calls.length, 3);
    assert.equal(new Set(calls.map((x) => x.init.headers["Idempotency-Key"])).size, 1);
    assert.deepEqual(slept, [2000, 2000]);
  });
}

test("retries stop after maxRetries and throw the API error", async () => {
  const body = { error: { type: "rate_limit", code: "rate_limited", message: "slow down", request_id: "r" } };
  const { c, calls, slept } = client(() => json(429, body), { maxRetries: 1 });
  await assert.rejects(c.paymentIntents.create(BODY), (err) => {
    assert.ok(err instanceof APIError);
    assert.equal(err.status, 429);
    assert.equal(err.code, "rate_limited");
    assert.equal(err.requestId, "r");
    return true;
  });
  assert.equal(calls.length, 2);
  assert.equal(slept.length, 1);
});

for (const status of [400, 409, 422, 500, 502]) {
  test(`${status} is never retried`, async () => {
    const { c, calls } = client(() => json(status, { error: { type: "x", code: "y", message: "no", param: "amount" } }));
    await assert.rejects(c.paymentIntents.create(BODY), (err) => err instanceof APIError && err.param === "amount");
    assert.equal(calls.length, 1);
  });
}

test("connection errors before the request arrives are retried; others are not", async () => {
  let r = client((n) => {
    if (n === 1) throw connectError("ECONNREFUSED");
    return json(201, { id: "pay_1" });
  });
  assert.equal((await r.c.paymentIntents.create(BODY)).id, "pay_1");
  assert.equal(r.calls.length, 2);
  assert.equal(r.calls[0].init.headers["Idempotency-Key"], r.calls[1].init.headers["Idempotency-Key"]);

  r = client(() => {
    throw connectError("ENOTFOUND");
  });
  await assert.rejects(r.c.killSwitch.engage(), APIConnectionError);
  assert.equal(r.slept.length, 2);

  r = client(() => {
    throw connectError("ECONNRESET"); // the request may have arrived
  });
  await assert.rejects(r.c.paymentIntents.create(BODY), TypeError);
  assert.equal(r.calls.length, 1);
});

test("every API operation has a method", () => {
  const spec = JSON.parse(readFileSync(new URL("../../../docs/api/openapi.json", import.meta.url), "utf8"));
  const ops = Object.values(spec.paths).flatMap((item) =>
    Object.keys(item).filter((m) => ["get", "post", "put", "patch", "delete"].includes(m)),
  );
  const { c } = client(() => json(200, {}));
  const methods = Object.values(c)
    .filter((v) => v && typeof v === "object" && "client" in v)
    .flatMap((r) => Object.getOwnPropertyNames(Object.getPrototypeOf(r)).filter((n) => n !== "constructor"));
  assert.equal(methods.length, ops.length);
});

function sign(secret, ts, body) {
  return "v1=" + createHmac("sha256", secret).update(`${ts}.${body}`).digest("hex");
}

test("verifyWebhook returns the event and refuses bad signatures", () => {
  const body = '{"id":"evt_1","type":"payment_intent.confirmed"}';
  const header = `t=1764756000,${sign("whsec_a", 1764756000, body)}`;
  assert.equal(verifyWebhook("whsec_a", header, body, 300, 1764756100).id, "evt_1");
  const rotated = `t=1764756000,${sign("whsec_old", 1764756000, body)},${sign("whsec_a", 1764756000, body)}`;
  assert.equal(verifyWebhook("whsec_a", rotated, new TextEncoder().encode(body), 300, 1764756000).type,
    "payment_intent.confirmed");
  for (const [bad, now] of [
    [header, 1764756301],
    [header.replace("t=1764756000", "t=1764756001"), 1764756000],
    ["v1=abc", 1764756000],
    ["", 1764756000],
  ]) {
    assert.throws(() => verifyWebhook("whsec_a", bad, body, 300, now), WebhookSignatureError);
  }
  assert.throws(() => verifyWebhook("whsec_a", header, body + " ", 300, 1764756000), WebhookSignatureError);
});
