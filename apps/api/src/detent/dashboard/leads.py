"""DSH-10: website access requests, stored as leads of the operator organisation and emailed to sales.

The form is public, so everything in it is untrusted text: lengths are capped, it is shown escaped, it never
goes to a model, and nothing in it is followed. A form with the hidden `website` field filled in is treated as
a bot: it gets the same thank-you and nothing is stored. The same work email within a day is not stored twice.

"Emailed" means the notice went to the outbox (G-02), like every other dashboard email; with
`EMAIL_PROVIDER=zeptomail` the worker then sends it (`dashboard/email.py`). With no `SALES_INBOX` set, the
lead is stored and the admin inbox says nothing was sent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.dashboard import nda
from detent.dashboard.access import OPERATOR_ORG, AccessError, Member, _require_staff, ensure_operator_org
from detent.dashboard.email import send_email
from detent.domain.ids import Prefix, new_id
from detent.settings import Settings

STATUSES = ("new", "contacted", "approved", "declined")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
_PUBLIC = Actor.system("website-form")


@dataclass(frozen=True, slots=True)
class AccessRequest:
    name: str
    email: str
    company: str
    role: str
    use_case: str
    website: str = ""  # the honeypot: people never see it, bots fill it in

    def cleaned(self) -> AccessRequest:
        def one_line(v: str, n: int) -> str:
            return " ".join(v.split())[:n]

        return AccessRequest(
            name=one_line(self.name, 120),
            email=self.email.strip().lower()[:254],
            company=one_line(self.company, 160),
            role=one_line(self.role, 120),
            use_case=self.use_case.strip()[:2000],
            website=self.website.strip(),
        )


def confirmation_body(settings: Settings, nda_link: str | None = None) -> str:
    """The fixed reply to the person who sent the form: what happens next (founder, 2026-11-28). The NDA
    link is their own one-time signing page (D-45), included once the NDA text is final."""
    brand = settings.brand_name
    reply_from = settings.sales_inbox or "our team"
    step1 = (
        f"1. A short NDA to sign. You can sign it now: {nda_link}\n"
        if nda_link
        else "1. A short NDA to sign.\n"
    )
    return (
        f"Thank you for your interest in {brand}.\n\n"
        f"We've received your access request. We'll reply from {reply_from} with the next steps:\n"
        f"{step1}"
        "2. A commercial call about your platform, your deposits and your payouts.\n"
        f"3. If {brand} is a fit, access to the sandbox and your client dashboard.\n\n"
        f"{brand}: agentic payment controls.\n"
        f"You're receiving this because this address was entered on the {brand} website's access form. "
        "If that wasn't you, you can ignore this email."
    )


def submit(conn: Connection, clock: Clock, settings: Settings, req: AccessRequest) -> str | None:
    """Store the request and email the sales inbox. Returns the lead ID, or None when nothing was stored
    (a bot, or a repeat within a day)."""
    r = req.cleaned()
    if r.website:
        return None
    missing = [f for f in ("name", "email", "company") if not getattr(r, f)]
    if missing:
        raise AccessError(
            "validation_error", "Fill in every field: " + ", ".join(missing).replace("_", " ") + "."
        )
    if not _EMAIL.match(r.email):
        raise AccessError("validation_error", "Give a work email address.")
    now = clock.now()
    seen = conn.execute(
        text(
            "SELECT id FROM leads WHERE org_id=:o AND lower(email)=:e AND created_at > :since "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"o": OPERATOR_ORG, "e": r.email, "since": now - timedelta(days=1)},
    ).scalar_one_or_none()
    if seen is not None:
        return None
    ensure_operator_org(conn, clock)
    lead_id = new_id(Prefix.LED, now)
    outbox_id = None
    if settings.sales_inbox:
        outbox_id = send_email(
            conn,
            clock,
            org_id=OPERATOR_ORG,
            to=settings.sales_inbox,
            template="access_request",
            settings=settings,
            body=(
                "A new access request from the website (untrusted text from a public form).\n\n"
                f"Name: {r.name}\nWork email: {r.email}\nCompany: {r.company}\nRole: {r.role}\n"
                f"Use case:\n{r.use_case}\n\nLead: {lead_id}. Follow up from the admin inbox."
            ),
        )
    conn.execute(
        text(
            "INSERT INTO leads (id, org_id, email, company, message, name, role, use_case, outbox_id, "
            "created_at) "
            "VALUES (:id, :o, :e, :c, NULL, :n, :r, :u, :ob, :now)"
        ),
        {
            "id": lead_id,
            "o": OPERATOR_ORG,
            "e": r.email,
            "c": r.company,
            "n": r.name,
            "r": r.role,
            "u": r.use_case,
            "ob": outbox_id,
            "now": now,
        },
    )
    # The requester's confirmation. It repeats nothing they typed, so the form can't be used to send our
    # email with someone else's text in it; a repeat within a day or a bot gets none (both return above).
    send_email(
        conn,
        clock,
        org_id=OPERATOR_ORG,
        to=r.email,
        template="access_request.received",
        settings=settings,
        body=confirmation_body(settings, nda.issue_link(conn, settings, lead_id)),
    )
    append(
        conn,
        clock,
        org_id=OPERATOR_ORG,
        actor=_PUBLIC,
        kind="lead.received",
        subject_id=lead_id,
        payload={"emailed": outbox_id is not None},
    )
    return lead_id


def list_leads(conn: Connection, status: str | None = None, limit: int = 200) -> list[Any]:
    return list(
        conn.execute(
            text(
                "SELECT id, name, email, company, role, use_case, status, status_note, status_by, status_at, "
                "outbox_id, created_at, "
                "(SELECT s.signed_at FROM nda_signatures s WHERE s.lead_id = leads.id) AS nda_signed_at "
                "FROM leads WHERE org_id=:o "
                "AND (CAST(:s AS TEXT) IS NULL OR status=:s) ORDER BY created_at DESC, id DESC LIMIT :n"
            ),
            {"o": OPERATOR_ORG, "s": status if status in STATUSES else None, "n": limit},
        ).all()
    )


def set_status(
    conn: Connection, clock: Clock, *, staff: Member, lead_id: str, status: str, note: str
) -> None:
    """An admin moves a lead along (new, contacted, approved, declined). Audited."""
    _require_staff(staff)
    if status not in STATUSES:
        raise AccessError("validation_error", "Choose one of the listed statuses.")
    note = note.strip()[:500]
    old = conn.execute(
        text("SELECT status FROM leads WHERE org_id=:o AND id=:i FOR UPDATE"),
        {"o": OPERATOR_ORG, "i": lead_id},
    ).scalar_one_or_none()
    if old is None:
        raise AccessError("not_found", "No such access request.", status=404)
    conn.execute(
        text(
            "UPDATE leads SET status=:s, status_note=:n, status_by=:b, status_at=:now "
            "WHERE org_id=:o AND id=:i"
        ),
        {"s": status, "n": note or None, "b": staff.id, "now": clock.now(), "o": OPERATOR_ORG, "i": lead_id},
    )
    append(
        conn,
        clock,
        org_id=OPERATOR_ORG,
        actor=staff.actor,
        kind="lead.status_changed",
        subject_id=lead_id,
        payload={"from": old, "to": status, "note": note},
    )
