"""The FastAPI application: /v1 API (from M1), console, /healthz.

``create_app`` validates settings first, so a mainnet chain ID stops the app before it serves
anything (FND-02).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine, text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from detent import logging as dlog
from detent.api import v1
from detent.api import webhooks as v1_webhooks
from detent.api.auth import AuthError
from detent.api.error_codes import HTTP_STATUS_CODES
from detent.api.errors import error_response
from detent.api.limits import RateLimiter
from detent.api.middleware import request_context
from detent.clock import Clock
from detent.console import routes as console_routes
from detent.console.auth import ActingUserRequired, LoginRequired
from detent.dashboard import mount as dashboard
from detent.intents.service import IdempotencyConflict, RequestProblem
from detent.logging import request_id_var
from detent.policy.screening import MockScreening
from detent.runtime import build_runtime
from detent.sandbox.usage import QuotaExceeded
from detent.settings import Settings, get_settings

log = logging.getLogger("detent.api")

STATIC_DIR = Path(__file__).resolve().parent.parent / "console" / "static"


def _quota(request: Request, exc: QuotaExceeded) -> Response:
    """SBX-02: over a daily sandbox quota. Retry-After runs to the next UTC day."""
    resp = error_response(429, "quota", "quota_exceeded", str(exc), request_id=request_id_var.get())
    resp.headers["Retry-After"] = str(exc.retry_after)
    return resp


def _conflict(request: Request, exc: IdempotencyConflict) -> Response:
    return error_response(
        409,
        "conflict",
        "idempotency_conflict",
        "This Idempotency-Key was already used with a different request body.",
        request_id=request_id_var.get(),
        param="Idempotency-Key",
    )


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
    app.state.limiter = RateLimiter(limit=max(1, rt.settings.api_rate_limit_per_minute))

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
    app.include_router(v1.router)
    app.include_router(v1_webhooks.router)
    dashboard.install(app)
    app.state.screening = MockScreening.from_fixture()

    def _err(status: int, type_: str, code: str, message: str, param: str | None = None) -> Response:
        return error_response(status, type_, code, message, request_id=request_id_var.get(), param=param)  # type: ignore[arg-type]

    @app.exception_handler(AuthError)
    def _auth(request: Request, exc: AuthError) -> Response:
        return _err(exc.status, exc.type, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    def _invalid(request: Request, exc: RequestValidationError) -> Response:
        errs = exc.errors()
        first = errs[0] if errs else {"loc": (), "msg": "invalid request"}
        loc = [str(p) for p in first.get("loc", ()) if p not in ("body",)]
        msg = "; ".join(
            f"{'.'.join(str(p) for p in e.get('loc', ()) if p != 'body')}: {e.get('msg')}" for e in errs
        )
        return _err(
            422, "invalid_request", "validation_error", msg or "invalid request", ".".join(loc) or None
        )

    @app.exception_handler(StarletteHTTPException)
    def _http(request: Request, exc: StarletteHTTPException) -> Response:
        type_, code = HTTP_STATUS_CODES.get(
            exc.status_code,
            ("invalid_request", "bad_request") if exc.status_code < 500 else ("internal", "internal_error"),
        )
        resp = _err(exc.status_code, type_, code, str(exc.detail))
        if exc.headers:
            resp.headers.update(exc.headers)
        return resp

    @app.exception_handler(RequestProblem)
    def _problem(request: Request, exc: RequestProblem) -> Response:
        return _err(exc.status, "invalid_request", exc.code, exc.message, exc.param)

    app.add_exception_handler(QuotaExceeded, _quota)  # type: ignore[arg-type]
    app.add_exception_handler(IdempotencyConflict, _conflict)  # type: ignore[arg-type]

    @app.exception_handler(v1.MissingIdempotencyKey)
    def _no_key(request: Request, exc: v1.MissingIdempotencyKey) -> Response:
        return _err(
            422,
            "invalid_request",
            "validation_error",
            "The Idempotency-Key header is required.",
            "Idempotency-Key",
        )

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
        """FND-07: the database and both chain RPCs, each reported. A chain RPC that is not configured is
        reported as such; it fails the check only in demo mode, where the demo needs both testnets."""
        from detent.chainguard import rpc_health

        checks: dict[str, str] = {}
        try:
            with rt.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # report, never raise, from a health check
            log.warning("healthz database check failed", extra={"error": type(exc).__name__})
            checks["database"] = "error"
        checks.update(rpc_health(settings))
        required_ok = {"ok"} if settings.is_demo else {"ok", "not_configured"}
        ok = checks["database"] == "ok" and all(
            v in required_ok for k, v in checks.items() if k != "database"
        )
        return JSONResponse(
            {
                "status": "ok" if ok else "degraded",
                "checks": checks,
                "env": settings.app_env,
                "regions": {"hosting": settings.hosting_region, "database": settings.database_region},
            },
            status_code=200 if ok else 503,
        )

    return app
