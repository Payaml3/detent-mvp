"""The whole client onboarding journey, one fictional client end to end, through HTTP only (founder ask,
2026-11-28). Each step has its own detailed tests; this one checks the steps join up in the order the website
promises: access form, NDA, admin inbox, organisation, owner invite, dashboard sections, verification."""

from __future__ import annotations

import re
import uuid

import pytest
from conftest import make_settings
from cryptography.fernet import Fernet
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.dashboard import access, nda, verification
from detent.dashboard.access import OPERATOR_ORG
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from test_dashboard_access import PASSWORD, _email, accept, post, sign_in, token_of
from test_dashboard_developer import form
from test_leads_verification import _evidence_by_api, _evidence_by_hand
from test_nda_signing import FINAL, PNG
from test_sandbox_rails import PEPPER

pytestmark = pytest.mark.db

SETTINGS = make_settings(
    "org_detent",
    api_key_pepper=SecretStr(PEPPER),
    credentials_encryption_key=SecretStr(Fernet.generate_key().decode()),
    sales_inbox="sales@dekern.example.test",
    dashboard_url="https://dash.example.test",
)


def _mail(engine: Engine, org_id: str, to: str, template: str) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                text(
                    "SELECT body FROM outbox WHERE org_id=:o AND recipient=:e AND template=:t "
                    "ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"o": org_id, "e": to, "t": template},
            ).scalar_one()
        )


