"""DekernAI admin screens (DSH-01, DSH-03; spec/08 "Admin").

Only admins of the operator organisation reach them (`detent staff add` creates one; there is no other way).
They create a client organisation after KYB, or an evaluation organisation with an expiry, invite its account
owner, extend an evaluation, and suspend or reinstate an organisation. Every action is audited in the
organisation it changes.

An invite goes to the outbox (and, with `EMAIL_PROVIDER=zeptomail`, is emailed by the worker); the admin also
sees its link once, here, to send by hand if the email doesn't arrive.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response

from detent.dashboard import access, leads, nda, verification
from detent.dashboard.access import AccessError, Member
from detent.dashboard.web import Forbidden, check_csrf, page, redirect, runtime, staff_member
from detent.db.engine import transaction
from detent.domain.roles import Role
from detent.runtime import Runtime

router = APIRouter(prefix="/admin", dependencies=[Depends(check_csrf)], include_in_schema=False)

# The invite link is shown once, on the next view of the organisation: it rides in the admin's own signed
# session cookie (HttpOnly) until then, so it works with any number of API instances.
_LINK = "admin_invite_link"


def _show_once(request: Request, org_id: str, link: str) -> None:
    request.session[_LINK] = {"org": org_id, "link": link}


def _pop_link(request: Request, org_id: str) -> str | None:
    held = request.session.get(_LINK)
    if isinstance(held, dict) and held.get("org") == org_id:
        request.session.pop(_LINK, None)
        return str(held["link"])
    return None


@router.get("/", response_class=HTMLResponse)
def organisations(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        orgs = access.list_organisations(conn)
    now = rt.clock.now()
    rows = [{"org": o, "status": access.org_status(o, now)} for o in orgs]
    return page(request, rt, "admin_orgs.html", staff, rows=rows)


@router.get("/organisations/new", response_class=HTMLResponse)
def new_form(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
) -> HTMLResponse:
    return page(request, rt, "admin_new.html", staff, error=None, form={}, days=rt.settings.evaluation_days)


@router.post("/organisations", response_model=None)
def create(
    request: Request,
    kind: str = Form(""),
    name: str = Form(""),
    owner_email: str = Form(""),
    kyb_reference: str = Form(""),
    kyb_approved_on: str = Form(""),
    expires_in_days: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
) -> Response:
    form = {
        "kind": kind,
        "name": name,
        "owner_email": owner_email,
        "kyb_reference": kyb_reference,
        "kyb_approved_on": kyb_approved_on,
        "expires_in_days": expires_in_days,
    }
    try:
        if kind not in ("client", "evaluation"):
            raise AccessError("validation_error", "Choose a client or an evaluation organisation.")
        approved = _date(kyb_approved_on) if kind == "client" and kyb_approved_on.strip() else None
        days = int(expires_in_days) if kind == "evaluation" and expires_in_days.strip() else None
        with transaction(rt.engine) as conn:
            org_id, token = access.create_organisation(
                conn,
                rt.clock,
                rt.settings,
                staff=staff,
                kind="client" if kind == "client" else "evaluation",
                name=name,
                owner_email=owner_email,
                kyb_reference=kyb_reference,
                kyb_approved_on=approved,
                expires_in_days=days,
            )
    except (AccessError, ValueError) as exc:
        return page(
            request,
            rt,
            "admin_new.html",
            staff,
            error=str(exc),
            form=form,
            days=rt.settings.evaluation_days,
            status_code=422,
        )
    _show_once(request, org_id, access.invite_link(rt.settings, token))
    return redirect(f"/admin/organisations/{org_id}")


@router.get("/organisations/{org_id}", response_class=HTMLResponse)
def detail(
    org_id: str,
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
    error: str | None = None,
) -> HTMLResponse:
    try:
        with rt.engine.connect() as conn:
            org = access.load_org(conn, org_id)
            if org.kind not in ("client", "evaluation"):
                raise AccessError("not_found", "No such organisation.", status=404)
            members = access.list_members(conn, org_id)
            invites = access.list_invites(conn, rt.clock, org_id)
    except AccessError as exc:
        return page(request, rt, "forbidden.html", staff, message=str(exc), status_code=exc.status)
    link = _pop_link(request, org_id)
    return page(
        request,
        rt,
        "admin_org.html",
        staff,
        org=org,
        status=access.org_status(org, rt.clock.now()),
        members=members,
        invites=invites,
        link=link,
        error=error,
        status_code=422 if error else 200,
    )


def _act(request: Request, rt: Runtime, staff: Member, org_id: str, fn: Any) -> Response:
    try:
        with transaction(rt.engine) as conn:
            fn(conn)
    except (AccessError, ValueError) as exc:
        return detail(org_id, request, rt, staff, error=str(exc))
    return redirect(f"/admin/organisations/{org_id}")


@router.post("/organisations/{org_id}/extend", response_model=None)
def extend(
    org_id: str,
    request: Request,
    days: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
) -> Response:
    return _act(
        request,
        rt,
        staff,
        org_id,
        lambda conn: access.extend(conn, rt.clock, staff=staff, org_id=org_id, days=int(days or "0")),
    )


@router.post("/organisations/{org_id}/suspend", response_model=None)
def suspend(
    org_id: str,
    request: Request,
    reason: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
) -> Response:
    return _act(
        request,
        rt,
        staff,
        org_id,
        lambda conn: access.suspend(conn, rt.clock, staff=staff, org_id=org_id, reason=reason),
    )


@router.post("/organisations/{org_id}/unsuspend", response_model=None)
def unsuspend(
    org_id: str,
    request: Request,
    reason: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
) -> Response:
    return _act(
        request,
        rt,
        staff,
        org_id,
        lambda conn: access.unsuspend(conn, rt.clock, staff=staff, org_id=org_id, reason=reason),
    )


@router.post("/organisations/{org_id}/invite_owner", response_model=None)
def invite_owner(
    org_id: str,
    request: Request,
    email: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
) -> Response:
    """Send (or replace) the account owner's invite, for example after the first one expired."""
    token: list[str] = []

    def go(conn: Any) -> None:
        org = access.load_org(conn, org_id)
        if org.kind not in ("client", "evaluation"):
            raise AccessError("not_found", "No such organisation.", status=404)
        token.append(
            access.invite(
                conn, rt.clock, rt.settings, org_id=org_id, email=email, role=Role.ACCOUNT_OWNER, by=staff
            )
        )

    resp = _act(request, rt, staff, org_id, go)
    if token:
        _show_once(request, org_id, access.invite_link(rt.settings, token[0]))
    return resp


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise AccessError("validation_error", "Enter the KYB approval date as YYYY-MM-DD.") from exc


