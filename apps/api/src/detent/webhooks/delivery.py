"""WHK-03: delivery, retries and the delivery log.

Each event gets one `webhook.deliver` job per subscribed endpoint, enqueued in the transaction that
wrote the event (the transactional outbox; FND-06 queue). A delivery is an HTTPS POST of the stored
envelope, signed with the endpoint's secret (WHK-02), with a 10-second timeout and no redirects. A 2xx
answer is success. Anything else is retried at 1 min, 5 min, 30 min, 2 h, 6 h and 24 h, then marked
failed (G-20, D-38). Every attempt is a row in `webhook_deliveries` with its status code and time.

Delivery is at least once: a worker that dies after the POST but before committing sends again, which
is why every event carries `id` for the receiver to deduplicate on.
"""

from __future__ import annotations

import json
import secrets
import time
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import Connection, text

from detent.clock import Clock
from detent.domain.ids import Prefix, new_id
from detent.settings import Settings
from detent.webhooks import endpoints, signing
from detent.webhooks.events import ALL_TYPES, TEST_EVENT_TYPE, emit
from detent.worker.queue import enqueue
from detent.worker.registry import JobContext, handler

JOB_KIND = "webhook.deliver"
RETRY_DELAYS: tuple[timedelta, ...] = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=6),
    timedelta(hours=24),
)
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
USER_AGENT = "DekernAI-Webhooks/1"
# Tests may replace the transport (httpx.MockTransport); production always uses the network.
TRANSPORT: httpx.BaseTransport | None = None


def _job(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    endpoint_id: str,
    event_id: str,
    attempt: int,
    manual: bool,
    run_at: Any = None,
    chain: str,
) -> str | None:
    return enqueue(
        conn,
        clock,
        org_id=org_id,
        kind=JOB_KIND,
        payload={
            "endpoint_id": endpoint_id,
            "event_id": event_id,
            "attempt": attempt,
            "manual": manual,
            "chain": chain,
        },
        run_at=run_at,
        dedupe_key=f"{chain}:{attempt}",
    )


def enqueue_deliveries(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    event_id: str,
    type_: str,
    only_endpoint: str | None = None,
) -> list[str]:
    """One delivery chain per enabled endpoint subscribed to the type. Test events go to one endpoint."""
    if only_endpoint is not None:
        ids = [only_endpoint]
    elif type_ == TEST_EVENT_TYPE:
        ids = []
    else:
        ids = list(
            conn.execute(
                text(
                    "SELECT id FROM webhook_endpoints WHERE org_id=:o AND disabled_at IS NULL "
                    "AND (:t = ANY(event_types) OR :all = ANY(event_types)) ORDER BY id"
                ),
                {"o": org_id, "t": type_, "all": ALL_TYPES},
            ).scalars()
        )
    for eid in ids:
        _job(conn, clock, org_id=org_id, endpoint_id=eid, event_id=event_id, attempt=1, manual=False,
             chain=f"{eid}:{event_id}")  # fmt: skip
    return ids


def resend(conn: Connection, clock: Clock, *, org_id: str, endpoint_id: str, event_id: str) -> None:
    """Manual resend from the delivery log: a fresh chain of attempts, whatever happened before."""
    endpoints.get(conn, org_id, endpoint_id)
    found = conn.execute(
        text("SELECT 1 FROM webhook_events WHERE org_id=:o AND id=:e"), {"o": org_id, "e": event_id}
    ).one_or_none()
    if found is None:
        raise endpoints.EndpointError("not_found", "No such event.", status=404, param="event_id")
    chain = f"{endpoint_id}:{event_id}:manual:{secrets.token_hex(6)}"
    _job(
        conn,
        clock,
        org_id=org_id,
        endpoint_id=endpoint_id,
        event_id=event_id,
        attempt=1,
        manual=True,
        chain=chain,
    )


def send_test(conn: Connection, clock: Clock, *, org_id: str, endpoint_id: str) -> str:
    """'Send test event' (G-20: test events carry `"test": true`). Delivered to this endpoint only."""
    row = endpoints.get(conn, org_id, endpoint_id)
    if row.disabled_at is not None:
        raise endpoints.EndpointError("endpoint_disabled", "The endpoint is disabled.", status=409)
    obj = {"object": "test", "message": "A test event from DekernAI. Nothing happened to any payment."}
    return emit(
        conn, clock, org_id=org_id, type_=TEST_EVENT_TYPE, subject_id=endpoint_id, payment_id=None, obj=obj,
        test=True, only_endpoint=endpoint_id,
    )  # fmt: skip


def body_bytes(envelope: dict[str, Any]) -> bytes:
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()


