// Logic checks: run before and independent of the build.
import { test } from "node:test";
import assert from "node:assert/strict";
import { SCENARIOS, runScenario } from "../src/scripts/scenarios.mjs";
import { readResults } from "../src/lib/results.mjs";
import { statusRows } from "../src/lib/status.mjs";

// The states a payment may move between (spec/02, detent/domain/states.py ALLOWED), mirrored for the demo.
const ALLOWED = {
  RECEIVED: ["BLOCKED", "ESCALATED", "READY", "SHADOWED", "HELD"],
  ESCALATED: ["READY", "BLOCKED", "REJECTED", "ESCALATED", "CANCELLED"],
  READY: ["SUBMITTED", "HELD", "BLOCKED", "CANCELLED"],
  HELD: ["READY", "ESCALATED", "BLOCKED", "CANCELLED"],
  SUBMITTED: ["CONFIRMED", "UNKNOWN", "FAILED"],
  UNKNOWN: ["CONFIRMED", "FAILED"],
  FAILED: ["READY", "FAILED_FINAL"],
};

test("every scenario follows the real state machine and keeps one payment ID", () => {
  assert.ok(SCENARIOS.length >= 4);
  for (const sc of SCENARIOS) {
    const run = runScenario(sc.id);
    const ids = new Set(run.steps.map((s) => s.paymentId));
    assert.equal(ids.size, 1, `${sc.id}: one payment ID for life`);
    assert.equal(run.steps[0].status, "RECEIVED");
    for (let i = 1; i < run.steps.length; i++) {
      const a = run.steps[i - 1].status, b = run.steps[i].status;
      if (a === b) continue; // an event that changes nothing (a poll, a refused action) is not a transition
      assert.ok(ALLOWED[a]?.includes(b), `${sc.id}: ${a} -> ${b} is not allowed`);
    }
    assert.ok(run.transfers <= 1, `${sc.id}: paid at most once`);
  }
});

test("a timeout goes to UNKNOWN, is never FAILED, and ends with exactly one transfer", () => {
  const run = runScenario("timeout");
  const states = run.steps.map((s) => s.status);
  assert.ok(states.includes("UNKNOWN"));
  assert.ok(!states.includes("FAILED"));
  assert.equal(states.at(-1), "CONFIRMED");
  assert.equal(run.transfers, 1);
});

test("a screening hit is BLOCKED and nothing is ever sent", () => {
  const run = runScenario("screening");
  assert.equal(run.steps.at(-1).status, "BLOCKED");
  assert.equal(run.transfers, 0);
  assert.ok(!run.steps.some((s) => s.status === "SUBMITTED"));
});

test("a reverted transaction fails over under the same payment ID", () => {
  const run = runScenario("reverted");
  const rails = run.steps.map((s) => s.rail).filter(Boolean);
  assert.ok(new Set(rails).size >= 2, "a second rail is tried");
  assert.equal(run.steps.at(-1).status, "CONFIRMED");
  assert.equal(run.transfers, 1);
});

test("an approval re-runs the policy before anything is sent", () => {
  const run = runScenario("approve");
  const i = run.steps.findIndex((s) => s.event === "policy re-run");
  const j = run.steps.findIndex((s) => s.status === "SUBMITTED");
  assert.ok(i > 0 && j > i);
});

test("results: absent file means not published and no figures", () => {
  const r = readResults(null);
  assert.equal(r.published, false);
  assert.deepEqual(r.figures, []);
});

test("results: every figure carries the dated synthetic-data label", () => {
  const r = readResults({ date: "2026-12-20", figures: [{ value: "0", caption: "unauthorised executions in 112 attack scenarios" }] });
  assert.equal(r.published, true);
  assert.match(r.label, /^Evaluation on synthetic data, 2026-12-20\. Not production results/);
  for (const f of r.figures) assert.ok(f.caption.length > 0);
});

test("results: a file without a date is rejected", () => {
  assert.throws(() => readResults({ figures: [{ value: "0", caption: "x" }] }), /date/);
});

test("status: rows follow the deploy's answer, and a failed fetch means unreachable (WEB-07)", () => {
  const ok = statusRows({ checked_at: "2026-11-28T00:00:00Z", components: [
    { id: "sandbox_api", status: "operational" }, { id: "dashboard", status: "operational" }, { id: "docs", status: "not_monitored" }] });
  assert.deepEqual(ok.rows.map((r) => r.label), ["Operational", "Operational", "Not monitored yet"]);
  assert.match(ok.summary, /operational/);
  assert.equal(ok.checkedAt, "2026-11-28T00:00:00Z");
  const down = statusRows({ components: [{ id: "sandbox_api", status: "down" }, { id: "dashboard", status: "down" }, { id: "docs", status: "weird" }] });
  assert.deepEqual(down.rows.map((r) => r.state), ["down", "down", "unknown"]);
  assert.equal(down.summary, "Sandbox API and Dashboard are having problems.");
  const gone = statusRows(null);
  assert.deepEqual(gone.rows.map((r) => r.state), ["unreachable", "unreachable", "unknown"]);
  assert.match(gone.summary, /can't reach/);
});
