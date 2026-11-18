"""The FastAPI application: /v1 API (from M1), console, /healthz.

``create_app`` validates settings first, so a mainnet chain ID stops the app before it serves
anything (FND-02).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine, text
from starlette.middleware.sessions import SessionMiddleware

from detent import logging as dlog
from detent.api.middleware import request_context
from detent.clock import Clock
from detent.console import routes as console_routes
from detent.console.auth import ActingUserRequired, LoginRequired
from detent.runtime import build_runtime
from detent.settings import Settings, get_settings

log = logging.getLogger("detent.api")

STATIC_DIR = Path(__file__).resolve().parent.parent / "console" / "static"


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    clock: Clock | None = None,
    configure_logging: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    if configure_logging:
        dlog.configure(settings.log_level, settings.log_json, settings.secret_values())
    else:
        dlog.redactor.add(*settings.secret_values())
    rt = build_runtime(settings, engine=engine, clock=clock)

    app = FastAPI(
        title=f"{settings.brand_name} payment controls API (sandbox)",
        description="Agentic payment controls: decision, orchestration and operations. Test networks only.",
        version="0.1.0",
        docs_url=None if settings.app_env == "demo" else "/docs",
        redoc_url=None,
    )
    app.state.runtime = rt

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        session_cookie="detent_console",
        same_site="lax",
        https_only=settings.app_env in ("demo", "sandbox"),
        max_age=12 * 3600,
    )
    # Added last so it runs first: request ID and live-key rejection wrap everything.
    app.middleware("http")(request_context)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(console_routes.router)

    @app.exception_handler(LoginRequired)
    def _login(request: Request, exc: LoginRequired) -> Response:
        return RedirectResponse("/console/login", status_code=303)

    @app.exception_handler(ActingUserRequired)
    def _act_as(request: Request, exc: ActingUserRequired) -> Response:
        return RedirectResponse("/console/act-as", status_code=303)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/console/", status_code=303)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            with rt.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # report, never raise, from a health check
            log.warning("healthz database check failed", extra={"error": type(exc).__name__})
            checks["database"] = "error"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ok" if ok else "degraded", "checks": checks, "env": settings.app_env},
            status_code=200 if ok else 503,
        )

    return app
