"""Adds the dashboard and admin screens to the app (P2)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from detent.dashboard import admin, developer, routes
from detent.dashboard.web import Forbidden, SignInRequired, page, runtime


def install(app: FastAPI) -> None:
    app.include_router(developer.router)  # before routes: its /{section} placeholder catches the rest
    app.include_router(routes.router)
    app.include_router(admin.router)

    @app.exception_handler(SignInRequired)
    def _sign_in(request: Request, exc: SignInRequired) -> Response:
        return RedirectResponse(f"/dashboard/login?next={quote(exc.next_path)}", status_code=303)

    @app.exception_handler(Forbidden)
    def _forbidden(request: Request, exc: Forbidden) -> Response:
        return page(
            request, runtime(request), "forbidden.html", None, message=exc.message, status_code=exc.status
        )