# --------------------------------------------------------------------------------- access requests (DSH-10)
@router.get("/access-requests", response_class=HTMLResponse)
def access_requests(
    request: Request,
    status: str = "",
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
    error: str | None = None,
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        rows = leads.list_leads(conn, status or None)
    return page(
        request,
        rt,
        "admin_leads.html",
        staff,
        rows=rows,
        status=status,
        statuses=leads.STATUSES,
        inbox=rt.settings.sales_inbox,
        error=error,
        status_code=422 if error else 200,
    )


@router.post("/access-requests/{lead_id}/status", response_model=None)
def access_request_status(
    lead_id: str,
    request: Request,
    status: str = Form(""),
    note: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
) -> Response:
    try:
        with transaction(rt.engine) as conn:
            leads.set_status(conn, rt.clock, staff=staff, lead_id=lead_id, status=status, note=note)
    except AccessError as exc:
        resp = access_requests(request, "", rt, staff, error=str(exc))
        resp.status_code = exc.status
        return resp
    return redirect("/admin/access-requests")


@router.get("/access-requests/{lead_id}/nda", response_class=HTMLResponse)
def access_request_nda(
    lead_id: str,
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
) -> HTMLResponse:
    """D-45: the signed NDA record, with the signature drawn on the page."""
    with rt.engine.connect() as conn:
        sig = nda.signature(conn, lead_id)
    if sig is None:
        raise Forbidden("No signed NDA for this access request.", status=404)
    return page(request, rt, "admin_nda.html", staff, sig=sig)


@router.get("/access-requests/{lead_id}/nda.png", response_model=None)
def access_request_nda_png(
    lead_id: str,
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
) -> Response:
    with rt.engine.connect() as conn:
        sig = nda.signature(conn, lead_id)
    if sig is None:
        return Response(status_code=404)
    return Response(
        bytes(sig.signature_png),
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


# ------------------------------------------------------------------------------------ verification (DSH-12)
@router.get("/verifications", response_class=HTMLResponse)
def verifications(
    request: Request,
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
    error: str | None = None,
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        rows = verification.open_requests(conn)
    return page(
        request,
        rt,
        "admin_verifications.html",
        staff,
        rows=rows,
        error=error,
        status_code=422 if error else 200,
    )


@router.post("/verifications/{org_id}/{request_id}", response_model=None)
def verification_decide(
    org_id: str,
    request_id: str,
    request: Request,
    outcome: str = Form(""),
    note: str = Form(""),
    rt: Runtime = Depends(runtime),  # noqa: B008
    staff: Member = Depends(staff_member),  # noqa: B008
) -> Response:
    try:
        with transaction(rt.engine) as conn:
            verification.decide(
                conn, rt.clock, staff=staff, org_id=org_id, request_id=request_id, outcome=outcome, note=note
            )
    except AccessError as exc:
        resp = verifications(request, rt, staff, error=str(exc))
        resp.status_code = exc.status
        return resp
    return redirect("/admin/verifications")
