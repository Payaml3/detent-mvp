// Verify webhook deliveries (WHK-02). `DekernAI-Signature: t=<unix seconds>,v1=<hex>` is an HMAC-SHA256, with
// your endpoint's signing secret, over "{t}.{raw body}". During a secret rotation a delivery carries one v1= per
// active secret.
import { createHmac, timingSafeEqual } from "node:crypto";
import { WebhookSignatureError } from "./errors.js";

export const SIGNATURE_HEADER = "DekernAI-Signature";

function parse(header: string): { ts: number; sigs: string[] } {
  let ts: number | undefined;
  const sigs: string[] = [];
  for (const part of header.split(",")) {
    const [key, ...rest] = part.trim().split("=");
    const value = rest.join("=");
    if (rest.length === 0) throw new WebhookSignatureError("malformed signature header");
    if (key === "t") {
      if (ts !== undefined || !/^\d+$/.test(value)) throw new WebhookSignatureError("malformed timestamp");
      ts = Number(value);
    } else if (key === "v1") {
      sigs.push(value);
    }
  }
  if (ts === undefined || sigs.length === 0) throw new WebhookSignatureError("the header needs t= and at least one v1=");
  return { ts, sigs };
}

/**
 * Check a delivery and return its event. Throws WebhookSignatureError.
 *
 * Pass the raw request body, exactly as received: parsing and re-serialising it changes the bytes. A timestamp more
 * than `tolerance` seconds away from now, in either direction, is refused against replays.
 */
export function verifyWebhook<T = Record<string, unknown>>(
  secret: string,
  header: string | null | undefined,
  body: string | Uint8Array,
  tolerance = 300,
  now: number = Math.floor(Date.now() / 1000),
): T {
  if (!header) throw new WebhookSignatureError("missing signature header");
  const { ts, sigs } = parse(header);
  if (Math.abs(now - ts) > tolerance) throw new WebhookSignatureError("timestamp outside the tolerance window");
  const raw = typeof body === "string" ? Buffer.from(body, "utf8") : Buffer.from(body);
  const expected = createHmac("sha256", secret).update(`${ts}.`).update(raw).digest();
  const ok = sigs.some((s) => {
    const given = Buffer.from(s, "hex");
    return given.length === expected.length && timingSafeEqual(given, expected);
  });
  if (!ok) throw new WebhookSignatureError("no signature matches");
  return JSON.parse(raw.toString("utf8")) as T;
}