def test_a_fictional_client_goes_from_the_access_form_to_a_verified_sandbox(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nda, "current", lambda: FINAL)
    app = create_app(SETTINGS, engine=engine, clock=clock, configure_logging=False)
    client, admin = TestClient(app), TestClient(app)
    email = f"robin-{uuid.uuid4().hex[:8]}@quillfern-test.example.test"

    # 1. Discovery: the website's form, with its own field names.
    site_form = {"name": "Robin Testwell", "email": email, "title": "Head of Payments",
            "company": "Quillfern Test Payouts Ltd", "country": "United Kingdom",
            "platform": "Payout platform", "rails": "Both", "message": "Two approvers today."}  # fmt: skip
    r = client.post("/access-requests", data=site_form)
    assert r.status_code == 200 and "Thank you" in r.text
    assert "Robin Testwell" in _mail(engine, OPERATOR_ORG, "sales@dekern.example.test", "access_request")
    m = re.search(r"https://dash\.example\.test(/nda/[A-Za-z0-9_-]+)", _mail(engine, OPERATOR_ORG, email,
                  "access_request.received"))  # fmt: skip
    assert m, "the confirmation email carries the NDA link"

    # 2. Contract: the NDA, signed once, with a copy to the requester and a notice to sales.
    nda_path = m.group(1)
    page = client.get(nda_path)
    assert page.status_code == 200 and 'id="nda-pad-error" role="alert" hidden' in page.text
    # The pad's "Draw your signature" error stays hidden until a submit without a drawing: p.error sets display,
    # so the stylesheet must let the hidden attribute win (it showed on the live page, 2026-11-28).
    assert "[hidden] { display: none !important; }" in client.get("/static/console.css").text
    data = {"name": "Robin Testwell", "title": "Head of Payments", "company": "Quillfern Test Payouts Ltd",
            "signature": PNG, "agree": "yes", "csrf": token_of(client, nda_path)}  # fmt: skip
    assert client.post(nda_path, data=data).status_code == 200
    assert "already signed" in client.get(nda_path).text
    assert "Quillfern" in _mail(engine, OPERATOR_ORG, email, "nda.signed_copy")
    _mail(engine, OPERATOR_ORG, "sales@dekern.example.test", "nda.signed_notice")

    # 3. The admin sees the request with "NDA signed", then (after the call and KYB) creates the evaluation org.
    with engine.begin() as conn:
        staff = access.create_staff(
            conn, clock, email=_email("staff"), display_name="Staff", password=PASSWORD
        )
        lead_id = conn.execute(
            text("SELECT id FROM leads WHERE org_id=:o AND email=:e"), {"o": OPERATOR_ORG, "e": email}
        ).scalar_one()
    assert sign_in(admin, staff.email).headers["location"] == "/admin/"
    inbox = admin.get("/admin/access-requests").text
    assert lead_id in inbox and "NDA signed" in inbox
    assert admin.get(f"/admin/access-requests/{lead_id}/nda").status_code == 200
    r = post(admin, "/admin/organisations",
             {"kind": "evaluation", "name": "Quillfern Test Payouts Ltd", "owner_email": email},
             page="/admin/organisations/new")  # fmt: skip
    assert r.status_code == 303, r.text
    org_id = r.headers["location"].rsplit("/", 1)[1]
    with engine.connect() as conn:
        org = access.load_org(conn, org_id)
    assert org.kind == "evaluation" and (org.expires_at - clock.now()).days == 60

    # 4. Sandbox: the owner's single-use invite, then every dashboard section.
    invite = re.search(
        r"/dashboard/invite/([A-Za-z0-9_-]+)", _mail(engine, org_id, email, "invite.account_owner")
    )
    assert invite
    assert accept(client, invite.group(1), name="Robin Testwell").status_code == 303
    assert sign_in(client, email).status_code == 303
    for section in ("/dashboard/", "/dashboard/team", "/dashboard/keys", "/dashboard/webhooks",
                    "/dashboard/sandbox", "/dashboard/logs", "/dashboard/usage", "/dashboard/verification"):  # fmt: skip
        assert client.get(section).status_code == 200, section
    r = form(client, "/dashboard/keys", {"name": "Quillfern backend", "scopes": ["read", "intents:create"]},
             "/dashboard/keys")  # fmt: skip
    assert r.status_code == 201 and "sk_test_" in r.text, r.text
    r = form(client, "/dashboard/webhooks", {"url": "https://hooks.quillfern-test.example.test/dekern",
             "event_types": ["exception.created"]}, "/dashboard/webhooks")  # fmt: skip
    assert r.status_code == 201 and "whsec_" in r.text, r.text
    r = post(
        client,
        "/dashboard/team/invite",
        {"email": _email("dev"), "role": "developer"},
        page="/dashboard/team",
    )
    assert r.status_code == 303, r.text
    ai = client.get("/dashboard/ai-team", follow_redirects=True)
    assert ai.status_code == 200 and "They propose" in ai.text, ai.url

    # 5. Policy setup and go-live readiness: sandbox evidence, then the owner asks and an admin verifies.
    with engine.connect() as conn:
        user_id = conn.execute(
            text("SELECT id FROM users WHERE org_id=:o AND lower(email)=:e"), {"o": org_id, "e": email}
        ).scalar_one()
        owner = access.load_member(conn, org_id, user_id)
    assert owner is not None
    # The owner invites a payments lead and a compliance lead; the two of them move the sandbox from shadow
    # to auto in the console (EXE-09), as the shadow-to-auto guide shows. One person can't do both.
    leads = {}
    for role in ("payments_lead", "compliance_lead"):
        addr = _email(role.replace("_", ""))
        assert post(client, "/dashboard/team/invite", {"email": addr, "role": role},
                    page="/dashboard/team").status_code == 303  # fmt: skip
        token = re.search(r"/dashboard/invite/([A-Za-z0-9_-]+)", _mail(engine, org_id, addr, "invite.member"))
        assert token
        c = TestClient(app)
        assert accept(c, token.group(1), name=role.replace("_", " ").title()).status_code == 303
        assert sign_in(c, addr).status_code == 303
        leads[role] = c
    same = {"Origin": "http://testserver"}
    assert leads["payments_lead"].get("/console/settings").status_code == 200
    leads["payments_lead"].post("/console/settings/mode/propose",
                                data={"to_mode": "auto", "reason": "Sandbox rules reviewed"}, headers=same)  # fmt: skip
    with engine.connect() as conn:
        change = conn.execute(
            text("SELECT id FROM mode_changes WHERE org_id=:o AND status='proposed'"), {"o": org_id}
        ).scalar_one()
    leads["compliance_lead"].post(f"/console/settings/mode/{change}/approve", headers=same)
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT mode FROM organisations WHERE org_id=:o"), {"o": org_id}).scalar_one()
            == "auto"
        )

    _evidence_by_api(client, engine, clock, owner)
    _evidence_by_hand(engine, clock, org_id)
    r = post(client, "/dashboard/verification/request", {}, page="/dashboard/verification")
    with engine.connect() as conn:
        todo = [i.label for i in verification.checklist(conn, org_id) if not i.done]
    assert r.status_code == 303, todo
    with engine.connect() as conn:
        req = verification.latest(conn, org_id)
    assert req.id in admin.get("/admin/verifications").text
    r = post(
        admin, f"/admin/verifications/{org_id}/{req.id}", {"outcome": "verified"}, page="/admin/verifications"
    )
    assert r.status_code == 303
    with engine.connect() as conn:
        assert verification.latest(conn, org_id).status == "verified"
