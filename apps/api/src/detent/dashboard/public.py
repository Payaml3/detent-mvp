"""DSH-10: the website's access form posts here. Public: no session, no CSRF token (the site is another
origin and holds no session), so it does nothing but store a lead and email the sales inbox."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from detent.dashboard import leads
from detent.dashboard.access import AccessError
from detent.dashboard.web import page, runtime
from detent.db.engine import transaction
from detent.runtime import Runtime

router = APIRouter(include_in_schema=False)


@router.post("/access-requests", response_class=HTMLResponse)
def access_request(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    company: str = Form(""),
    role: str = Form(""),
    use_case: str = Form(""),
    website: str = Form(""),
    title: str = Form(""),
    message: str = Form(""),
    country: str = Form(""),
    platform: str = Form(""),
    rails: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
) -> HTMLResponse:
    # The website's form (WEB-06) names two fields differently and asks three more questions; they are kept
    # with the use case. Required: name, work email and company.
    extra = [f"{k}: {' '.join(v.split())[:120]}" for k, v in
             (("Country", country), ("Platform", platform), ("Rails", rails)) if v.strip()]  # fmt: skip
    case = "\n".join([p for p in (use_case or message).strip().splitlines()] + extra)
    req = leads.AccessRequest(name, email, company, role or title, case, website)
    try:
        with transaction(rt.engine) as conn:
            leads.submit(conn, rt.clock, rt.settings, req)
    except AccessError as exc:
        return page(request, rt, "access_thanks.html", None, error=str(exc), status_code=exc.status)
    return page(request, rt, "access_thanks.html", None, error=None)
