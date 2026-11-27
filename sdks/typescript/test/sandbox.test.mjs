// SDK-02: the SDK against a running sandbox API. CI starts one (the "sdks" job) and sets DEKERNAI_BASE_URL and
// DEKERNAI_API_KEY to a key for the seeded demo organisation; without them these tests are skipped.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { APIError, DekernAI } from "../dist/esm/index.js";

const live = Boolean(process.env.DEKERNAI_BASE_URL && process.env.DEKERNAI_API_KEY);
const skip = live ? false : "set DEKERNAI_BASE_URL and DEKERNAI_API_KEY to run against a sandbox";

const BODY = {
  kind: "payout",
  source: "platform",
  counterparty_id: "cpt_lumen",
  destination: { kind: "evm_wallet", network: "base-sepolia", destination_id: "dst_lumen_base" },
  amount: { amount: "25.00", currency: "USDC" },
  reference: "SDK-TS-CI",
};

test("create, replay, retrieve and list against the sandbox", { skip }, async () => {
  const client = new DekernAI();
  const key = randomUUID();
  const created = await client.paymentIntents.create(BODY, { idempotencyKey: key });
  assert.match(created.id, /^pay_/);
  assert.equal(created.decision?.outcome, "EXECUTE");
  assert.equal((await client.paymentIntents.create(BODY, { idempotencyKey: key })).id, created.id);
  assert.equal((await client.paymentIntents.retrieve(created.id)).id, created.id);
  const page = await client.paymentIntents.list({ limit: 1 });
  assert.equal(page.data.length, 1);
  const dry = await client.decisions.create(BODY);
  assert.equal(dry.outcome, "EXECUTE");
  assert.ok((await client.policy.listVersions()).data.length >= 1);
});

test("API errors carry the error fields", { skip }, async () => {
  const client = new DekernAI();
  await assert.rejects(client.paymentIntents.retrieve("pay_doesnotexist"), (err) => {
    assert.ok(err instanceof APIError);
    assert.equal(err.status, 404);
    assert.equal(err.type, "not_found");
    assert.ok(err.requestId);
    return true;
  });
});
