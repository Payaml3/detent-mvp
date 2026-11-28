"""API-05: the OpenAPI 3.1 file, generated from FastAPI and then completed.

FastAPI gives the paths, parameters and request bodies straight from the code. This module adds what
FastAPI cannot know: the public summary of each operation, response schemas and examples, the error
responses (from the error-code catalogue, API-02), authentication, the dated version header and the
webhook events (OpenAPI 3.1 `webhooks`). Console routes are left out.

`make openapi` writes `docs/api/openapi.json`. A unit test fails if the checked-in file and the code
drift, and CI lints the file with Redocly. Never edit the file by hand.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from fastapi import FastAPI

from detent.api.error_codes import CATALOGUE
from detent.api.limits import CURRENT_VERSION, VERSION_HEADER
from detent.webhooks.events import EVENT_TYPES, TEST_EVENT_TYPE
from detent.webhooks.signing import SIGNATURE_HEADER

DOCS_PATH = "docs/api/openapi.json"
REF = "#/components/schemas/"


TAG_TEXT: dict[str, str] = {
    "decisions": "Dry-run a payment against the active rules without creating it.",
    "deposit_intents": "Expected deposits and how incoming funds are matched to them.",
    "events": "Every webhook event, also available by polling.",
    "exceptions": "The exceptions queue: escalations, overdue cases and breaks, with their facts.",
    "kill_switch": "Hold every payout at once. Only the client's payments lead can release it.",
    "mandates": "What each AI agent may propose, within which limits.",
    "payment_intents": "Payouts: one ID for life, decided by the rules, sent exactly once.",
    "policy": "The client-owned rule set and its versions.",
    "reconciliation": "Reconciliation runs and the breaks they find.",
    "request_logs": "Your recent API requests, for debugging.",
    "webhook_endpoints": "Where events are sent, signed, with retries and resends.",
}


def _ref(name: str) -> dict[str, str]:
    return {"$ref": REF + name}


def _list_of(name: str) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["data", "has_more", "next_cursor"],
        "properties": {
            "data": {"type": "array", "items": _ref(name)},
            "has_more": {"type": "boolean"},
            "next_cursor": {
                "type": ["string", "null"],
                "description": "Pass as `starting_after` for the next page.",
            },
        },
    }


MONEY = {
    "type": "object",
    "required": ["amount", "currency"],
    "properties": {
        "amount": {
            "type": "string",
            "pattern": r"^\d+(\.\d+)?$",
            "example": "18500.00",
            "description": "A decimal string. Money is never a float.",
        },
        "currency": {"type": "string", "enum": ["USDC", "GBP", "EUR"]},
    },
}

SCHEMAS: dict[str, Any] = {
    "Money": MONEY,
    "Error": {
        "type": "object",
        "required": ["error"],
        "properties": {
            "error": {
                "type": "object",
                "required": ["type", "code", "message", "payment_id", "request_id", "param"],
                "properties": {
                    "type": {"type": "string", "enum": sorted({c.type for c in CATALOGUE} | {"quota"})},
                    "code": {
                        "type": "string",
                        "enum": [c.code for c in CATALOGUE],
                        "description": "The exact reason. See the error-code reference.",
                    },
                    "message": {"type": "string", "description": "For people; may change."},
                    "payment_id": {"type": ["string", "null"]},
                    "request_id": {
                        "type": ["string", "null"],
                        "description": "Also on the `Request-Id` header.",
                    },
                    "param": {"type": ["string", "null"], "description": "The field or header at fault."},
                },
            }
        },
    },
    "Decision": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "example": "dec_01JDQ3ZJ6M4N8Q2R5T7V9X1Z3B"},
            "outcome": {"type": "string", "enum": ["EXECUTE", "ESCALATE", "BLOCK"]},
            "policy_version": {"type": "integer"},
            "policy_hash": {"type": "string"},
            "checks": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Every check with its result and reason code.",
            },
            "approved_reasons": {"type": "array", "items": {"type": "string"}},
            "route": {"type": ["object", "null"]},
            "decided_at": {"type": "string", "format": "date-time"},
        },
    },
    "PaymentIntent": {
        "type": "object",
        "description": "One payment for life: retries, failovers and approvals keep the `pay_` ID.",
        "properties": {
            "id": {"type": "string", "example": "pay_01JDQ3ZJ6M4N8Q2R5T7V9X1Z3B"},
            "status": {
                "type": "string",
                "enum": [
                    "RECEIVED",
                    "BLOCKED",
                    "ESCALATED",
                    "READY",
                    "SHADOWED",
                    "HELD",
                    "SUBMITTED",
                    "UNKNOWN",
                    "CONFIRMED",
                    "FAILED",
                    "FAILED_FINAL",
                    "REJECTED",
                    "CANCELLED",
                ],
                "description": "A timeout is UNKNOWN, never FAILED; nothing is resent while UNKNOWN.",
            },
            "source": {"type": "string", "enum": ["platform", "agent"]},
            "amount": _ref("Money"),
            "counterparty_id": {"type": ["string", "null"]},
            "user_account_ref": {"type": ["string", "null"]},
            "destination": {"type": "object"},
            "reference": {"type": ["string", "null"]},
            "decision": {"oneOf": [_ref("Decision"), {"type": "null"}]},
            "exception": {"type": ["object", "null"], "description": "The open case, if any."},
            "awaiting_send_click": {"type": ["boolean", "null"]},
            "created_at": {"type": "string", "format": "date-time"},
        },
    },
    "Exception": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "example": "exc_01JDQ3ZJ6M4N8Q2R5T7V9X1Z3B"},
            "object": {"const": "exception"},
            "type": {"type": "string"},
            "status": {"type": "string", "enum": ["OPEN", "HELD_OVERDUE", "RESOLVED"]},
            "payment_id": {"type": ["string", "null"]},
            "deposit_id": {"type": ["string", "null"]},
            "tier": {"type": "integer"},
            "reasons": {
                "type": "array",
                "items": {"type": "string"},
                "example": ["FIRST_PAYMENT", "ABOVE_AUTO_LIMIT"],
            },
            "owner_id": {"type": ["string", "null"]},
            "backup_owner_id": {"type": ["string", "null"]},
            "deadline_at": {
                "type": "string",
                "format": "date-time",
                "description": "An overdue case stays held; a timeout never becomes an approval.",
            },
            "resolution": {
                "type": ["string", "null"],
                "enum": ["approved", "rejected", "cancelled", "superseded", None],
            },
            "resolved_by": {"type": ["string", "null"]},
            "resolved_at": {"type": ["string", "null"], "format": "date-time"},
            "created": {"type": "string", "format": "date-time"},
        },
    },
    "ExceptionDetail": {
        "allOf": [
            _ref("Exception"),
            {
                "type": "object",
                "properties": {
                    "resolution_reason": {"type": ["string", "null"]},
                    "raw_facts": {
                        "type": ["object", "null"],
                        "description": "What the reviewer reads first: payee, destination, amount, history.",
                    },
                    "rule_hits": {"type": "array", "items": {"type": "object"}},
                    "investigation": {
                        "type": ["object", "null"],
                        "description": "The investigation agent's cited evidence. The rules decide.",
                    },
                    "history": {"type": "array", "items": {"type": "object"}},
                },
            },
        ],
    },
    "Resolution": {
        "type": "object",
        "properties": {
            "case_id": {"type": "string"},
            "payment_id": {"type": ["string", "null"]},
            "payment_status": {"type": ["string", "null"]},
            "new_case_id": {
                "type": ["string", "null"],
                "description": "Set when the policy re-run found a new reason and opened a new case.",
            },
        },
    },
    "Event": {
        "type": "object",
        "description": "Delivered by webhooks and listed by GET /v1/events. Deduplicate on `id`.",
        "required": ["id", "type", "created", "sequence", "test", "data"],
        "properties": {
            "id": {"type": "string", "example": "evt_01JDQ3ZJ6M4N8Q2R5T7V9X1Z3B"},
            "type": {"type": "string", "enum": [*EVENT_TYPES, TEST_EVENT_TYPE]},
            "created": {"type": "integer", "description": "Unix seconds.", "example": 1764756000},
            "sequence": {"type": "integer", "description": "Increases per payment (or per subject)."},
            "test": {"type": "boolean", "description": "True only for 'send test event'."},
            "data": {"type": "object", "required": ["object"], "properties": {"object": {"type": "object"}}},
        },
    },
    "WebhookEndpoint": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "example": "whe_01JDQ3ZJ6M4N8Q2R5T7V9X1Z3B"},
            "object": {"const": "webhook_endpoint"},
            "url": {"type": "string", "format": "uri"},
            "event_types": {"type": "array", "items": {"type": "string"}},
            "description": {"type": ["string", "null"]},
            "status": {"type": "string", "enum": ["enabled", "disabled"]},
            "secret_fingerprint": {"type": ["string", "null"]},
            "created": {"type": "string", "format": "date-time"},
        },
    },
    "WebhookEndpointCreated": {
        "allOf": [
            _ref("WebhookEndpoint"),
            {
                "type": "object",
                "properties": {
                    "secret": {
                        "type": ["string", "null"],
                        "example": "whsec_...",
                        "description": "Shown once. A replay of the same request returns null.",
                    }
                },
            },
        ],
    },
    "WebhookDelivery": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "example": "whd_01JDQ3ZJ6M4N8Q2R5T7V9X1Z3B"},
            "object": {"const": "webhook_delivery"},
            "endpoint_id": {"type": "string"},
            "event_id": {"type": "string"},
            "event_type": {"type": "string"},
            "attempt": {"type": "integer", "minimum": 1, "maximum": 7},
            "status_code": {"type": ["integer", "null"]},
            "error": {"type": ["string", "null"]},
            "latency_ms": {"type": ["integer", "null"]},
            "outcome": {"type": "string", "enum": ["succeeded", "retrying", "failed"]},
            "next_attempt_at": {"type": ["string", "null"], "format": "date-time"},
            "manual": {"type": "boolean"},
            "created": {"type": "string", "format": "date-time"},
        },
    },
    "RequestLog": {
        "type": "object",
        "description": "Metadata only: no bodies, no query strings, no keys. Kept 30 days.",
        "properties": {
            "id": {"type": "integer"},
            "key_id": {"type": ["string", "null"]},
            "method": {"type": "string"},
            "path": {"type": "string"},
            "status": {"type": "integer"},
            "latency_ms": {"type": "integer"},
            "idempotency_key": {"type": ["string", "null"]},
            "payment_id": {"type": ["string", "null"]},
            "request_id": {"type": "string"},
            "at": {"type": "string", "format": "date-time"},
        },
    },
    "Accepted": {"type": "object", "description": "The work is queued."},
    "Object": {"type": "object"},
}

# Per operation: summary, the success response's schema, and the extra error statuses it can return.
OPS: dict[tuple[str, str], tuple[str, str, tuple[int, ...]]] = {
    ("post", "/v1/payment_intents"): ("Create and decide a payout intent", "PaymentIntent", (409, 422)),
    ("get", "/v1/payment_intents"): ("List payment intents", "list:PaymentIntent", (422,)),
    ("post", "/v1/decisions"): ("Decide without creating a payment (dry run)", "Decision", (409, 422)),
    ("get", "/v1/payment_intents/{payment_id}"): (
        "Get a payment intent with its history",
        "PaymentIntent",
        (404,),
    ),
    ("post", "/v1/payment_intents/{payment_id}/send"): (
        "Confirm sending (assist mode)",
        "PaymentIntent",
        (404, 409),
    ),
    ("post", "/v1/payment_intents/{payment_id}/cancel"): (
        "Cancel a payment before it is sent",
        "PaymentIntent",
        (404, 409, 422),
    ),
    ("get", "/v1/payment_intents/{payment_id}/replay"): ("Replay a payment's decisions", "Object", (404,)),
    ("get", "/v1/exceptions"): ("List exceptions", "list:Exception", (422,)),
    ("get", "/v1/exceptions/{case_id}"): ("Get an exception with its raw facts", "ExceptionDetail", (404,)),
    ("post", "/v1/exceptions/{case_id}/approve"): (
        "Approve an exception (re-runs the policy)",
        "Resolution",
        (404, 409, 422),
    ),
    ("post", "/v1/exceptions/{case_id}/reject"): ("Reject an exception", "Resolution", (404, 409, 422)),
    ("post", "/v1/kill_switch"): ("Engage the kill switch", "Object", ()),
    ("delete", "/v1/kill_switch"): ("Release the kill switch (payments lead only)", "Object", ()),
    ("get", "/v1/request_logs"): ("List this organisation's request logs", "list:RequestLog", (422,)),
    ("get", "/v1/mandates"): ("List agent mandates", "Object", ()),
    ("post", "/v1/mandates/{mandate_id}/revoke"): ("Revoke an agent mandate", "Object", (404,)),
    ("get", "/v1/policy/versions"): ("List rule versions", "Object", ()),
    ("get", "/v1/policy/versions/{version}"): ("Get a rule version", "Object", (404,)),
    ("post", "/v1/deposit_intents"): ("Create deposit instructions", "Object", (409, 422)),
    ("get", "/v1/deposit_intents/{deposit_id}"): ("Get a deposit intent and its credits", "Object", (404,)),
    ("get", "/v1/reconciliation/runs"): ("List reconciliation runs", "Object", ()),
    ("get", "/v1/reconciliation/breaks"): ("List reconciliation breaks", "Object", (422,)),
    ("post", "/v1/webhook_endpoints"): (
        "Create a webhook endpoint",
        "WebhookEndpointCreated",
        (409, 422, 503),
    ),
    ("get", "/v1/webhook_endpoints"): ("List webhook endpoints", "list:WebhookEndpoint", ()),
    ("get", "/v1/webhook_endpoints/{endpoint_id}"): ("Get a webhook endpoint", "WebhookEndpoint", (404,)),
    ("delete", "/v1/webhook_endpoints/{endpoint_id}"): (
        "Disable a webhook endpoint",
        "WebhookEndpoint",
        (404,),
    ),
    ("post", "/v1/webhook_endpoints/{endpoint_id}/test"): ("Send a test event", "Accepted", (404, 409)),
    ("get", "/v1/webhook_endpoints/{endpoint_id}/deliveries"): (
        "List an endpoint's deliveries",
        "list:WebhookDelivery",
        (404, 422),
    ),
    ("post", "/v1/webhook_endpoints/{endpoint_id}/resend"): (
        "Resend an event to an endpoint",
        "Accepted",
        (404, 422),
    ),
    ("get", "/v1/events"): ("List events", "list:Event", (422,)),
    ("get", "/v1/events/{event_id}"): ("Get an event", "Event", (404,)),
}

COMMON_ERRORS = (401, 403, 429, 500)
STATUS_TEXT = {
    400: "Bad request",
    401: "Not authenticated",
    403: "Not allowed",
    404: "Not found",
    409: "Conflict",
    422: "Invalid request",
    429: "Too many requests",
    500: "Internal error",
    503: "Unavailable",
}


def _error_response(status: int) -> dict[str, Any]:
    codes = [c for c in CATALOGUE if status in c.statuses]
    examples = {
        c.code: {
            "summary": c.meaning,
            "value": {
                "error": {
                    "type": c.type,
                    "code": c.code,
                    "message": c.meaning,
                    "payment_id": None,
                    "request_id": "req_4f7c1e1a2b3c4d5e6f708192",
                    "param": None,
                }
            },
        }
        for c in codes
    }
    out: dict[str, Any] = {
        "description": STATUS_TEXT.get(status, "Error") + ": " + ", ".join(f"`{c.code}`" for c in codes),
        "content": {"application/json": {"schema": _ref("Error"), "examples": examples}},
    }
    if status == 429:
        out["headers"] = {"Retry-After": {"schema": {"type": "integer"}, "description": "Seconds to wait."}}
    return out


def _success_schema(spec: str) -> dict[str, Any]:
    return _list_of(spec[5:]) if spec.startswith("list:") else _ref(spec)


def _operation_id(path: str, method: str) -> str:
    parts = [p.strip("{}") for p in path.removeprefix("/v1/").split("/")]
    return method + "".join(p.replace("_", " ").title().replace(" ", "") for p in parts)


def build(app: FastAPI) -> dict[str, Any]:
    raw = copy.deepcopy(app.openapi())
    paths = {p: v for p, v in raw["paths"].items() if p.startswith("/v1/")}
    used: set[str] = set()
    for path, item in paths.items():
        for method, op in item.items():
            key = (method, path)
            if key not in OPS:
                raise KeyError(
                    f"no OpenAPI entry for {method.upper()} {path}; add it to detent.api.openapi.OPS"
                )
            summary, schema, errors = OPS[key]
            used.add(f"{method} {path}")
            op["summary"] = summary
            op["operationId"] = _operation_id(path, method)
            op["tags"] = [path.removeprefix("/v1/").split("/")[0]]
            params = [p for p in op.get("parameters", []) if p.get("name") != VERSION_HEADER]
            params.append({"$ref": "#/components/parameters/Version"})
            op["parameters"] = params
            status = next((s for s in op["responses"] if s.startswith("2")), "200")
            ok = {"description": op["responses"].get(status, {}).get("description", "OK")}
            ok["content"] = {"application/json": {"schema": _success_schema(schema)}}
            ok["headers"] = {
                "Request-Id": {"$ref": "#/components/headers/RequestId"},
                "RateLimit-Limit": {"$ref": "#/components/headers/RateLimitLimit"},
                "RateLimit-Remaining": {"$ref": "#/components/headers/RateLimitRemaining"},
                "RateLimit-Reset": {"$ref": "#/components/headers/RateLimitReset"},
            }
            responses: dict[str, Any] = {status: ok}
            for s in sorted({*COMMON_ERRORS, *errors, 400}):
                responses[str(s)] = _error_response(s)
            op["responses"] = responses
    missing = sorted(f"{m.upper()} {p}" for (m, p) in OPS if f"{m} {p}" not in used)
    if missing:
        raise KeyError(f"OpenAPI entries for routes that do not exist: {missing}")
    schemas = {
        k: v
        for k, v in raw.get("components", {}).get("schemas", {}).items()
        if not k.startswith("Body_") and k not in ("HTTPValidationError", "ValidationError")
    }
    schemas.update(SCHEMAS)
    event_webhooks = {
        t: {
            "post": {
                "summary": f"{t} event",
                "operationId": "event" + "".join(p.title() for p in t.replace(".", "_").split("_")),
                "parameters": [
                    {
                        "name": SIGNATURE_HEADER,
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string"},
                        "example": "t=1764756000,v1=5257a869...",
                    }
                ],
                "requestBody": {"required": True, "content": {"application/json": {"schema": _ref("Event")}}},
                "responses": {
                    "200": {"description": "Any 2xx acknowledges the event; anything else is retried."}
                },
            }
        }
        for t in (*EVENT_TYPES, TEST_EVENT_TYPE)
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "DekernAI API (sandbox)",
            "version": CURRENT_VERSION,
            "summary": "Agentic payment controls: decision, orchestration and operations.",
            "description": (
                "The public sandbox API. Test networks only: `sk_live_` keys are always refused. "
                "The AI proposes and the client's rules decide. Generated from the code (API-05); "
                "see the [error codes](/api/errors) for every `error.code` and the [changelog](/changelog) "
                "for what changed in each version."
            ),
            "license": {"name": "Proprietary", "identifier": "LicenseRef-Proprietary"},
        },
        "servers": [
            {
                "url": "http://localhost:8000",
                "description": "Local development (make dev). "
                "The public sandbox address is published at launch.",
            }
        ],
        "security": [{"bearer": []}],
        "tags": [
            {"name": t, "description": TAG_TEXT[t]}
            for t in sorted({op["tags"][0] for i in paths.values() for op in i.values()})
        ],
        "paths": paths,
        "webhooks": event_webhooks,
        "components": {
            "securitySchemes": {
                "bearer": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "`Authorization: Bearer sk_test_...`",
                }
            },
            "parameters": {
                "Version": {
                    "name": VERSION_HEADER,
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string", "enum": [CURRENT_VERSION]},
                    "description": "Dated API version. Omit it to use your organisation's pinned version.",
                }
            },
            "headers": {
                "RequestId": {
                    "schema": {"type": "string"},
                    "description": "Quote it when you contact DekernAI.",
                },
                "RateLimitLimit": {"schema": {"type": "integer"}},
                "RateLimitRemaining": {"schema": {"type": "integer"}},
                "RateLimitReset": {
                    "schema": {"type": "integer"},
                    "description": "Seconds until the window resets.",
                },
            },
            "schemas": dict(sorted(schemas.items())),
        },
    }


def render(app: FastAPI) -> str:
    return json.dumps(build(app), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    from sqlalchemy import create_engine

    from detent.api.app import create_app
    from detent.settings import Settings

    s = Settings(_env_file=None, app_env="test")
    app = create_app(s, engine=create_engine(s.database_url), configure_logging=False)
    print(render(app), end="")


if __name__ == "__main__":
    main()
