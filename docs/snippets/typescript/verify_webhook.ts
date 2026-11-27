// Verify a DekernAI webhook delivery. Run: node verify_webhook.ts ../webhook-vectors.txt
import { readFileSync } from "node:fs";

// docs:start
import { createHmac, timingSafeEqual } from "node:crypto";

export function verifyWebhook(
  secret: string,
  header: string,
  body: string | Buffer,
  now: number = Math.floor(Date.now() / 1000),
  tolerance = 300,
): boolean {
  let timestamp: number | undefined;
  const signatures: string[] = [];
  for (const part of header.split(",")) {
    const i = part.indexOf("=");
    if (i < 0) return false;
    const key = part.slice(0, i).trim();
    const value = part.slice(i + 1).trim();
    if (key === "t") {
      if (timestamp !== undefined || !/^\d+$/.test(value)) return false;
      timestamp = Number(value);
    } else if (key === "v1") {
      signatures.push(value);
    }
  }
  if (timestamp === undefined || signatures.length === 0) return false;
  if (Math.abs(now - timestamp) > tolerance) return false;
  const expected = Buffer.from(
    createHmac("sha256", secret).update(`${timestamp}.`).update(body).digest("hex"),
  );
  return signatures.some((s) => {
    const candidate = Buffer.from(s);
    return candidate.length === expected.length && timingSafeEqual(candidate, expected);
  });
}
// docs:end

let failures = 0;
for (const line of readFileSync(process.argv[2], "utf8").split("\n")) {
  if (!line || line.startsWith("#")) continue;
  const [name, expect, secret, now, header, ...rest] = line.split("|");
  if (verifyWebhook(secret, header, rest.join("|"), Number(now)) !== (expect === "ok")) {
    console.log(`FAIL ${name}: expected ${expect}`);
    failures++;
  }
}
console.log(failures ? `typescript: ${failures} vector(s) failed` : "typescript: all vectors pass");
process.exit(failures ? 1 : 0);
