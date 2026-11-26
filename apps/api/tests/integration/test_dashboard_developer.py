"""P2 group 2: the keys, request logs, webhooks and usage pages; metering and sandbox quotas
(DSH-04, DSH-05, DSH-06, DSH-08, LED-08, SBX-02)."""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from conftest import make_settings
from cryptography.fernet import Fernet
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.dashboard import access
from detent.dashboard.access import Member
from detent.domain.roles import Role
from detent.sandbox import usage
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from test_dashboard_access import PASSWORD, _email, audit_kinds, owner_of, sign_in, token_of

pytestmark = pytest.mark.db

SETTINGS = make_settings(
    "org_detent",
    dashboard_url="https://dashboard.example.test",
    credentials_encryption_key=SecretStr(Fernet.generate_key().decode()),
)
SECRET = re.compile(r'value="(sk_test_[A-Za-z0-9_-]+)"')


@pytest.fixture
def staff(engine: Engine, clock: FrozenClock) -> Member:
    with engine.begin() as conn:
        return access.create_staff(
            conn, clock, email=_email("staff"), display_name="Staff Admin", password=PASSWORD
        )


@pytest.fixture
def web(engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    with TestClient(create_app(SETTINGS, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


@pytest.fixture
def owner(engine: Engine, clock: FrozenClock, staff: Member, web: TestClient) -> Member:
    _org, member = owner_of(engine, clock, staff)
    assert sign_in(web, member.email).status_code == 303
    return member


def form(c: TestClient, path: str, data: dict[str, Any], page: str) -> Any:
    return c.post(path, data={**data, "csrf": token_of(c, page)}, follow_redirects=False)


def new_key(
    c: TestClient, name: str = "staging", scopes: tuple[str, ...] = ("read", "intents:create")
) -> str:
    r = form(c, "/dashboard/keys", {"name": name, "scopes": list(scopes)}, "/dashboard/keys")
    assert r.status_code == 201, r.text
    assert r.headers["cache-control"] == "no-store"
    m = SECRET.search(r.text)
    assert m
    return m.group(1)


def key_id(engine: Engine, org_id: str, name: str, *, live: bool = True) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                text(
                    "SELECT id FROM api_keys WHERE org_id=:o AND name=:n AND (rolled_to IS NULL) = :live "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"o": org_id, "n": name, "live": live},
            ).scalar_one()
        )


def bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def member_with(engine: Engine, clock: FrozenClock, owner: Member, role: Role) -> Member:
    email = _email(role.value)
    with engine.begin() as conn:
        token = access.invite(conn, clock, SETTINGS, org_id=owner.org_id, email=email, role=role, by=owner)
        return access.accept_invite(conn, clock, token=token, display_name="Rae Member", password=PASSWORD)


# ------------------------------------------------------------------------------------------ DSH-04
def test_a_key_is_shown_once_works_and_records_its_last_use(
    web: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    page = web.get("/dashboard/keys").text
    assert "Production keys" in page and "Not available in the prototype" in page
    secret = new_key(web)
    assert secret.startswith("sk_test_")
    assert secret not in web.get("/dashboard/keys").text  # shown once
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT hash, name, created_by, last_used_at FROM api_keys WHERE org_id=:o"),
            {"o": owner.org_id},
        ).one()
    assert secret not in row.hash and row.name == "staging" and row.created_by == owner.id
    assert row.last_used_at is None and "Never" in web.get("/dashboard/keys").text
    assert web.get("/v1/payment_intents", headers=bearer(secret)).status_code == 200
    with engine.connect() as conn:
        used = conn.execute(
            text("SELECT last_used_at FROM api_keys WHERE org_id=:o"), {"o": owner.org_id}
        ).scalar()
    assert used == clock.now()
    assert "api_key.created" in audit_kinds(engine, owner.org_id)


def test_roll_keeps_the_old_key_for_the_overlap_and_revoke_is_immediate(
    web: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    old = new_key(web, "server")
    old_id = key_id(engine, owner.org_id, "server")
    r = form(web, f"/dashboard/keys/{old_id}/roll", {"overlap_hours": "2"}, "/dashboard/keys")
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    m = SECRET.search(r.text)
    assert m
    new = m.group(1)
    assert new != old
    assert web.get("/v1/payment_intents", headers=bearer(old)).status_code == 200  # in the overlap
    assert web.get("/v1/payment_intents", headers=bearer(new)).status_code == 200
    again = form(web, f"/dashboard/keys/{old_id}/roll", {"overlap_hours": "2"}, "/dashboard/keys")
    assert again.status_code == 409  # roll the replacement instead
    clock.advance(timedelta(hours=2, seconds=1))
    assert web.get("/v1/payment_intents", headers=bearer(old)).status_code == 401
    assert web.get("/v1/payment_intents", headers=bearer(new)).status_code == 200
    new_id = key_id(engine, owner.org_id, "server")
    assert form(web, f"/dashboard/keys/{new_id}/revoke", {}, "/dashboard/keys").status_code == 303
    assert web.get("/v1/payment_intents", headers=bearer(new)).status_code == 401  # at once
    with engine.connect() as conn:
        rolled = conn.execute(
            text("SELECT scopes, rolled_from FROM api_keys WHERE org_id=:o AND id=:i"),
            {"o": owner.org_id, "i": new_id},
        ).one()
    assert rolled.rolled_from == old_id and sorted(rolled.scopes) == ["intents:create", "read"]
    kinds = audit_kinds(engine, owner.org_id)
    assert {"api_key.created", "api_key.rolled", "api_key.revoked"} <= set(kinds)


def test_key_forms_check_the_name_scopes_and_overlap(web: TestClient, owner: Member, engine: Engine) -> None:
    r = form(web, "/dashboard/keys", {"name": "x", "scopes": []}, "/dashboard/keys")
    assert r.status_code == 422 and "at least one scope" in r.text
    r = form(web, "/dashboard/keys", {"name": "x", "scopes": ["root"]}, "/dashboard/keys")
    assert r.status_code == 422
    new_key(web, "k")
    kid = key_id(engine, owner.org_id, "k")
    assert (
        form(web, f"/dashboard/keys/{kid}/roll", {"overlap_hours": "999"}, "/dashboard/keys").status_code
        == 422
    )
    assert (
        form(web, f"/dashboard/keys/{kid}/roll", {"overlap_hours": "soon"}, "/dashboard/keys").status_code
        == 422
    )
    assert form(web, "/dashboard/keys/key_nope/revoke", {}, "/dashboard/keys").status_code == 404


def test_roles_without_keys_manage_cannot_see_or_change_keys(
    web: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    new_key(web, "owners")
    kid = key_id(engine, owner.org_id, "owners")
    reviewer = member_with(engine, clock, owner, Role.REVIEWER)
    assert sign_in(web, reviewer.email).status_code == 303
    assert web.get("/dashboard/keys").status_code == 403
    assert web.get("/dashboard/logs").status_code == 403
    assert web.get("/dashboard/webhooks").status_code == 403
    assert form(web, f"/dashboard/keys/{kid}/revoke", {}, "/dashboard/").status_code == 403
    r = form(web, "/dashboard/webhooks", {"url": "https://hooks.example.test/a"}, "/dashboard/")
    assert r.status_code == 403
    assert web.get("/dashboard/usage").status_code == 200  # usage is open to every member
    developer = member_with(engine, clock, owner, Role.DEVELOPER)
    assert sign_in(web, developer.email).status_code == 303
    assert web.get("/dashboard/keys").status_code == 200


def test_a_suspended_organisation_cannot_make_keys(
    web: TestClient, owner: Member, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    with engine.begin() as conn:
        access.suspend(conn, clock, staff=staff, org_id=owner.org_id, reason="KYB review")
    page = web.get("/dashboard/keys").text
    assert "suspended" in page and "Create sandbox key" not in page
    r = form(web, "/dashboard/keys", {"name": "x", "scopes": ["read"]}, "/dashboard/keys")
    assert r.status_code == 403


# ------------------------------------------------------------------------------------------ DSH-05
def test_request_logs_filter_and_show_a_redacted_detail(
    web: TestClient, owner: Member, engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    secret = new_key(web)
    web.get("/v1/payment_intents?secret_query=1", headers={**bearer(secret), "Idempotency-Key": "idem-abc"})
    web.get("/v1/payment_intents/pay_00000000000000000000000000", headers=bearer(secret))
    web.post("/v1/payment_intents", json={}, headers=bearer(secret))
    page = web.get("/dashboard/logs").text
    assert "/v1/payment_intents" in page and "secret_query" not in page
    assert "404" in web.get("/dashboard/logs?status=404").text
    only_4xx = web.get("/dashboard/logs?status=4xx").text
    assert '<td class="mono">200</td>' not in only_4xx and '<td class="mono">404</td>' in only_4xx
    assert web.get("/dashboard/logs?status=teapot").status_code == 422
    assert (
        "pay_00000000000000000000000000"
        in web.get("/dashboard/logs?payment_id=pay_00000000000000000000000000").text
    )
    assert "No requests match" in web.get("/dashboard/logs?idempotency_key=other").text
    assert "idem-abc" in web.get("/dashboard/logs?idempotency_key=idem-abc").text
    assert "No requests match" in web.get("/dashboard/logs?path=/v1/exceptions").text
    with engine.connect() as conn:
        log_id = conn.execute(
            text("SELECT id FROM request_logs WHERE org_id=:o ORDER BY id LIMIT 1"), {"o": owner.org_id}
        ).scalar_one()
    detail = web.get(f"/dashboard/logs/{log_id}").text
    assert "[redacted]" in detail and "idem-abc" in detail
    # Another organisation's log entry is not found.
    other_org, other = owner_of(engine, clock, staff)
    assert sign_in(web, other.email).status_code == 303
    assert web.get(f"/dashboard/logs/{log_id}").status_code == 404
    assert other_org != owner.org_id


# ------------------------------------------------------------------------------------------ DSH-06
def test_webhooks_page_covers_create_secret_once_test_resend_and_disable(
    web: TestClient, owner: Member, engine: Engine
) -> None:
    r = form(web, "/dashboard/webhooks", {"url": "http://hooks.example.test/a"}, "/dashboard/webhooks")
    assert r.status_code == 422 and "https://" in r.text
    r = form(
        web,
        "/dashboard/webhooks",
        {"url": "https://hooks.example.test/a", "description": "ops", "event_types": ["exception.created"]},
        "/dashboard/webhooks",
    )
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    m = re.search(r'value="(whsec_[A-Za-z0-9_-]+)"', r.text)
    assert m
    listing = web.get("/dashboard/webhooks").text
    assert m.group(1) not in listing and "https://hooks.example.test/a" in listing
    with engine.connect() as conn:
        ep = conn.execute(
            text("SELECT id FROM webhook_endpoints WHERE org_id=:o"), {"o": owner.org_id}
        ).scalar_one()
    detail = f"/dashboard/webhooks/{ep}"
    assert "Delivery log" in web.get(detail).text
    assert form(web, f"{detail}/test", {}, detail).headers["location"].endswith("notice=test_sent")
    with engine.connect() as conn:
        event = conn.execute(
            text("SELECT id FROM webhook_events WHERE org_id=:o AND type='webhook.test'"), {"o": owner.org_id}
        ).scalar_one()
    assert form(web, f"{detail}/resend", {"event_id": event}, detail).status_code == 303
    assert form(web, f"{detail}/resend", {"event_id": "evt_nope"}, detail).status_code == 404
    assert form(web, f"{detail}/disable", {}, detail).status_code == 303
    assert "disabled" in web.get(detail).text
    assert form(web, f"{detail}/test", {}, detail).status_code == 409
    assert web.get("/dashboard/webhooks/whe_nope").status_code == 404
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT kind, payload, actor FROM audit_events WHERE org_id=:o AND kind LIKE 'webhook%'"),
            {"o": owner.org_id},
        ).all()
    kinds = {r.kind for r in rows}
    assert {"webhook_endpoint.created", "webhook.test_sent", "webhook.resend_requested"} <= kinds
    assert "webhook_endpoint.disabled" in kinds
    assert all(r.payload.get("via") == "dashboard" and r.actor == owner.id for r in rows)


# ------------------------------------------------------------------------------------------ SBX-02, LED-08
@pytest.fixture
def dorg(engine: Engine, clock: FrozenClock) -> DecisionOrg:
    return setup_decision_org(engine, clock)


@pytest.fixture
def api(dorg: DecisionOrg, engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    s = make_settings(dorg.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def _set_quota(engine: Engine, org_id: str, payments: int | None, investigations: int | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE organisations SET daily_payment_quota=:p, daily_investigation_quota=:i WHERE org_id=:o"
            ),
            {"p": payments, "i": investigations, "o": org_id},
        )


def _intent(
    api: TestClient, d: DecisionOrg, idem: str | None = None, path: str = "/v1/payment_intents"
) -> Any:
    dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": d.wallets["WALLET_BLUEFIN_BASE"]}
    body = payout("cpt_bluefin", "120.00", "USDC", dest, reference="INV-Q")
    return api.post(path, json=body, headers={**d.auth(), "Idempotency-Key": idem or str(uuid.uuid4())})


def test_over_the_daily_payment_quota_is_429_quota_exceeded_and_nothing_is_created(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    _set_quota(engine, dorg.id, 2)
    first = _intent(api, dorg, "idem-q-1")
    assert first.status_code in (200, 201)
    assert _intent(api, dorg, path="/v1/decisions").status_code in (200, 201)  # dry runs count too
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT count(*) FROM payment_intents WHERE org_id=:o"), {"o": dorg.id}
        ).scalar()
    over = _intent(api, dorg)
    assert over.status_code == 429
    err = over.json()["error"]
    assert err["type"] == "quota" and err["code"] == "quota_exceeded"
    assert 0 < int(over.headers["retry-after"]) <= 86_400
    with engine.connect() as conn:
        after = conn.execute(
            text("SELECT count(*) FROM payment_intents WHERE org_id=:o"), {"o": dorg.id}
        ).scalar()
    assert after == before
    assert _intent(api, dorg, "idem-q-1").json()["id"] == first.json()["id"]  # a replay is not a new decision
    clock.advance(timedelta(days=1))
    assert _intent(api, dorg).status_code in (200, 201)  # a new UTC day
    with engine.connect() as conn:
        days = conn.execute(
            text(
                "SELECT day, count FROM usage_daily WHERE org_id=:o AND metric='payments_decided' ORDER BY day"
            ),
            {"o": dorg.id},
        ).all()
    assert [r.count for r in days] == [2, 1]


def test_the_quota_holds_under_concurrent_requests(
    engine: Engine, clock: FrozenClock, dorg: DecisionOrg
) -> None:
    _set_quota(engine, dorg.id, 3)
    ok, refused = [], []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        try:
            with engine.begin() as conn:
                ok.append(usage.consume(conn, clock, dorg.id, "payments_decided"))
        except usage.QuotaExceeded:
            refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(ok) == [1, 2, 3] and len(refused) == 5


def test_api_calls_are_metered_and_months_add_up(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    for _ in range(3):
        api.get("/v1/payment_intents", headers=dorg.auth())
    now = clock.now()
    with engine.connect() as conn:
        month = usage.monthly(conn, dorg.id, now.year, now.month)
        nxt = usage.monthly(conn, dorg.id, now.year + (now.month == 12), now.month % 12 + 1)
    assert month["api_calls"] == 3 and month["payments_decided"] == 0
    assert nxt == {"api_calls": 0, "payments_decided": 0, "agent_investigations": 0}


def test_over_the_investigation_quota_the_case_goes_to_a_person(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    from detent.agents.investigation import latest_investigation
    from detent.runtime import Runtime
    from detent.worker.loop import Worker
    from test_investigation import escalated_case

    _set_quota(engine, dorg.id, None, 1)
    _, first = escalated_case(api, dorg, engine)
    _, second = escalated_case(api, dorg, engine)
    w = Worker(Runtime(make_settings(dorg.id), engine, clock), worker_id="test-quota", org_id=dorg.id)
    while w.run_one():
        pass
    with engine.connect() as conn:
        a = latest_investigation(conn, dorg.id, first)
        b = latest_investigation(conn, dorg.id, second)
    assert a and a["status"] == "recorded"
    assert b and b["status"] == "needs_human" and b["flags"][0]["code"] == "QUOTA_EXCEEDED"


# ------------------------------------------------------------------------------------------ DSH-08
def test_new_organisations_get_the_quotas_and_the_usage_page_shows_them(
    web: TestClient, owner: Member, engine: Engine
) -> None:
    with engine.connect() as conn:
        org = conn.execute(
            text("SELECT daily_payment_quota, daily_investigation_quota FROM organisations WHERE org_id=:o"),
            {"o": owner.org_id},
        ).one()
    assert (org.daily_payment_quota, org.daily_investigation_quota) == (500, 50)
    secret = new_key(web)
    web.get("/v1/payment_intents", headers=bearer(secret))
    page = web.get("/dashboard/usage").text
    assert "Payments decided" in page and "Agent investigations" in page
    assert '<span class="mono">500</span>' in page and '<span class="mono">50</span>' in page
    assert re.search(r"API calls</td><td class=\"mono\">1</td>", page)
