/** Base class for every error the SDK throws. */
export class DekernAIError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

/** The request never reached the API (DNS, refused connection), after every retry. */
export class APIConnectionError extends DekernAIError {
  constructor(message: string, readonly cause?: unknown) {
    super(message);
  }
}

interface ErrorBody {
  error?: {
    type?: string;
    code?: string;
    message?: string;
    param?: string | null;
    payment_id?: string | null;
    request_id?: string;
  };
}

/** The API answered with an error. Its fields come from the error body (see the error codes page). */
export class APIError extends DekernAIError {
  readonly type?: string;
  readonly code?: string;
  readonly param?: string | null;
  readonly paymentId?: string | null;
  readonly requestId?: string;

  constructor(readonly status: number, readonly body: unknown, readonly headers: Headers) {
    const err = ((body ?? {}) as ErrorBody).error ?? {};
    super(`${status} ${err.code ?? err.type ?? "error"}: ${err.message ?? `HTTP ${status}`}`);
    this.type = err.type;
    this.code = err.code;
    this.param = err.param;
    this.paymentId = err.payment_id;
    this.requestId = err.request_id;
  }
}

/** A webhook delivery's signature is missing, malformed, wrong or too old. */
export class WebhookSignatureError extends DekernAIError {}
