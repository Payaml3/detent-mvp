// The client: keys, versioning, idempotency keys and safe retries (SDK-02, the same behaviour as SDK-01).
//
// Retries happen only where they can't pay twice: on 429 and 503, and on connection errors that happen before the
// API sees the request. A retried create sends the same Idempotency-Key, so the API returns the first result
// instead of creating a second payment. A timeout or a dropped connection is never retried: the request may have
// arrived.
import { randomUUID } from "node:crypto";
import { APIConnectionError, APIError } from "./errors.js";
import { API_VERSION, resources } from "./generated.js";

export const VERSION = "0.1.0";
export const DEFAULT_BASE_URL = "http://localhost:8000";
const RETRY_STATUSES = new Set([429, 503]);
const BEFORE_REQUEST = new Set(["ECONNREFUSED", "ENOTFOUND", "EAI_AGAIN", "UND_ERR_CONNECT_TIMEOUT"]);
const MAX_BACKOFF_MS = 30_000;

export interface RequestOptions {
  method: string;
  path: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  idempotent?: boolean;
  idempotencyKey?: string;
}

export interface ClientOptions {
  /** Defaults to DEKERNAI_API_KEY. Live keys (sk_live_) are refused. */
  apiKey?: string;
  /** Defaults to DEKERNAI_BASE_URL, then http://localhost:8000. */
  baseUrl?: string;
  apiVersion?: string;
  /** Retries on 429, 503 and connection errors before the request arrives. Default 2. */
  maxRetries?: number;
  /** Per request, in milliseconds. Default 30000. */
  timeoutMs?: number;
  fetch?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
}

type Resources = ReturnType<typeof resources>;

const env = (name: string): string | undefined =>
  typeof process !== "undefined" ? process.env[name] : undefined;

function connectErrorCode(err: unknown): string | undefined {
  const cause = (err as { cause?: { code?: string } } | undefined)?.cause;
  return cause?.code;
}

function backoff(attempt: number, retryAfter: string | null): number {
  if (retryAfter !== null) {
    const s = Number(retryAfter);
    if (Number.isFinite(s)) return Math.min(Math.max(s * 1000, 0), MAX_BACKOFF_MS);
  }
  return Math.min(500 * 2 ** attempt, MAX_BACKOFF_MS) * (0.5 + Math.random() / 2);
}

export interface DekernAI extends Resources {}

/**
 * A DekernAI API client.
 *
 *     const client = new DekernAI({ apiKey: "sk_test_...", baseUrl: "https://sandbox.api.example" });
 *     const intent = await client.paymentIntents.create({ ... });
 */
export class DekernAI {
  readonly apiKey: string;
  readonly baseUrl: string;
  readonly apiVersion: string;
  readonly maxRetries: number;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;
  private readonly sleep: (ms: number) => Promise<void>;

  constructor(options: ClientOptions = {}) {
    const key = options.apiKey ?? env("DEKERNAI_API_KEY");
    if (!key) throw new Error("pass apiKey or set DEKERNAI_API_KEY");
    if (key.startsWith("sk_live_")) {
      throw new Error("live keys are refused: DekernAI runs on test networks only (use an sk_test_ key)");
    }
    this.apiKey = key;
    this.baseUrl = (options.baseUrl ?? env("DEKERNAI_BASE_URL") ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.apiVersion = options.apiVersion ?? API_VERSION;
    this.maxRetries = options.maxRetries ?? 2;
    if (this.maxRetries < 0) throw new Error("maxRetries can't be negative");
    this.timeoutMs = options.timeoutMs ?? 30_000;
    this.fetchImpl = options.fetch ?? globalThis.fetch;
    this.sleep = options.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
    Object.assign(this, resources(this));
  }

  async request<T>(options: RequestOptions): Promise<T> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
      "DekernAI-Version": this.apiVersion,
      Accept: "application/json",
      "User-Agent": `dekernai-typescript/${VERSION}`,
    };
    if (options.idempotent) headers["Idempotency-Key"] = options.idempotencyKey ?? randomUUID(); // reused on retry
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    const url = new URL(this.baseUrl + options.path);
    for (const [k, v] of Object.entries(options.query ?? {})) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
    const body = options.body === undefined ? undefined : JSON.stringify(options.body);
    for (let attempt = 0; ; attempt++) {
      let response: Response;
      try {
        response = await this.fetchImpl(url, {
          method: options.method,
          headers,
          body,
          signal: AbortSignal.timeout(this.timeoutMs),
        });
      } catch (err) {
        const code = connectErrorCode(err);
        if (code === undefined || !BEFORE_REQUEST.has(code)) throw err; // may have arrived: never resent
        if (attempt >= this.maxRetries) {
          throw new APIConnectionError(`could not reach ${this.baseUrl}: ${code}`, err);
        }
        await this.sleep(backoff(attempt, null));
        continue;
      }
      if (RETRY_STATUSES.has(response.status) && attempt < this.maxRetries) {
        await this.sleep(backoff(attempt, response.headers.get("Retry-After")));
        continue;
      }
      const text = await response.text();
      let data: unknown = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = null;
      }
      if (!response.ok) throw new APIError(response.status, data, response.headers);
      return data as T;
    }
  }
}
