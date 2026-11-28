"""D-45: the requester signs the NDA on our own page.

The access confirmation email carries a one-time link (`/nda/<token>`); only the token's SHA-256 is kept on
the lead. The page shows the NDA text, and the requester types their name, job title and company, draws a
signature and ticks "I agree". The signature is stored once per lead, append-only, with the NDA version, the
SHA-256 of the exact text shown, the time, the IP address and the browser's user agent. A copy goes to the
requester's address and a notice to the sales inbox.

The switch: the page and the link stay off while the NDA text still has a "[placeholder]" in square brackets,
so nobody can sign an unfinished draft. Going live means replacing the text file with the version the lawyer
approved (and a new `VERSION` when the text changes); no setting is needed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import secrets
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.dashboard.access import OPERATOR_ORG, AccessError
from detent.dashboard.email import send_email
from detent.settings import Settings

VERSION = "mutual-v1"
_TEXT_DIR = Path(__file__).parent / "nda"
_PLACEHOLDER = re.compile(r"\[[^\]]+\]")
_DATA_URL = "data:image/png;base64,"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MIN_PNG, MAX_PNG = 100, 200_000
_SIGNER = Actor.system("nda-page")


@dataclass(frozen=True, slots=True)
class Nda:
    version: str
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()

    @property
    def ready(self) -> bool:
        """Off while any [placeholder] is left: fail closed on an unfinished draft."""
        return not _PLACEHOLDER.search(self.text)


@cache
def _load(version: str) -> str:
    return (_TEXT_DIR / f"{version}.txt").read_text(encoding="utf-8")


def current() -> Nda:
    return Nda(VERSION, _load(VERSION))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_link(conn: Connection, settings: Settings, lead_id: str) -> str | None:
    """A one-time signing link for a new lead, or None while the NDA is not ready."""
    if not current().ready:
        return None
    token = secrets.token_urlsafe(32)
    conn.execute(
        text("UPDATE leads SET nda_token_hash=:h WHERE org_id=:o AND id=:i"),
        {"h": _hash(token), "o": OPERATOR_ORG, "i": lead_id},
    )
    return f"{settings.dashboard_url.rstrip('/')}/nda/{token}"


_LOOKUP = (
    "SELECT l.id, l.email, l.name, l.company, l.role, s.signed_at FROM leads l "
    "LEFT JOIN nda_signatures s ON s.lead_id = l.id WHERE l.org_id=:o AND l.nda_token_hash=:h"
)
_LOOKUP_LOCKED = _LOOKUP + " FOR UPDATE OF l"


def lookup(conn: Connection, token: str, *, lock: bool = False) -> Any | None:
    """The lead a signing link belongs to, with its signature time if it was signed already."""
    if not token or len(token) > 100:
        return None
    return conn.execute(
        text(_LOOKUP_LOCKED if lock else _LOOKUP), {"o": OPERATOR_ORG, "h": _hash(token)}
    ).one_or_none()


@dataclass(frozen=True, slots=True)
class Signing:
    name: str
    title: str
    company: str
    signature: str  # a data:image/png;base64 URL from the page's drawing pad
    agree: bool
    ip: str
    user_agent: str


def _one_line(v: str, n: int) -> str:
    return " ".join(v.split())[:n]


def _png(data_url: str) -> bytes:
    if not data_url.startswith(_DATA_URL) or len(data_url) > MAX_PNG * 2:
        raise AccessError("validation_error", "Draw your signature in the box.")
    try:
        png = base64.b64decode(data_url[len(_DATA_URL) :], validate=True)
    except (binascii.Error, ValueError):
        raise AccessError("validation_error", "Draw your signature in the box.") from None
    if not png.startswith(_PNG_MAGIC) or not MIN_PNG <= len(png) <= MAX_PNG:
        raise AccessError("validation_error", "Draw your signature in the box.")
    return png


def sign(conn: Connection, clock: Clock, settings: Settings, token: str, s: Signing) -> str:
    """Store the signature once and email the copies. Returns the lead ID."""
    nda = current()
    if not nda.ready:
        raise AccessError("not_found", "This NDA is not open for signing yet.", status=404)
    lead = lookup(conn, token, lock=True)
    if lead is None:
        raise AccessError("not_found", "This signing link is not valid.", status=404)
    if lead.signed_at is not None:
        raise AccessError("conflict", "This NDA has already been signed.", status=409)
    name, title, company = _one_line(s.name, 120), _one_line(s.title, 120), _one_line(s.company, 160)
    missing = [f for f, v in (("name", name), ("job title", title), ("company", company)) if not v]
    if missing:
        raise AccessError("validation_error", "Fill in every field: " + ", ".join(missing) + ".")
    if not s.agree:
        raise AccessError("validation_error", "Tick the box to confirm that you agree.")
    png = _png(s.signature)
    now = clock.now()
    conn.execute(
        text(
            "INSERT INTO nda_signatures (lead_id, org_id, nda_version, nda_sha256, signer_name, "
            "signer_title, signer_company, signer_email, signature_png, ip, user_agent, signed_at) "
            "VALUES (:l, :o, :v, :h, :n, :t, :c, :e, :png, :ip, :ua, :now)"
        ),
        {
            "l": lead.id, "o": OPERATOR_ORG, "v": nda.version, "h": nda.sha256, "n": name, "t": title,
            "c": company, "e": lead.email, "png": png, "ip": s.ip[:64], "ua": s.user_agent[:300], "now": now,
        },
    )  # fmt: skip
    record = (
        f"Signed by: {name}, {title}, {company}\n"
        f"Email: {lead.email}\n"
        f"Signed at: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"NDA version: {nda.version} (SHA-256 {nda.sha256})\n"
        f"IP address: {s.ip[:64]}\n"
    )
    # The copy goes only to the address the link was sent to, so the page can't send email anywhere else.
    send_email(
        conn,
        clock,
        org_id=OPERATOR_ORG,
        to=lead.email,
        template="nda.signed_copy",
        settings=settings,
        body=(
            f"Thank you for signing the {settings.brand_name} NDA. Your copy is below; please keep it.\n\n"
            f"{record}\n{'-' * 60}\n\n{nda.text}"
        ),
    )
    if settings.sales_inbox:
        send_email(
            conn,
            clock,
            org_id=OPERATOR_ORG,
            to=settings.sales_inbox,
            template="nda.signed_notice",
            settings=settings,
            body=(
                "An access requester signed the NDA (the name, title and company were typed on a public "
                f"page).\n\n{record}Lead: {lead.id}. The signature is in the admin inbox."
            ),
        )
    append(
        conn,
        clock,
        org_id=OPERATOR_ORG,
        actor=_SIGNER,
        kind="lead.nda_signed",
        subject_id=lead.id,
        payload={"nda_version": nda.version, "nda_sha256": nda.sha256},
    )
    return str(lead.id)


def signature(conn: Connection, lead_id: str) -> Any | None:
    """The stored record for the admin view."""
    return conn.execute(
        text(
            "SELECT lead_id, nda_version, nda_sha256, signer_name, signer_title, signer_company, "
            "signer_email, signature_png, ip, user_agent, signed_at FROM nda_signatures "
            "WHERE org_id=:o AND lead_id=:l"
        ),
        {"o": OPERATOR_ORG, "l": lead_id},
    ).one_or_none()
