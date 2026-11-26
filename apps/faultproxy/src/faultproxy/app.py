"""Fault-injection proxy (RAL-05, spec/06). Test and sandbox only.

It sits between Dekernai's rail adapters and an upstream (a JSON-RPC node or the bank simulator) and
passes everything through, unless a scenario says to inject a fault into the next matching calls.

Scenarios (``POST /__faults``)::

    {"match": "eth_sendRawTransaction", "fault": "timeout_after_forward", "count": 1}
    {"match": "eth_getTransactionReceipt", "fault": "hide_receipt", "count": 3}     # delayed receipt
    {"match": "eth_getTransactionReceipt", "fault": "hide_receipt", "count": -1}    # stuck
    {"match": "POST /payments", "fault": "duplicate_request", "count": 1}

``match`` is a JSON-RPC method, or ``"<HTTP method> <path prefix>"``. ``count`` -1 means until cleared.
An optional ``attempt`` limits the scenario to requests carrying that ``X-Dekernai-Attempt`` header, and an
optional ``body_contains`` to requests whose body contains that text, ignoring case (the demo batch uses it
to revert only the transfer of 75.42 USDC: ``"body_contains": "047ed160"``, S9).
Every injected fault is logged with the attempt ID (``GET /__faults/log``).

Faults:
- ``timeout_after_forward``: forwards the request, then answers nothing until the client gives up.
- ``timeout_before_forward``: never forwards; answers nothing.
- ``reset_after_forward``: forwards, then breaks the response mid-way (the client sees a broken connection).
- ``http_503_before_accept``: 503 without forwarding (the rail never saw it).
- ``hide_receipt``: answers ``null`` for a receipt without forwarding (delayed or stuck receipt).
- ``duplicate_request``: forwards the request twice and returns the first answer.
- ``low_gas_estimate``: answers ``eth_estimateGas`` with 21000, so the signed transfer runs out of gas
  on chain and its receipt has status 0 (a genuine revert; no money moves).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

log = logging.getLogger("faultproxy")

FAULTS = {
    "timeout_after_forward",
    "timeout_before_forward",
    "reset_after_forward",
    "http_503_before_accept",
    "hide_receipt",
    "duplicate_request",
    "low_gas_estimate",
}


@dataclass
class Scenario:
    match: str
    fault: str
    count: int = 1
    attempt: str | None = None
    body_contains: str | None = None


@dataclass
class State:
    upstream: str
    hold_seconds: float
    scenarios: list[Scenario] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def take(self, keys: list[str], attempt: str | None, body: bytes = b"") -> Scenario | None:
        text = body.decode("utf-8", errors="replace").lower()
        with self.lock:
            for s in self.scenarios:
                if (
                    s.match in keys
                    and (s.attempt is None or s.attempt == attempt)
                    and (s.body_contains is None or s.body_contains.lower() in text)
                    and s.count != 0
                ):
                    if s.count > 0:
                        s.count -= 1
                    return s
        return None


def _keys(method: str, path: str, body: bytes) -> list[str]:
    keys = []
    try:
        data = json.loads(body) if body else None
    except ValueError:
        data = None
    if isinstance(data, dict) and "method" in data:
        keys.append(str(data["method"]))
    keys.append(f"{method} {path}")
    # path prefixes, so "POST /payments" matches "POST /payments/abc"
    parts = path.rstrip("/").split("/")
    for i in range(len(parts) - 1, 1, -1):
        keys.append(f"{method} {'/'.join(parts[:i])}")
    return keys


def create_app(upstream: str | None = None, *, hold_seconds: float = 5.0, demo_mode: bool = False) -> FastAPI:
    state = State(
        upstream=(upstream or os.environ.get("FAULTPROXY_UPSTREAM", "")).rstrip("/"),
        hold_seconds=hold_seconds,
    )
    app = FastAPI(title="Dekernai fault-injection proxy (test only)")
    app.state.faults = state

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        return {"status": "ok", "upstream": state.upstream, "scenarios": len(state.scenarios)}

    @app.post("/__faults")
    async def add(request: Request) -> JSONResponse:
        if demo_mode and request.headers.get("x-dekernai-scenario-runner") != "1":
            return JSONResponse({"error": "faults are disabled in demo mode"}, status_code=403)
        body = await request.json()
        if body.get("fault") not in FAULTS:
            return JSONResponse({"error": f"unknown fault {body.get('fault')!r}"}, status_code=422)
        with state.lock:
            state.scenarios.append(
                Scenario(
                    body["match"],
                    body["fault"],
                    int(body.get("count", 1)),
                    body.get("attempt"),
                    body.get("body_contains"),
                )
            )
        return JSONResponse({"ok": True}, status_code=201)

    @app.get("/__faults")
    def armed() -> list[dict[str, Any]]:
        with state.lock:
            return [
                {
                    "match": s.match,
                    "fault": s.fault,
                    "count": s.count,
                    "attempt": s.attempt,
                    "body_contains": s.body_contains,
                }
                for s in state.scenarios
            ]

    @app.delete("/__faults")
    def clear() -> dict[str, bool]:
        with state.lock:
            state.scenarios.clear()
        return {"ok": True}

    @app.get("/__faults/log")
    def fault_log() -> list[dict[str, Any]]:
        with state.lock:
            return list(state.log)

    async def forward(request: Request, body: bytes) -> httpx.Response:
        headers = {k: v for k, v in request.headers.items() if k.lower() not in {"host", "content-length"}}
        async with httpx.AsyncClient(timeout=30) as client:
            return await client.request(
                request.method,
                f"{state.upstream}{request.url.path}",
                params=request.query_params,
                content=body,
                headers=headers,
            )

    def passthrough(r: httpx.Response) -> Response:
        return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def proxy(path: str, request: Request) -> Response:  # noqa: PLR0911 - one return per fault
        body = await request.body()
        attempt = request.headers.get("x-dekernai-attempt")
        keys = _keys(request.method, "/" + path, body)
        s = state.take(keys, attempt, body)
        if s is None:
            return passthrough(await forward(request, body))
        entry = {"fault": s.fault, "match": s.match, "attempt": attempt, "at": time.time()}
        with state.lock:
            state.log.append(entry)
        log.warning("injecting fault", extra=entry)
        if s.fault == "timeout_after_forward":
            await forward(request, body)
            await asyncio.sleep(state.hold_seconds)
            return Response(status_code=504)
        if s.fault == "timeout_before_forward":
            await asyncio.sleep(state.hold_seconds)
            return Response(status_code=504)
        if s.fault == "http_503_before_accept":
            return Response("service unavailable", status_code=503)
        if s.fault == "hide_receipt":
            rid = json.loads(body).get("id", 1) if body else 1
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": None})
        if s.fault == "low_gas_estimate":
            rid = json.loads(body).get("id", 1) if body else 1
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": hex(21000)})
        if s.fault == "duplicate_request":
            first = await forward(request, body)
            await forward(request, body)
            return passthrough(first)
        # reset_after_forward: the upstream did the work; the client's answer breaks off mid-way.
        upstream = await forward(request, body)

        async def broken() -> Any:
            yield upstream.content[: max(1, len(upstream.content) // 2)]
            raise ConnectionResetError("faultproxy: reset after forward")

        return StreamingResponse(
            broken(), status_code=200, headers={"content-length": str(len(upstream.content) + 100)}
        )

    return app


# FAULTPROXY_DEMO_MODE=1 (the deployed demo, S9): only the scenario runner may arm faults.
app = create_app(demo_mode=os.environ.get("FAULTPROXY_DEMO_MODE") == "1")
