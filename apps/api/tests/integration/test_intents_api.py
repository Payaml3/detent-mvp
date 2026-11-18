"""S1 exit check over HTTP: INT-01, INT-02, INT-03, POL-08 and the fixture counterparties' outcomes."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from conftest import make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import verify_chain
from detent.clock import FrozenClock
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


@pytest.fixture
def dorg(engine: Engine, clock: FrozenClock) -> DecisionOrg:
    return setup_decision_org(engine, clock)


@pytest.fixture
def api(dorg: DecisionOrg, engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    s = make_settings(dorg.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def post(
    api: TestClient,
    dorg: DecisionOrg,
    body: dict[str, object],
    key: str | None = None,
    path: str = "/v1/payment_intents",
):  # type: ignore[no-untyped-def]
    return api.post(path, json=body, headers={**dorg.auth(), "Idempotency-Key": key or str(uuid.uuid4())})


def checks(resp_json: dict[str, object]) -> dict[str, dict[str, object]]:
    return {c["check"]: c for c in resp_json["decision"]["checks"]}  # type: ignore[index, union-attr]


HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}
QUILL = {"destination_id": "dst_quill_acct", "kind": "bank_account", "network": "banksim-fps"}


# ------------------------------------------------------------------------------ INT-01 and the fixtures
def test_harbor_executes(api: TestClient, dorg: DecisionOrg) -> None:
    r = post(api, dorg, payout("cpt_harbor", "2000.00", "EUR", HARBOR, reference="INV-H-1"))
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["id"].startswith("pay_") and j["status"] == "READY"
    assert j["decision"]["outcome"] == "EXECUTE" and j["decision"]["policy_version"] == 1
    assert all(c["result"] in ("PASS", "NOT_EVALUATED") for c in j["decision"]["checks"])
    assert j["amount"] == {"amount": "2000.00", "currency": "EUR"}


def test_quill_escalates_changed_details(api: TestClient, dorg: DecisionOrg) -> None:
    j = post(api, dorg, payout("cpt_quill", "500.00", "GBP", QUILL)).json()
    assert j["status"] == "ESCALATED" and j["decision"]["outcome"] == "ESCALATE"
    assert checks(j)["changed_details"]["reason"] == "CHANGED_DETAILS"


def test_nova_escalates(api: TestClient, dorg: DecisionOrg) -> None:
    dest = {"kind": "evm_wallet", "network": "eth-sepolia", "address": dorg.wallets["WALLET_NOVA_ETH"]}
    j = post(api, dorg, payout("cpt_nova", "300.00", "USDC", dest)).json()
    assert j["status"] == "ESCALATED"
    reasons = {c.get("reason") for c in j["decision"]["checks"]}
    assert {"KYB_PENDING", "NOT_ALLOWLISTED", "NEW_WALLET", "FIRST_PAYMENT"} <= reasons


def test_flagged_payee_is_blocked(api: TestClient, dorg: DecisionOrg) -> None:
    dest = {
        "kind": "evm_wallet",
        "network": "base-sepolia",
        "address": "0x000000000000000000000000000000000000dEaD",
    }
    j = post(api, dorg, payout("cpt_flagged", "100.00", "USDC", dest)).json()
    assert j["status"] == "BLOCKED" and checks(j)["screening"]["reason"] == "SCREENING_HIT"


def test_bluefin_18500_escalates_first_payment_and_auto_limit(api: TestClient, dorg: DecisionOrg) -> None:
    dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": dorg.wallets["WALLET_BLUEFIN_BASE"]}
    j = post(api, dorg, payout("cpt_bluefin", "18500.00", "USDC", dest, reference="INV-2026-0142")).json()
    c = checks(j)
    assert j["status"] == "ESCALATED"
    assert c["first_payment"]["reason"] == "FIRST_PAYMENT" and c["auto_limit"]["reason"] == "ABOVE_AUTO_LIMIT"
    assert c["auto_limit"]["evidence"] == {"amount": "18500.00", "auto_limit": "10000.00"}
    assert c["travel_rule"]["result"] == "PASS"


def test_unregistered_address_becomes_a_new_destination(
    api: TestClient, dorg: DecisionOrg, engine: Engine
) -> None:  # G-01
    new = "0x1111111111111111111111111111111111111111"
    j = post(
        api,
        dorg,
        payout(
            "cpt_bluefin", "100.00", "USDC", {"kind": "evm_wallet", "network": "base-sepolia", "address": new}
        ),
    ).json()
    assert checks(j)["new_wallet"]["reason"] == "NEW_WALLET"
    with engine.connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM destinations WHERE org_id=:o AND lower(address)=:a"),
            {"o": dorg.id, "a": new},
        ).scalar()
    assert n == 1


def test_invalid_input_is_422_and_creates_nothing(api: TestClient, dorg: DecisionOrg, engine: Engine) -> None:
    bad = [
        payout("cpt_harbor", "12.345", "EUR", HARBOR),  # too many decimals for EUR
        payout("cpt_harbor", 2000.5, "EUR", HARBOR),  # float amount  # type: ignore[arg-type]
        payout("cpt_harbor", "-5.00", "EUR", HARBOR),
        payout("cpt_nobody", "5.00", "EUR", HARBOR),
        {**payout("cpt_harbor", "5.00", "EUR", HARBOR), "source": "agent"},  # agent needs a mandate_id
        {**payout("cpt_harbor", "5.00", "EUR", HARBOR), "source": "robot"},
    ]
    for body in bad:
        r = post(api, dorg, body)
        assert r.status_code == 422, (body, r.text)
        err = r.json()["error"]
        assert err["type"] == "invalid_request" and err["request_id"] == r.headers["Request-Id"]
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM payment_intents WHERE org_id=:o"), {"o": dorg.id}).scalar()
            == 0
        )


def test_user_payouts_are_not_available_yet(api: TestClient, dorg: DecisionOrg) -> None:  # D-26
    body = {
        "kind": "payout",
        "source": "platform",
        "user_account_ref": "acct_u1001",
        "destination": {
            "kind": "evm_wallet",
            "network": "base-sepolia",
            "address": "0x2222222222222222222222222222222222222222",
        },
        "amount": {"amount": "5.00", "currency": "USDC"},
    }
    r = post(api, dorg, body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "user_payouts_unavailable"


def test_agent_intent_with_unknown_mandate_is_refused(
    api: TestClient, dorg: DecisionOrg, engine: Engine
) -> None:
    body = {**payout("cpt_harbor", "20.00", "EUR", HARBOR), "source": "agent", "mandate_id": "mnd_unknown"}
    r = post(api, dorg, body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "mandate_invalid"
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM payment_intents WHERE org_id=:o"), {"o": dorg.id}).scalar()
            == 0
        )


def test_agent_intent_never_executes_before_mandate_checks_exist(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    # MND-02 (slice S5) verifies mandates. Until then an agent intent fails closed, whatever it asks for.
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO mandates (id, org_id, agent_id, version, payload, signature, valid_from, expires_at, created_at) "
                "VALUES ('mnd_t1', :o, 'agt_test', 1, '{}', 'unsigned', :t, :t, :t)"
            ),
            {"o": dorg.id, "t": clock.now()},
        )
    body = {**payout("cpt_harbor", "20.00", "EUR", HARBOR), "source": "agent", "mandate_id": "mnd_t1"}
    j = post(api, dorg, body).json()
    assert j["decision"]["outcome"] != "EXECUTE" and j["status"] != "READY"
    assert j["decision"]["checks"][0] == {
        "check": "mandate_scope",
        "result": "ESCALATE",
        "reason": "SYSTEM_UNAVAILABLE",
        "evidence": {"dependency": "mandate_verifier", "error": "not_built"},
    }


# ------------------------------------------------------------------------------ authentication
def test_requests_need_a_valid_key(api: TestClient, dorg: DecisionOrg) -> None:
    r = api.get("/v1/payment_intents")
    assert r.status_code == 401 and r.json()["error"]["type"] == "authentication"
    r = api.get("/v1/payment_intents", headers={"Authorization": "Bearer sk_" + "test_nottherightkey"})
    assert r.status_code == 401


def test_wrong_scope_is_403(engine: Engine, clock: FrozenClock) -> None:
    ro = setup_decision_org(engine, clock, scopes=["read"])
    s = make_settings(ro.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        r = c.post(
            "/v1/payment_intents",
            json=payout("cpt_harbor", "1.00", "EUR", HARBOR),
            headers={**ro.auth(), "Idempotency-Key": "k1"},
        )
        assert r.status_code == 403 and r.json()["error"]["code"] == "insufficient_scope"
        assert c.get("/v1/payment_intents", headers=ro.auth()).status_code == 200


# ------------------------------------------------------------------------------ INT-02 idempotency
def test_same_key_same_body_returns_the_original(api: TestClient, dorg: DecisionOrg, engine: Engine) -> None:
    body = payout("cpt_harbor", "2000.00", "EUR", HARBOR)
    a, b = post(api, dorg, body, key="idem-1"), post(api, dorg, body, key="idem-1")
    assert a.status_code == b.status_code == 201 and a.json() == b.json()
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM payment_intents WHERE org_id=:o"), {"o": dorg.id}).scalar()
            == 1
        )


def test_same_key_different_body_conflicts(api: TestClient, dorg: DecisionOrg) -> None:
    post(api, dorg, payout("cpt_harbor", "2000.00", "EUR", HARBOR), key="idem-2")
    r = post(api, dorg, payout("cpt_harbor", "2000.01", "EUR", HARBOR), key="idem-2")
    assert r.status_code == 409 and r.json()["error"]["code"] == "idempotency_conflict"


def test_idempotency_key_is_required(api: TestClient, dorg: DecisionOrg) -> None:
    r = api.post("/v1/payment_intents", json=payout("cpt_harbor", "1.00", "EUR", HARBOR), headers=dorg.auth())
    assert r.status_code == 422 and r.json()["error"]["param"] == "Idempotency-Key"


def test_keys_are_scoped_per_organisation(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    other = setup_decision_org(engine, clock)
    body = payout("cpt_harbor", "2000.00", "EUR", HARBOR)
    a = post(api, dorg, body, key="shared-key")
    b = api.post("/v1/payment_intents", json=body, headers={**other.auth(), "Idempotency-Key": "shared-key"})
    assert a.status_code == b.status_code == 201 and a.json()["id"] != b.json()["id"]


# ------------------------------------------------------------------------------ INT-03 read and list
def test_get_intent_with_timeline(api: TestClient, dorg: DecisionOrg) -> None:
    pid = post(api, dorg, payout("cpt_harbor", "2000.00", "EUR", HARBOR)).json()["id"]
    r = api.get(f"/v1/payment_intents/{pid}", headers=dorg.auth())
    assert r.status_code == 200
    j = r.json()
    assert j["id"] == pid and len(j["decisions"]) == 1 and j["attempts"] == [] and j["postings"] == []
    kinds = [e["kind"] for e in j["events"]]
    assert (
        kinds[:1] == ["payment.received"] and "decision.made" in kinds and "payment.status_changed" in kinds
    )


def test_other_organisations_payment_is_404(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    other = setup_decision_org(engine, clock)
    s = make_settings(other.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c2:
        pid = c2.post(
            "/v1/payment_intents",
            json=payout("cpt_harbor", "1.00", "EUR", HARBOR),
            headers={**other.auth(), "Idempotency-Key": "x"},
        ).json()["id"]
    r = api.get(f"/v1/payment_intents/{pid}", headers=dorg.auth())
    assert r.status_code == 404 and r.json()["error"]["type"] == "not_found"


def test_list_paginates_and_filters(api: TestClient, dorg: DecisionOrg, clock: FrozenClock) -> None:
    from datetime import timedelta

    ids = []
    for i in range(5):
        clock.advance(timedelta(seconds=1))
        ids.append(post(api, dorg, payout("cpt_harbor", f"{100 + i}.00", "EUR", HARBOR)).json()["id"])
    post(api, dorg, payout("cpt_quill", "10.00", "GBP", QUILL))  # ESCALATED
    page1 = api.get("/v1/payment_intents?status=READY&limit=2", headers=dorg.auth()).json()
    assert [p["id"] for p in page1["data"]] == ids[::-1][:2] and page1["has_more"]
    page2 = api.get(
        f"/v1/payment_intents?status=READY&limit=2&starting_after={page1['next_cursor']}", headers=dorg.auth()
    ).json()
    assert [p["id"] for p in page2["data"]] == ids[::-1][2:4]
    esc = api.get("/v1/payment_intents?status=ESCALATED", headers=dorg.auth()).json()
    assert len(esc["data"]) == 1
    assert (
        api.get("/v1/payment_intents?rail=banksim-sepa", headers=dorg.auth()).json()["data"] == []
    )  # no attempts yet
    t = clock.now().isoformat()
    assert api.get("/v1/payment_intents", params={"created[gte]": t}, headers=dorg.auth()).json()["data"]


# ------------------------------------------------------------------------------ POL-08 decision only
def test_decision_only_executes_nothing(api: TestClient, dorg: DecisionOrg, engine: Engine) -> None:
    r = post(api, dorg, payout("cpt_harbor", "2000.00", "EUR", HARBOR), path="/v1/decisions")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["outcome"] == "EXECUTE" and j["executed"] is False and j["id"].startswith("dec_")
    with engine.connect() as c:
        st = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"),
            {"o": dorg.id, "p": j["payment_id"]},
        ).scalar()
        att = c.execute(text("SELECT count(*) FROM attempts WHERE org_id=:o"), {"o": dorg.id}).scalar()
        used = c.execute(
            text("SELECT coalesce(sum(amount_minor),0) FROM counters WHERE org_id=:o"), {"o": dorg.id}
        ).scalar()
    assert st == "SHADOWED" and att == 0 and used == 0


def test_shadow_mode_shadows_executes(engine: Engine, clock: FrozenClock) -> None:
    sh = setup_decision_org(engine, clock, mode="shadow")
    s = make_settings(sh.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        j = c.post(
            "/v1/payment_intents",
            json=payout("cpt_harbor", "2000.00", "EUR", HARBOR),
            headers={**sh.auth(), "Idempotency-Key": "s"},
        ).json()
    assert j["status"] == "SHADOWED" and j["decision"]["outcome"] == "EXECUTE"


# ------------------------------------------------------------------------------ AUD-01 in the flow
def test_every_step_is_audited_and_the_chain_verifies(
    api: TestClient, dorg: DecisionOrg, engine: Engine
) -> None:
    pid = post(api, dorg, payout("cpt_quill", "500.00", "GBP", QUILL)).json()["id"]
    with engine.connect() as c:
        rows = c.execute(
            text("SELECT kind, payload FROM audit_events WHERE org_id=:o AND subject_id=:p ORDER BY seq"),
            {"o": dorg.id, "p": pid},
        ).all()
        assert verify_chain(c, dorg.id).ok
    kinds = [r.kind for r in rows]
    assert kinds == ["payment.received", "decision.made", "payment.status_changed"]
    decided = rows[1].payload
    assert (
        decided["outcome"] == "ESCALATE"
        and decided["policy_version"] == 1
        and len(decided["policy_hash"]) == 64
    )
    assert any(ch.get("reason") == "CHANGED_DETAILS" for ch in decided["checks"])
