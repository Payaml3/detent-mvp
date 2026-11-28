"""Console Audit screen (AUD-01 status, AUD-03 evidence export): the hash-chain check, recent events, and an
evidence pack for one payment or a date range as JSON, HTML or PDF."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import text

from detent.audit import evidence
from detent.audit.log import verify_chain
from detent.console.auth import ActingUser, acting_user, runtime
from detent.console.routes import page, templates
from detent.runtime import Runtime
from detent.shadow import pdf

router = APIRouter(prefix="/console")


@router.get("/audit", response_class=HTMLResponse)
def audit_page(
    request: Request,
    kind: str = "",
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    with rt.engine.connect() as conn:
        chain = verify_chain(conn, user.org_id)
        events = conn.execute(
            text(
                "SELECT seq, at, actor, actor_role, kind, subject_id FROM audit_events WHERE org_id=:o "
                "AND (:k = '' OR kind LIKE :k || '%') ORDER BY seq DESC LIMIT 100"
            ),
            {"o": user.org_id, "k": kind[:60]},
        ).all()
    today = rt.clock.now().date()
    return page(
        request, rt, "audit.html", user, chain=chain, events=events, kind=kind,
        default_from=(today - timedelta(days=7)).isoformat(), default_to=today.isoformat(),
        error=request.query_params.get("error"),
    )  # fmt: skip


def _pack(rt: Runtime, user: ActingUser, payment_id: str, start: str, end: str) -> dict[str, Any]:
    s = e = None
    try:
        if not payment_id:
            s = datetime.combine(date.fromisoformat(start), datetime.min.time(), UTC)
            e = datetime.combine(date.fromisoformat(end), datetime.min.time(), UTC) + timedelta(days=1)
    except ValueError:
        raise HTTPException(status_code=422, detail="dates are YYYY-MM-DD") from None
    with rt.engine.connect() as conn:
        try:
            return evidence.build(
                conn, user.org_id, now=rt.clock.now(), payment_id=payment_id or None, start=s, end=e
            )
        except evidence.EvidenceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None


def _name(pack: dict[str, Any], ext: str) -> str:
    sc = pack["scope"]
    tag = sc["payment_id"] or f"{str(sc['from'])[:10]}_{str(sc['to'])[:10]}"
    return f'attachment; filename="evidence-{tag}.{ext}"'


@router.get("/audit/evidence.json")
def evidence_json(
    payment_id: str = "",
    start: str = "",
    end: str = "",
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> Response:
    pack = _pack(rt, user, payment_id, start, end)
    return Response(
        json.dumps(pack, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": _name(pack, "json")},
    )


@router.get("/audit/evidence.html", response_class=HTMLResponse)
def evidence_html(
    request: Request,
    payment_id: str = "",
    start: str = "",
    end: str = "",
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> HTMLResponse:
    pack = _pack(rt, user, payment_id, start, end)
    resp = templates.TemplateResponse(
        request, "evidence_file.html", {"pack": pack, "brand": rt.settings.brand_name}
    )
    resp.headers["Content-Disposition"] = _name(pack, "html")
    return resp


@router.get("/audit/evidence.pdf")
def evidence_pdf(
    payment_id: str = "",
    start: str = "",
    end: str = "",
    rt: Runtime = Depends(runtime),  # noqa: B008
    user: ActingUser = Depends(acting_user),  # noqa: B008
) -> Response:
    pack = _pack(rt, user, payment_id, start, end)
    body = pdf.render(evidence.as_lines(pack), title="Evidence pack")
    return Response(body, media_type="application/pdf", headers={"Content-Disposition": _name(pack, "pdf")})
