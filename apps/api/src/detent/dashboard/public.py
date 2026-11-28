"""DSH-10: the website's access form posts here. Public: no session, no CSRF token (the site is another
origin and holds no session), so it does nothing but store a lead and email the sales inbox.

D-45: the NDA signing page, reached only through the one-time link in the confirmation email. Its form is
served by this app, so it does carry the session's CSRF token."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from detent.dashboard import leads, nda
from detent.dashboard.access import AccessError
from detent.dashboard.web import check_csrf, client_address, page, runtime
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


# ------------------------------------------------------------------------------------------ D-45 NDA
# The signing link is the only credential here, so the page sets no-referrer (base.html) and isn't cached.
_NO_STORE = {"Cache-Control": "no-store"}


def _nda_page(request: Request, rt: Runtime, token: str, **ctx: object) -> HTMLResponse:
    doc = nda.current()
    lead = None
    if doc.ready:
        with rt.engine.connect() as conn:
            lead = nda.lookup(conn, token)
    state = "unavailable" if lead is None else ("signed" if lead.signed_at is not None else "open")
    ctx.setdefault("status_code", 404 if state == "unavailable" else 200)
    resp = page(request, rt, "nda.html", None, state=state, lead=lead, doc=doc, token=token, **ctx)
    resp.headers.update(_NO_STORE)
    return resp


@router.get("/nda/{token}", response_class=HTMLResponse)
def nda_form(token: str, request: Request, rt: Runtime = Depends(runtime)) -> HTMLResponse:  # noqa: B008
    return _nda_page(request, rt, token)


@router.post("/nda/{token}", response_class=HTMLResponse, dependencies=[Depends(check_csrf)])
def nda_sign(
    token: str,
    request: Request,
    name: str = Form(""),
    title: str = Form(""),
    company: str = Form(""),
    signature: str = Form(""),
    agree: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
) -> HTMLResponse:
    signing = nda.Signing(
        name=name,
        title=title,
        company=company,
        signature=signature,
        agree=agree == "yes",
        ip=client_address(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    try:
        with transaction(rt.engine) as conn:
            nda.sign(conn, rt.clock, rt.settings, token, signing)
    except AccessError as exc:
        form = {"name": name, "title": title, "company": company}
        return _nda_page(request, rt, token, error=str(exc), form=form, status_code=exc.status)
    return _nda_page(request, rt, token, just_signed=True)
