"""D-45: a requester signs the NDA on our own page, through the one-time link in the confirmation email."""

from __future__ import annotations

import base64
import re
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from conftest import make_settings
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.dashboard import access, nda
from detent.dashboard.access import OPERATOR_ORG, Member
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_dashboard_access import PASSWORD, _email, audit_kinds, sign_in, token_of

pytestmark = pytest.mark.db

SETTINGS = make_settings(
    "org_detent", sales_inbox="sales@dekern.example.test", dashboard_url="https://dash.example.test"
)
FINAL = nda.Nda("test-v1", "A final NDA text with every blank filled in.")
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 400).decode()
FORM = {"name": "Ada Example", "company": "Fictional Payouts Ltd", "role": "Head of payments"}


@pytest.fixture
def web(engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    with TestClient(create_app(SETTINGS, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


@pytest.fixture
def final(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nda, "current", lambda: FINAL)


def _request(web: TestClient, engine: Engine) -> tuple[str, str | None]:
    email = f"nda-{uuid.uuid4().hex[:8]}@fictional-payouts.example.test"
    assert web.post("/access-requests", data={**FORM, "email": email}).status_code == 200
    with engine.connect() as conn:
        body = conn.execute(
            text(
                "SELECT body FROM outbox WHERE org_id=:o AND recipient=:e AND template='access_request.received'"
            ),
            {"o": OPERATOR_ORG, "e": email},
        ).scalar_one()
    m = re.search(r"https://dash\.example\.test(/nda/[A-Za-z0-9_-]+)", body)
    return email, m.group(1) if m else None


def _sign(web: TestClient, path: str, **over: str) -> Any:
    csrf = over.pop("csrf", "") or token_of(web, path)
    data = {"name": "Ada Example", "title": "CFO", "company": "Fictional Payouts Ltd", "signature": PNG,
            "agree": "yes", "csrf": csrf, **over}  # fmt: skip
    return web.post(path, data=data, headers={"user-agent": "pytest-browser"})


def test_a_draft_with_placeholders_is_not_open_for_signing(
    web: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The shipped text is final; a text with any [placeholder] sends no link and opens no page.
    assert nda.current().ready
    _email_addr, live = _request(web, engine)
    assert live is not None
    monkeypatch.setattr(nda, "current", lambda: nda.Nda("draft", "Between [company name] and DekernAI."))
    _email_addr, path = _request(web, engine)
    assert path is None
    assert web.get(live).status_code == 404


def test_signing_stores_one_record_and_emails_both_copies(
    web: TestClient, engine: Engine, final: None
) -> None:
    email, path = _request(web, engine)
    assert path is not None
    form = web.get(path)
    assert form.status_code == 200 and FINAL.text in form.text and "Head of payments" in form.text
    assert form.headers["cache-control"] == "no-store"
    r = _sign(web, path)
    assert r.status_code == 200 and "Thank you" in r.text
    with engine.connect() as conn:
        (row,) = conn.execute(
            text(
                "SELECT s.* FROM nda_signatures s JOIN leads l ON l.id = s.lead_id "
                "WHERE l.org_id=:o AND l.email=:e"
            ),
            {"o": OPERATOR_ORG, "e": email},
        ).all()
        mails: dict[str, str] = dict(
            conn.execute(
                text("SELECT template, recipient FROM outbox WHERE org_id=:o AND body LIKE :b"),
                {"o": OPERATOR_ORG, "b": f"%{email}%"},
            ).all()
        )
    assert (row.nda_version, row.nda_sha256, row.signer_title, row.signer_email) == (
        "test-v1", FINAL.sha256, "CFO", email
    )  # fmt: skip
    assert row.ip and row.user_agent == "pytest-browser" and bytes(row.signature_png).startswith(b"\x89PNG")
    assert mails["nda.signed_copy"] == email and mails["nda.signed_notice"] == "sales@dekern.example.test"
    assert "lead.nda_signed" in audit_kinds(engine, OPERATOR_ORG)
    # A second signature is refused; the page now says it is signed.
    again = _sign(web, path, name="Someone Else", csrf=token_of(web, "/dashboard/login"))
    assert again.status_code == 409
    assert "NDA already signed" in again.text and "NDA already signed" in web.get(path).text
    # The record can't be changed or deleted.
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            text("UPDATE nda_signatures SET signer_name='x' WHERE org_id=:o AND lead_id=:l"),
            {"o": OPERATOR_ORG, "l": row.lead_id},
        )
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            text("DELETE FROM nda_signatures WHERE org_id=:o AND lead_id=:l"),
            {"o": OPERATOR_ORG, "l": row.lead_id},
        )


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"agree": ""}, "Tick the box"),
        ({"title": "  "}, "job title"),
        ({"signature": ""}, "Draw your signature"),
        ({"signature": "data:image/png;base64,bm90IGEgcG5n"}, "Draw your signature"),  # not a PNG
        ({"signature": "data:image/svg+xml;base64,PHN2Zz4="}, "Draw your signature"),
        ({"signature": "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()}, "Draw"),
    ],
)
def test_a_signature_without_every_part_is_refused(
    web: TestClient, engine: Engine, final: None, over: dict[str, str], message: str
) -> None:
    _email_addr, path = _request(web, engine)
    assert path is not None
    r = _sign(web, path, **over)
    assert r.status_code == 422 and message in r.text


def test_a_wrong_link_or_a_missing_csrf_token_signs_nothing(
    web: TestClient, engine: Engine, final: None
) -> None:
    assert web.get("/nda/not-a-real-token").status_code == 404
    _email_addr, path = _request(web, engine)
    assert path is not None
    web.get(path)
    r = web.post(path, data={"name": "A", "title": "B", "company": "C", "signature": PNG, "agree": "yes"})
    assert r.status_code == 400


def test_admins_see_nda_signed_and_the_record(
    web: TestClient, engine: Engine, clock: FrozenClock, final: None
) -> None:
    email, path = _request(web, engine)
    assert path is not None
    _sign(web, path)
    with engine.begin() as conn:
        staff: Member = access.create_staff(
            conn, clock, email=_email("ndastaff"), display_name="Staff", password=PASSWORD
        )
        lead_id = conn.execute(
            text("SELECT id FROM leads WHERE org_id=:o AND email=:e"), {"o": OPERATOR_ORG, "e": email}
        ).scalar_one()
    assert sign_in(web, staff.email).status_code == 303
    inbox = web.get("/admin/access-requests").text
    assert f"/admin/access-requests/{lead_id}/nda" in inbox and "NDA signed" in inbox
    record = web.get(f"/admin/access-requests/{lead_id}/nda")
    assert record.status_code == 200 and FINAL.sha256 in record.text and "CFO" in record.text
    png = web.get(f"/admin/access-requests/{lead_id}/nda.png")
    assert png.headers["content-type"] == "image/png" and png.content.startswith(b"\x89PNG")
