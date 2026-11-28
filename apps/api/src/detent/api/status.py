"""WEB-07: ``GET /status.json``, the public status of the sandbox API, the dashboard and the docs.

The website's status page reads it from the browser, so it answers any origin and holds nothing private:
three component states and the time of the check. The website lives on another host, so if this app is
down the page still loads and says the sandbox API and dashboard can't be reached.

- Sandbox API: the database answers ``SELECT 1`` (every ``/v1`` call needs it).
- Dashboard: served by the same process, so it shares that check.
- Docs: an HTTP GET of ``STATUS_DOCS_URL`` (2xx or 3xx is up); ``not_monitored`` while it is empty.

One round of checks is reused for ``STATUS_CACHE_SECONDS`` so the public page can't load the database.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

log = logging.getLogger(__name__)
router = APIRouter()

COMPONENTS = (("sandbox_api", "Sandbox API"), ("dashboard", "Dashboard"), ("docs", "Docs"))
_lock = threading.Lock()


def _docs(url: str) -> str:
    if not url:
        return "not_monitored"
    try:
        r = httpx.get(url, timeout=3.0, follow_redirects=False)
    except httpx.HTTPError as exc:
        log.warning("status docs check failed", extra={"error": type(exc).__name__})
        return "down"
    return "operational" if r.status_code < 400 else "down"


def _check(request: Request, now: datetime) -> dict[str, Any]:
    rt = request.app.state.runtime
    try:
        with rt.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db = "operational"
    except Exception as exc:  # report, never raise, from a health check
        log.warning("status database check failed", extra={"error": type(exc).__name__})
        db = "down"
    states = {"sandbox_api": db, "dashboard": db, "docs": _docs(rt.settings.status_docs_url)}
    return {
        "checked_at": now.isoformat().replace("+00:00", "Z"),
        "components": [{"id": i, "name": n, "status": states[i]} for i, n in COMPONENTS],
    }


@router.get("/status.json", include_in_schema=False)
def status(request: Request) -> JSONResponse:
    rt = request.app.state.runtime
    now = rt.clock.now()
    with _lock:
        cached: tuple[datetime, dict[str, Any]] | None = getattr(request.app.state, "status_cache", None)
        if cached is None or now - cached[0] >= timedelta(seconds=rt.settings.status_cache_seconds):
            cached = (now, _check(request, now))
            request.app.state.status_cache = cached
    body = cached[1]
    return JSONResponse(
        body,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": f"public, max-age={rt.settings.status_cache_seconds}",
        },
    )
