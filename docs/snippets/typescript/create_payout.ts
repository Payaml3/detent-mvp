// Create the quickstart payout. Run from a folder that holds payout.json: node create_payout.ts
// docs:start
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";

const response = await fetch(`${process.env.DEKERNAI_BASE_URL}/v1/payment_intents`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${process.env.DEKERNAI_API_KEY}`,
    "Idempotency-Key": randomUUID(),
    "Content-Type": "application/json",
  },
  body: readFileSync("payout.json"),
});
if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
const payment = await response.json();
console.log(payment.id, payment.status);
// docs:end
