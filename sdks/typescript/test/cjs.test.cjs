// SDK-02: the CommonJS build loads and has the same API as the ES module build.
const assert = require("node:assert/strict");
const { test } = require("node:test");

test("the CommonJS build exports the client", async () => {
  const cjs = require("../dist/cjs/index.js");
  const esm = await import("../dist/esm/index.js");
  assert.equal(typeof cjs.DekernAI, "function");
  assert.equal(typeof cjs.verifyWebhook, "function");
  assert.deepEqual(Object.keys(cjs).filter((k) => k !== "__esModule").sort(), Object.keys(esm).sort());
  const c = new cjs.DekernAI({ apiKey: "sk_test_x" });
  assert.equal(typeof c.paymentIntents.create, "function");
});
