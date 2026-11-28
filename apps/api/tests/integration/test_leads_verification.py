"""P2 group 4a: the access-requests inbox (DSH-10) and the integration checklist with its verification
(DSH-12)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

import pytest
from conftest import make_settings
from cryptography.fernet import Fernet
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.dashboard import access, verification
from detent.dashboard.access import OPERATOR_ORG, Member
from detent.domain.ids import Prefix, new_id
from detent.domain.roles import Role
from detent.webhooks import endpoints
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from test_dashboard_access import PASSWORD, _email, audit_kinds, owner_of, post, sign_in, token_of
from test_sandbox_rails import PEPPER, drain, key_for, pay

pytestmark = pytest.mark.db

SETTINGS = make_settings(
    "org_detent", api_key_pepper=SecretStr(PEPPER), sales_inbox="sales@dekern.example.test"
)
HOOKS = make_settings("org_detent", credentials_encryption_key=SecretStr(Fernet.generate_key().decode()))
NO_INBOX = make_settings("org_detent", api_key_pepper=SecretStr(PEPPER))
FORM = {
    "name": "Ada Example",
    "email": "Ada@Fictional-Payouts.example.test",
    "company": "Fictional Payouts Ltd",
    "role": "Head of payments",
    "use_case": "Stablecoin payouts to our sellers.",
}


@pytest.fixture
def staff(engine: Engine, clock: FrozenClock) -> Member:
    with engine.begin() as conn:
        return access.create_staff(
            conn, clock, email=_email("staff"), display_name="Staff", password=PASSWORD
        )


@pytest.fixture
def owner(engine: Engine, clock: FrozenClock, staff: Member) -> Member:
    _org, member = owner_of(engine, clock, staff)
    with engine.begin() as conn:
        conn.execute(text("UPDATE organisations SET mode='auto' WHERE org_id=:o"), {"o": member.org_id})
    return member


@pytest.fixture
def web(engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    with TestClient(create_app(SETTINGS, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def _leads(engine: Engine, email: str) -> list[dict[str, object]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM leads WHERE org_id=:o AND email=:e ORDER BY created_at"),
            {"o": OPERATOR_ORG, "e": email},
        ).all()
    return [dict(r._mapping) for r in rows]


# ------------------------------------------------------------------------------------------ DSH-10
def test_the_access_form_stores_a_lead_and_emails_the_sales_inbox(
    web: TestClient, engine: Engine, clock: FrozenClock
) -> None:
    email = f"ada-{uuid.uuid4().hex[:8]}@fictional-payouts.example.test"
    r = web.post("/access-requests", data={**FORM, "email": email.upper()})  # no session, no CSRF token
    assert r.status_code == 200 and "Thank you" in r.text
    (lead,) = _leads(engine, email)
    assert (lead["name"], lead["company"], lead["role"], lead["use_case"], lead["status"]) == (
        "Ada Example", "Fictional Payouts Ltd", "Head of payments", "Stablecoin payouts to our sellers.", "new"
    )  # fmt: skip
    with engine.connect() as conn:
        mail = conn.execute(
            text("SELECT recipient, template, body FROM outbox WHERE org_id=:o AND id=:i"),
            {"o": OPERATOR_ORG, "i": lead["outbox_id"]},
        ).one()
    assert mail.recipient == "sales@dekern.example.test" and mail.template == "access_request"
    assert email in mail.body and "untrusted" in mail.body
    # The same email again within a day is not stored twice; a bot filling the hidden field is not stored.
    assert web.post("/access-requests", data={**FORM, "email": email}).status_code == 200
    bot = f"bot-{uuid.uuid4().hex[:8]}@example.test"
    assert web.post("/access-requests", data={**FORM, "email": bot, "website": "x"}).status_code == 200
    assert len(_leads(engine, email)) == 1 and _leads(engine, bot) == []
    bad = web.post("/access-requests", data={**FORM, "email": "not-an-email"})
    assert bad.status_code == 422 and "work email" in bad.text
    assert web.post("/access-requests", data={"name": "x"}).status_code == 422
    assert "lead.received" in audit_kinds(engine, OPERATOR_ORG)


def test_without_a_sales_inbox_the_lead_is_stored_and_nothing_is_sent(
    engine: Engine, clock: FrozenClock
) -> None:
    with TestClient(create_app(NO_INBOX, engine=engine, clock=clock, configure_logging=False)) as c:
        email = f"no-inbox-{uuid.uuid4().hex[:8]}@example.test"
        assert c.post("/access-requests", data={**FORM, "email": email}).status_code == 200
    (lead,) = _leads(engine, email)
    assert lead["outbox_id"] is None


def test_the_requester_gets_a_confirmation_that_repeats_nothing_they_typed(
    web: TestClient, engine: Engine
) -> None:
    email = f"conf-{uuid.uuid4().hex[:8]}@fictional-payouts.example.test"
    injected = {
        **FORM,
        "email": email,
        "name": "Click http://evil.example.test now",
        "use_case": "<b>buy</b>",
    }
    assert web.post("/access-requests", data=injected).status_code == 200
    assert web.post("/access-requests", data=injected).status_code == 200  # a repeat within a day
    with engine.connect() as conn:
        mails = conn.execute(
            text(
                "SELECT body FROM outbox WHERE org_id=:o AND recipient=:e AND template='access_request.received'"
            ),
            {"o": OPERATOR_ORG, "e": email},
        ).all()
    (mail,) = mails  # one confirmation, even after a repeat
    assert "NDA" in mail.body and "commercial call" in mail.body and "sandbox" in mail.body
    assert "sales@dekern.example.test" in mail.body
    assert "evil" not in mail.body and "<b>" not in mail.body


def test_the_confirmation_carries_the_nda_link_when_one_is_given() -> None:
    from detent.dashboard.leads import confirmation_body

    link = "https://dashboard.example.test/nda/tok"
    assert f"sign it now: {link}" in confirmation_body(NO_INBOX, link)
    assert "sign it now" not in confirmation_body(NO_INBOX) and "our team" in confirmation_body(NO_INBOX)


def test_admins_list_access_requests_and_change_their_status(
    web: TestClient, staff: Member, engine: Engine, clock: FrozenClock
) -> None:
    email = f"lin-{uuid.uuid4().hex[:8]}@example.test"
    web.post("/access-requests", data={**FORM, "email": email, "use_case": "<script>alert(1)</script>"})
    (lead,) = _leads(engine, email)
    assert sign_in(web, staff.email).status_code == 303
    page = web.get("/admin/access-requests").text
    assert email in page and "&lt;script&gt;" in page and "<script>alert" not in page
    r = post(web, f"/admin/access-requests/{lead['id']}/status", {"status": "contacted", "note": "Call booked"},
             page="/admin/access-requests")  # fmt: skip
    assert r.status_code == 303
    (lead,) = _leads(engine, email)
    assert (lead["status"], lead["status_note"], lead["status_by"]) == ("contacted", "Call booked", staff.id)
    assert "lead.status_changed" in audit_kinds(engine, OPERATOR_ORG)
    assert email not in web.get("/admin/access-requests?status=new").text
    bad = post(
        web, f"/admin/access-requests/{lead['id']}/status", {"status": "won"}, page="/admin/access-requests"
    )
    assert bad.status_code == 422


def test_client_members_cannot_see_the_inbox(web: TestClient, owner: Member) -> None:
    assert sign_in(web, owner.email).status_code == 303
    assert web.get("/admin/access-requests").status_code == 404  # the admin screens don't show they exist


# ------------------------------------------------------------------------------------------ DSH-12
def _keys(engine: Engine, org_id: str) -> dict[str, bool]:
    with engine.connect() as conn:
        return {i.key: i.done for i in verification.checklist(conn, org_id)}


def _evidence_by_api(web: TestClient, engine: Engine, clock: FrozenClock, m: Member) -> None:
    """Everything the checklist reads that a sandbox integration produces through the API."""
    auth = key_for(engine, clock, m)
    pay(web, auth, "90.13")
    pay(web, auth, "90.42", switch=False)
    pay(web, auth, "90.00", "cpt_flagged", "dst_flagged")
    body = {
        "kind": "payout", "source": "platform", "counterparty_id": "cpt_nova",
        "destination": {"kind": "evm_wallet", "network": "eth-sepolia", "destination_id": "dst_nova_eth"},
        "amount": {"amount": "90.00", "currency": "USDC"},
    }  # fmt: skip
    key = str(uuid.uuid4())
    for _ in range(2):  # the idempotent retry
        r = web.post("/v1/payment_intents", json=body, headers={**auth, "Idempotency-Key": key})
        assert r.status_code in (200, 201), r.text
    drain(engine, clock, m.org_id, seconds=20, rounds=4)


def _evidence_by_hand(engine: Engine, clock: FrozenClock, org_id: str) -> None:
    """The two items that need an agent mandate or a live endpoint: recorded the way those paths record them
    (their own tests cover the paths)."""
    with engine.begin() as conn:
        hook, _secret = endpoints.create(
            conn, clock, HOOKS, org_id=org_id, url="https://hooks.example.test/dekern", event_types=["*"]
        )
        d = conn.execute(
            text("SELECT payment_id, policy_version_id, policy_hash FROM decisions WHERE org_id=:o LIMIT 1"),
            {"o": org_id},
        ).one()
        conn.execute(
            text(
                "INSERT INTO decisions (id, org_id, payment_id, outcome, policy_version_id, policy_hash, "
                "inputs_snapshot, checks, decided_at, actor) VALUES (:id, :o, :p, 'BLOCK', :v, :h, '{}', "
                "CAST(:c AS jsonb), :now, 'test')"
            ),
            {
                "id": new_id(Prefix.DEC, clock.now()), "o": org_id, "p": d.payment_id, "v": d.policy_version_id,
                "h": d.policy_hash, "now": clock.now(),
                "c": json.dumps([{"check": "mandate_scope", "result": "BLOCK", "reason": "MANDATE_AMOUNT_EXCEEDED"}]),
            },
        )  # fmt: skip
        event_id = conn.execute(
            text("SELECT id FROM webhook_events WHERE org_id=:o AND NOT test LIMIT 1"), {"o": org_id}
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO webhook_deliveries (id, org_id, endpoint_id, event_id, attempt, status_code, "
                "created_at) VALUES (:id, :o, :ep, :e, 1, 204, :now)"
            ),
            {
                "id": new_id(Prefix.WHD, clock.now()),
                "o": org_id,
                "ep": hook["id"],
                "e": event_id,
                "now": clock.now(),
            },
        )


def test_the_checklist_is_filled_from_sandbox_evidence(
    web: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    assert not any(_keys(engine, owner.org_id).values())
    _evidence_by_api(web, engine, clock, owner)
    got = _keys(engine, owner.org_id)
    assert {k for k, v in got.items() if v} == {"timeout", "revert", "screening", "allowlist", "idempotency",
                                                 "unknown"}  # fmt: skip
    _evidence_by_hand(engine, clock, owner.org_id)
    assert all(_keys(engine, owner.org_id).values())


def test_the_owner_requests_verification_and_an_admin_returns_then_verifies_it(
    web: TestClient, owner: Member, staff: Member, engine: Engine, clock: FrozenClock
) -> None:
    assert sign_in(web, owner.email).status_code == 303
    page = web.get("/dashboard/verification").text
    assert "not yet" in page and "disabled" in page
    early = post(web, "/dashboard/verification/request", {}, page="/dashboard/verification")
    assert early.status_code == 409 and "no sandbox evidence" in early.text
    _evidence_by_api(web, engine, clock, owner)
    _evidence_by_hand(engine, clock, owner.org_id)
    r = post(web, "/dashboard/verification/request", {}, page="/dashboard/verification")
    assert r.status_code == 303
    again = post(web, "/dashboard/verification/request", {}, page="/dashboard/verification")
    assert again.status_code == 409
    with engine.connect() as conn:
        req = verification.latest(conn, owner.org_id)
    assert req.status == "requested" and all(i["done"] for i in req.checklist)

    admin = TestClient(web.app)
    assert sign_in(admin, staff.email).status_code == 303
    assert req.id in admin.get("/admin/verifications").text
    url = f"/admin/verifications/{owner.org_id}/{req.id}"
    assert (
        post(admin, url, {"outcome": "returned", "note": ""}, page="/admin/verifications").status_code == 422
    )
    assert post(admin, url, {"outcome": "returned", "note": "Show a webhook from your staging endpoint"},
                page="/admin/verifications").status_code == 303  # fmt: skip
    assert post(admin, url, {"outcome": "verified"}, page="/admin/verifications").status_code == 409  # final
    assert "Show a webhook" in web.get("/dashboard/verification").text

    assert post(web, "/dashboard/verification/request", {}, page="/dashboard/verification").status_code == 303
    with engine.connect() as conn:
        second = verification.latest(conn, owner.org_id)
    assert post(admin, f"/admin/verifications/{owner.org_id}/{second.id}", {"outcome": "verified"},
                page="/admin/verifications").status_code == 303  # fmt: skip
    assert "verified" in web.get("/dashboard/verification").text
    assert post(web, "/dashboard/verification/request", {}, page="/dashboard/verification").status_code == 409
    kinds = audit_kinds(engine, owner.org_id)
    assert kinds.count("verification.requested") == 2
    assert "verification.returned" in kinds and "verification.verified" in kinds
    with pytest.raises(Exception, match="final"), engine.begin() as conn:
        conn.execute(
            text("UPDATE verification_requests SET note='edited' WHERE org_id=:o AND id=:i"),
            {"o": owner.org_id, "i": second.id},
        )


def test_only_the_owner_or_an_admin_can_request_verification(
    web: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    email = _email("dev")
    with engine.begin() as conn:
        token = access.invite(
            conn, clock, SETTINGS, org_id=owner.org_id, email=email, role=Role.DEVELOPER, by=owner
        )
        access.accept_invite(conn, clock, token=token, display_name="Dev", password=PASSWORD)
    assert sign_in(web, email).status_code == 303
    page = web.get("/dashboard/verification")
    assert page.status_code == 200 and "The account owner or an admin requests verification" in page.text
    r = web.post("/dashboard/verification/request", data={"csrf": token_of(web, "/dashboard/verification")})
    assert r.status_code == 403


def test_the_website_form_fields_are_accepted(web: TestClient, engine: Engine) -> None:
    email = f"site-{uuid.uuid4().hex[:8]}@example.test"
    site = {"name": "Lin", "email": email, "title": "CFO", "company": "Fictional Markets", "country": "Ireland",
            "platform": "Marketplace", "rails": "Both", "message": "Two approvers today."}  # fmt: skip
    assert web.post("/access-requests", data=site).status_code == 200
    (lead,) = _leads(engine, email)
    assert lead["role"] == "CFO"
    assert lead["use_case"] == "Two approvers today.\nCountry: Ireland\nPlatform: Marketplace\nRails: Both"
