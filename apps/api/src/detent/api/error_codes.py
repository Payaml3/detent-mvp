"""The public error-code catalogue (API-02).

Every `error.code` the API can return is listed here, with the HTTP status, the error type and what
the client should do. `make error-docs` (`python -m detent.api.error_codes`) turns this table into
`docs/api/errors.md`, and a test fails if the page and the table drift. `error_response` records
any code that is not listed here, and the test session fails if one was returned (see
`tests/conftest.py`).
"""

from __future__ import annotations

from dataclasses import dataclass

from detent.api.errors import ErrorType


@dataclass(frozen=True, slots=True)
class ErrorCode:
    code: str
    statuses: tuple[int, ...]
    type: ErrorType
    meaning: str
    action: str


CATALOGUE: tuple[ErrorCode, ...] = (
    # invalid_request
    ErrorCode("validation_error", (422,), "invalid_request",
              "A field is missing, has the wrong type or is out of range. `param` names it.",
              "Fix the field named in `param` and send the request again."),
    ErrorCode("unknown_version", (400,), "invalid_request",
              "The `DekernAI-Version` header names a version that does not exist.",
              "Send a supported dated version, or leave the header out to use your organisation's "
              "pinned one."),
    ErrorCode("bad_request", (400,), "invalid_request",
              "The request could not be read, for example a malformed path parameter.",
              "Check the request against the API reference."),
    ErrorCode("method_not_allowed", (405,), "invalid_request",
              "The path exists, but not with this HTTP method.",
              "Use the method shown in the API reference."),
    ErrorCode("unsupported_network", (422,), "invalid_request",
              "The destination or deposit network is not one the sandbox supports.",
              "Use `base-sepolia`, `eth-sepolia` or a bank rail from the reference."),
    ErrorCode("network_not_allowed", (422,), "invalid_request",
              "The network is supported but not enabled for your organisation.",
              "Choose an enabled network, or ask your DekernAI contact to enable it."),
    ErrorCode("currency_mismatch", (422,), "invalid_request",
              "The currency does not match the destination or the expected amount.",
              "Send the amount in the currency of the destination."),
    ErrorCode("currency_network_mismatch", (422,), "invalid_request",
              "The currency is not available on the chosen network.",
              "Pick a network that carries the currency."),
    ErrorCode("invalid_amount", (422,), "invalid_request",
              "The amount is not a positive decimal string with the currency's precision.",
              "Send the amount as a string such as `\"18500.00\"`."),
    ErrorCode("mandate_invalid", (422,), "invalid_request",
              "The mandate is unknown, revoked, expired or not signed for this agent.",
              "Use an active mandate ID for the agent's key."),
    ErrorCode("user_payouts_unavailable", (422,), "invalid_request",
              "Payouts to end users are not available in the sandbox yet.",
              "Pay a counterparty instead."),
    ErrorCode("invalid_mode", (422,), "invalid_request",
              "The execution mode is not one of `shadow`, `assist` or `auto`.",
              "Send one of the three modes."),
    ErrorCode("invalid_url", (422,), "invalid_request",
              "The webhook URL is not https://, carries credentials, or points at a private address.",
              "Use a public https:// URL."),
    ErrorCode("unknown_event_type", (422,), "invalid_request",
              "An event type is not one of the documented types.",
              "Use the types listed in the webhooks reference, or \"*\" for all."),
    ErrorCode("reason_required", (422,), "invalid_request",
              "This action needs a written reason.",
              "Send a non-empty `reason`."),
    # authentication
    ErrorCode("missing_api_key", (401,), "authentication",
              "No `Authorization: Bearer` header was sent.",
              "Send `Authorization: Bearer sk_test_...`."),
    ErrorCode("invalid_api_key", (401,), "authentication",
              "The key is unknown, revoked or expired.",
              "Create a new test key in the dashboard."),
    # permission
    ErrorCode("live_mode_unavailable", (403,), "permission",
              "A live key was sent. DekernAI runs on test networks only.",
              "Use an `sk_test_` key."),
    ErrorCode("insufficient_scope", (403,), "permission",
              "The key does not carry the scope this endpoint needs.",
              "Use a key with the scope shown in the API reference."),
    ErrorCode("insufficient_role", (403,), "permission",
              "The user behind the key does not hold the role this action needs.",
              "Ask a user with the right role, for example the payments lead."),
    ErrorCode("self_approval_forbidden", (403,), "permission",
              "The approver is the person who started the payment.",
              "Ask a second person to approve."),
    ErrorCode("mandate_mismatch", (403,), "permission",
              "The intent names a mandate that is not the one bound to this agent key.",
              "Send the mandate ID bound to the key, or leave it out."),
    ErrorCode("organisation_expired", (403,), "permission",
              "The sandbox organisation has passed its expiry date and is locked.",
              "Contact DekernAI to extend the sandbox."),
    ErrorCode("organisation_suspended", (403,), "permission",
              "DekernAI has suspended the organisation; it is read-only until reinstated.",
              "Contact DekernAI."),
    ErrorCode("forbidden", (403,), "permission",
              "The action is not allowed for this caller.",
              "Check the scope and role the endpoint needs."),
    # not_found
    ErrorCode("not_found", (404,), "not_found",
              "No such object in your organisation, or no such path.",
              "Check the ID. Objects from another organisation are never visible."),
    # conflict
    ErrorCode("conflict", (409,), "conflict",
              "The object is in a state that does not allow this action.",
              "Read the object again and act on its current state."),
    ErrorCode("idempotency_conflict", (409,), "conflict",
              "This `Idempotency-Key` was already used with a different request body.",
              "Use a new key for a new request; resend the same body to get the stored response."),
    ErrorCode("idempotency_key_reused", (409,), "conflict",
              "This `Idempotency-Key` was already used for a different kind of request.",
              "Use a new key for each new request."),
    ErrorCode("already_resolved", (409,), "conflict",
              "The case was already approved or rejected.",
              "Read the case to see its outcome."),
    ErrorCode("payment_blocked", (409,), "conflict",
              "The payment was BLOCKED. A block is final and is never approved, retried or resent.",
              "Create a new intent only if the reason for the block no longer applies."),
    ErrorCode("resolve_via_reconciliation", (409,), "conflict",
              "The payment's outcome is UNKNOWN; only rail evidence through reconciliation can resolve it.",
              "Wait for reconciliation. Never resend while the outcome is UNKNOWN."),
    ErrorCode("too_many_endpoints", (409,), "conflict",
              "The organisation already has the maximum number of enabled webhook endpoints.",
              "Disable an endpoint you no longer use."),
    ErrorCode("endpoint_disabled", (409,), "conflict",
              "The webhook endpoint is disabled.",
              "Create a new endpoint."),
    ErrorCode("shadow_mode", (409,), "conflict",
              "The organisation is in shadow mode, so nothing is sent.",
              "Switch to assist or auto mode in the console to send."),
    # rate_limit
    ErrorCode("rate_limited", (429,), "rate_limit",
              "Too many requests for this key or client address in the current window.",
              "Wait for the seconds in `Retry-After`, then retry."),
    # quota
    ErrorCode("quota_exceeded", (429,), "quota",
              "The organisation used its daily sandbox quota for this kind of request (SBX-02).",
              "Wait for the seconds in `Retry-After` (the next UTC day); the usage page shows the quotas."),
    # internal
    ErrorCode("webhooks_unavailable", (503,), "internal",
              "Webhooks are not configured on this instance, so no endpoint can be created or signed.",
              "Contact DekernAI; nothing was created."),
    ErrorCode("internal_error", (500,), "internal",
              "Something went wrong on DekernAI's side. Nothing was executed because of it.",
              "Retry with the same `Idempotency-Key`; quote the `request_id` if it persists."),
)  # fmt: skip

