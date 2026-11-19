"""Run an ASGI app (fault proxy, bank simulator) on a free local port inside a test."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import uvicorn


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def serve(app: Any) -> Iterator[str]:
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(f"{url}/healthz", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    try:
        yield url
    finally:
        server.should_exit = True
        t.join(timeout=5)


def fault(proxy_url: str, match: str, kind: str, count: int = 1, attempt: str | None = None) -> None:
    r = httpx.post(
        f"{proxy_url}/__faults", json={"match": match, "fault": kind, "count": count, "attempt": attempt}
    )
    r.raise_for_status()


def clear_faults(proxy_url: str) -> None:
    httpx.delete(f"{proxy_url}/__faults").raise_for_status()


def fault_log(proxy_url: str) -> list[dict[str, Any]]:
    return list(httpx.get(f"{proxy_url}/__faults/log").json())