def _post(
    settings: Settings, url: str, headers: dict[str, str], body: bytes
) -> tuple[int | None, str | None, int]:
    started = time.perf_counter()  # duration only; domain time comes from the Clock
    try:
        with httpx.Client(
            timeout=settings.webhook_timeout_seconds, follow_redirects=False, transport=TRANSPORT
        ) as client:
            r = client.post(url, content=body, headers=headers)
        status, error = r.status_code, None if 200 <= r.status_code < 300 else f"HTTP {r.status_code}"
    except httpx.TimeoutException:
        status, error = None, "timeout"
    except httpx.HTTPError as exc:
        status, error = None, f"connection error: {type(exc).__name__}"
    return status, error, round((time.perf_counter() - started) * 1000)


@handler(JOB_KIND)
def deliver_job(ctx: JobContext) -> None:
    p = ctx.job.payload
    org_id, endpoint_id, event_id = ctx.job.org_id, str(p["endpoint_id"]), str(p["event_id"])
    attempt, manual, chain = int(p["attempt"]), bool(p.get("manual")), str(p["chain"])
    if ctx.settings is None:
        raise RuntimeError("webhook delivery needs settings")
    conn, clock = ctx.conn, ctx.clock
    ep = endpoints.get(conn, org_id, endpoint_id)
    if ep.disabled_at is not None:
        return  # disabled since: nothing is sent and nothing more is tried
    event = conn.execute(
        text("SELECT payload FROM webhook_events WHERE org_id=:o AND id=:e"), {"o": org_id, "e": event_id}
    ).one()
    body = body_bytes(dict(event.payload))
    now = clock.now()
    try:
        endpoints.check_url(ep.url, ctx.settings, resolve=True)
        secret = endpoints.decrypt_secret(ctx.settings, ep.secret_encrypted)
    except endpoints.EndpointError as exc:
        status, latency = None, 0
        error: str | None = f"not sent: {exc}"
    else:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            signing.SIGNATURE_HEADER: signing.sign(secret, int(now.timestamp()), body),
            "DekernAI-Event-Id": event_id,
            "DekernAI-Delivery-Attempt": str(attempt),
        }
        status, error, latency = _post(ctx.settings, ep.url, headers, body)
    ok = error is None
    retry_at = None if ok or attempt >= MAX_ATTEMPTS else now + RETRY_DELAYS[attempt - 1]
    outcome = "succeeded" if ok else ("retrying" if retry_at else "failed")
    conn.execute(
        text(
            "INSERT INTO webhook_deliveries (id, org_id, endpoint_id, event_id, attempt, status_code, error, "
            "latency_ms, outcome, next_attempt_at, manual, created_at) "
            "VALUES (:id, :o, :ep, :ev, :a, :s, :err, :lat, :out, :next, :m, :now)"
        ),
        {
            "id": new_id(Prefix.WHD, now),
            "o": org_id,
            "ep": endpoint_id,
            "ev": event_id,
            "a": attempt,
            "s": status,
            "err": error,
            "lat": latency,
            "out": outcome,
            "next": retry_at,
            "m": manual,
            "now": now,
        },
    )
    if retry_at is not None:
        _job(conn, clock, org_id=org_id, endpoint_id=endpoint_id, event_id=event_id, attempt=attempt + 1,
             manual=manual, run_at=retry_at, chain=chain)  # fmt: skip


def delivery_json(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "object": "webhook_delivery",
        "endpoint_id": row.endpoint_id,
        "event_id": row.event_id,
        "event_type": row.type,
        "attempt": row.attempt,
        "status_code": row.status_code,
        "error": row.error,
        "latency_ms": row.latency_ms,
        "outcome": row.outcome,
        "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
        "manual": row.manual,
        "created": row.created_at.isoformat(),
    }


def list_deliveries(
    conn: Connection, org_id: str, endpoint_id: str, *, limit: int, starting_after: str | None
) -> tuple[list[dict[str, Any]], bool]:
    endpoints.get(conn, org_id, endpoint_id)
    rows = conn.execute(
        text(
            "SELECT d.*, e.type FROM webhook_deliveries d JOIN webhook_events e "
            "ON e.org_id = d.org_id AND e.id = d.event_id "
            "WHERE d.org_id=:o AND d.endpoint_id=:ep AND (CAST(:after AS TEXT) IS NULL OR d.pos < "
            "(SELECT pos FROM webhook_deliveries WHERE org_id=:o AND id=:after)) "
            "ORDER BY d.pos DESC LIMIT :n"
        ),
        {"o": org_id, "ep": endpoint_id, "after": starting_after, "n": limit + 1},
    ).all()
    return [delivery_json(r) for r in rows[:limit]], len(rows) > limit