BY_CODE: dict[str, ErrorCode] = {c.code: c for c in CATALOGUE}

# Framework errors (HTTPException) by status, mapped onto the catalogue.
HTTP_STATUS_CODES: dict[int, tuple[ErrorType, str]] = {
    400: ("invalid_request", "bad_request"),
    401: ("authentication", "invalid_api_key"),
    403: ("permission", "forbidden"),
    404: ("not_found", "not_found"),
    405: ("invalid_request", "method_not_allowed"),
    409: ("conflict", "conflict"),
    422: ("invalid_request", "validation_error"),
    429: ("rate_limit", "rate_limited"),
}

DOCS_PATH = "docs/api/errors.md"
_TYPES: tuple[ErrorType, ...] = (
    "invalid_request", "authentication", "permission", "not_found", "conflict", "rate_limit", "quota",
    "internal",
)  # fmt: skip


def render_markdown() -> str:
    """The error-code page for the docs, generated from CATALOGUE. Never edit the page by hand."""
    lines = [
        "# Errors",
        "",
        "<!-- Generated by `make error-docs` from apps/api/src/detent/api/error_codes.py. Do not edit. -->",
        "",
        "Every error response has the same shape:",
        "",
        "```json",
        '{"error": {"type": "conflict", "code": "payment_blocked", "message": "...",',
        '           "payment_id": "pay_...", "request_id": "req_...", "param": null}}',
        "```",
        "",
        "Branch on `type` for the broad class and on `code` for the exact reason. `message` is for",
        "people and may change. Quote `request_id` when you contact DekernAI; it is also on the",
        "`Request-Id` header.",
        "",
    ]
    for type_ in _TYPES:
        rows = [c for c in CATALOGUE if c.type == type_]
        if not rows:
            continue
        lines += [f"## `{type_}`", "", "| Code | HTTP | Meaning | What to do |", "|---|---|---|---|"]
        for c in rows:
            status = ", ".join(str(s) for s in c.statuses)
            lines.append(f"| `{c.code}` | {status} | {c.meaning} | {c.action} |")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render_markdown(), end="")
