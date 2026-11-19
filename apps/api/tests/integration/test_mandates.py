"""MND-01, MND-02, MND-03: signed mandates, the mandate check, cumulative totals and revocation."""

from __future__ import annotations

import copy
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from conftest import make_settings
from decision_helpers import PEPPER, DecisionOrg, setup_decision_org
from detent.api.app import create_app
from detent.api.auth import issue_key
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.intents.service import IntentRequest, submit_intent
from detent.mandates.signing import canonical, sign, verify_signature
from detent.mandates.store import fixture_mandate, issue_mandate, revoke_mandate
from detent.policy.screening import MockScreening
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

KEY = SecretStr("test-mandate-key-0123456789abcdef")


def bluefin(
    d: DecisionOrg, amount: str, network: str = "base-sepolia", mandate: str = "mnd_demo_ap_agent"
) -> IntentRequest:
    return IntentRequest.model_validate(
        {
            "kind": "payout",
            "source": "agent",
            "mandate_id": mandate,
            "counterparty_id": "cpt_bluefin",
            "destination": {
                "kind": "evm_wallet",
                "network": network,
                "address": d.wallets["WALLET_BLUEFIN_BASE"],
            },
            "amount": {"amount": amount, "currency": "USDC"},
            "reference": "INV-2026-0142",
        }
    )


def decide(engine: Engine, clock: FrozenClock, d: DecisionOrg, req: IntentRequest) -> dict[str, object]:
    code, body = submit_intent(
        engine,
        clock,
        org_id=d.id,
        actor_id=d.org.users[Role.PAYMENTS_LEAD],
        idempotency_key=str(uuid.uuid4()),
        request=req,
        decision_only=False,
        screening=MockScreening.from_fixture(),
        mandate_key=KEY,
    )
    assert code == 201, body
    return body


def mandate_check(body: dict[str, object]) -> dict[str, object]:
    return body["decision"]["checks"][0]  # type: ignore[index, return-value]


@pytest.fixture
def d(engine: Engine, clock: FrozenClock) -> DecisionOrg:
    org = setup_decision_org(engine, clock)
    with engine.begin() as c:
        issue_mandate(c, clock, org.id, fixture_mandate(clock, org.id), KEY, actor=Actor.system("seed"))
    return org


# ---------------------------------------------------------------------------------------- MND-01
def test_signature_covers_canonical_json_without_the_signature(clock: FrozenClock) -> None:
    doc = fixture_mandate(clock, "org_x")
    body = {k: v for k, v in doc.items() if k != "signature"}
    assert canonical(doc) == canonical(body)  # the signature field is never signed
    c = canonical(doc)
    assert (
        c.startswith(b'{"agent":') and b'": ' not in c and b', "' not in c
    )  # sorted keys, no whitespace between tokens
    doc["signature"]["value"] = sign(doc, KEY)
    assert verify_signature(doc, KEY)
    tampered = copy.deepcopy(doc)
    tampered["scope"]["max_per_payment"]["amount"] = "200000.00"
    assert not verify_signature(tampered, KEY)
    assert not verify_signature(doc, SecretStr("another-key-entirely-000000000"))


def test_format_keeps_ap2_style_fields(clock: FrozenClock) -> None:
    doc = fixture_mandate(clock, "org_x")
    assert {
        "mandate_id",
        "version",
        "principal",
        "agent",
        "scope",
        "valid_from",
        "expires_at",
        "signature",
    } <= set(doc)
    assert {"payees", "max_per_payment", "max_total", "networks", "currencies", "purpose"} <= set(
        doc["scope"]
    )


# ---------------------------------------------------------------------------------------- MND-02
def test_in_scope_agent_intent_passes_the_mandate_and_escalates(
    engine: Engine, clock: FrozenClock, d: DecisionOrg
) -> None:
    body = decide(engine, clock, d, bluefin(d, "18500.00"))
    assert mandate_check(body)["result"] == "PASS"
    reasons = {c.get("reason") for c in body["decision"]["checks"]}  # type: ignore[index, union-attr]
    assert body["status"] == "ESCALATED" and {"FIRST_PAYMENT", "ABOVE_AUTO_LIMIT"} <= reasons


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("amount", "MANDATE_AMOUNT_EXCEEDED"),
        ("payee", "MANDATE_PAYEE_OUT_OF_SCOPE"),
        ("network", "MANDATE_NETWORK_OUT_OF_SCOPE"),
        ("expired", "MANDATE_EXPIRED"),
        ("revoked", "MANDATE_REVOKED"),
        ("signature", "MANDATE_SIGNATURE_INVALID"),
    ],
)
def test_out_of_scope_blocks_with_the_specific_reason(
    engine: Engine, clock: FrozenClock, d: DecisionOrg, change: str, reason: str
) -> None:
    req = bluefin(d, "18500.00")
    if change == "amount":
        req = bluefin(d, "20000.01")
    elif change == "payee":
        req = IntentRequest.model_validate(
            {
                **req.model_dump(mode="json"),
                "counterparty_id": "cpt_quill",
                "destination": {
                    "destination_id": "dst_quill_acct",
                    "kind": "bank_account",
                    "network": "banksim-fps",
                },
                "amount": {"amount": "10.00", "currency": "GBP"},
            }
        )
    elif change == "network":
        req = bluefin(d, "100.00", network="banksim-fps")
        req = IntentRequest.model_validate(
            {
                **req.model_dump(mode="json"),
                "destination": {
                    "kind": "evm_wallet",
                    "network": "local-evm-b",
                    "address": d.wallets["WALLET_BLUEFIN_BASE"],
                },
            }
        )
    elif change == "expired":
        clock.advance(timedelta(days=31))
    elif change == "revoked":
        with engine.begin() as c:
            revoke_mandate(
                c,
                clock,
                d.id,
                "mnd_demo_ap_agent",
                actor=Actor(d.org.users[Role.PAYMENTS_LEAD], "payments_lead"),
            )
    elif change == "signature":
        with engine.begin() as c:
            c.execute(
                text(
                    "UPDATE mandates SET payload = jsonb_set(payload, '{scope,max_per_payment,amount}', '\"900000.00\"') "
                    "WHERE org_id=:o"
                ),
                {"o": d.id},
            )
    body = decide(engine, clock, d, req)
    assert body["status"] == "BLOCKED" and mandate_check(body)["reason"] == reason
    assert len(body["decision"]["checks"]) == 1  # the mandate check short-circuits  # type: ignore[arg-type]


def test_cumulative_total_is_atomic_under_parallel_intents(engine: Engine, clock: FrozenClock) -> None:
    org = setup_decision_org(engine, clock)
    with engine.begin() as c:  # an established payee, so routine agent intents EXECUTE and count
        c.execute(
            text(
                "UPDATE counterparties SET payment_count=10, median_amount_minor=3000000000, median_currency='USDC' "
                "WHERE org_id=:o AND id='cpt_bluefin'"
            ),
            {"o": org.id},
        )
        c.execute(
            text(
                "UPDATE destinations SET first_seen_at=:t, last_changed_at=:t WHERE org_id=:o AND id='dst_bluefin_base'"
            ),
            {"o": org.id, "t": clock.now() - timedelta(days=100)},
        )
        doc = fixture_mandate(clock, org.id)
        doc["scope"]["max_per_payment"]["amount"] = "5000.00"
        doc["scope"]["max_total"]["amount"] = "20000.00"
        issue_mandate(c, clock, org.id, doc, KEY, actor=Actor.system("seed"))

    def one(_: int) -> str:
        return str(decide(engine, clock, org, bluefin(org, "3000.00"))["decision"]["outcome"])  # type: ignore[index]

    with ThreadPoolExecutor(10) as ex:
        outcomes = list(ex.map(one, range(10)))
    assert outcomes.count("EXECUTE") == 6 and outcomes.count("BLOCK") == 4
    with engine.connect() as c:
        used = c.execute(
            text("SELECT total_minor FROM mandate_usage WHERE org_id=:o"), {"o": org.id}
        ).scalar()
    assert used == 18_000_000_000


# ---------------------------------------------------------------------------------------- MND-03
def test_revocation_blocks_an_approved_intent_before_sending(
    engine: Engine, clock: FrozenClock, d: DecisionOrg
) -> None:
    from detent.exceptions.cases import approve
    from detent.execution.send import send_payment

    body = decide(engine, clock, d, bluefin(d, "18500.00"))
    pid, case = str(body["id"]), body["exception"]["id"]  # type: ignore[index]
    res = approve(
        engine,
        clock,
        case_id=case,
        org_id=d.id,
        actor=Actor(d.org.users[Role.REVIEWER], "reviewer"),
        reason="Invoice checked",
        mandate_key=KEY,
    )
    assert res.payment_status == "READY"
    with engine.begin() as c:
        revoke_mandate(
            c, clock, d.id, "mnd_demo_ap_agent", actor=Actor(d.org.users[Role.PAYMENTS_LEAD], "payments_lead")
        )
    st = send_payment(
        engine,
        clock,
        {},
        org_id=d.id,
        payment_id=pid,
        screening=MockScreening.from_fixture(),
        mandate_key=KEY,
    )
    assert st.value == "BLOCKED"
    with engine.connect() as c:
        why = c.execute(
            text(
                "SELECT payload->>'reason' FROM audit_events WHERE org_id=:o AND subject_id=:p "
                "AND kind='payment.status_changed' ORDER BY seq DESC LIMIT 1"
            ),
            {"o": d.id, "p": pid},
        ).scalar()
    assert "MANDATE_REVOKED" in why


def test_revoke_by_api_and_console(engine: Engine, clock: FrozenClock, d: DecisionOrg) -> None:
    from conftest import login

    with engine.begin() as c:
        oncall = issue_key(c, clock, d.id, d.org.users[Role.ONCALL], ["admin"], PEPPER)
    app = create_app(
        make_settings(d.id, api_key_pepper=SecretStr(PEPPER), mandate_signing_key_demo=KEY),
        engine=engine,
        clock=clock,
        configure_logging=False,
    )
    with TestClient(app) as client:
        r = client.post(
            "/v1/mandates/mnd_demo_ap_agent/revoke", headers={"Authorization": f"Bearer {oncall}"}
        )
        assert r.status_code == 403 and r.json()["error"]["code"] == "insufficient_role"
        lst = client.get("/v1/mandates", headers=d.auth()).json()["data"]
        assert lst[0]["mandate_id"] == "mnd_demo_ap_agent" and lst[0]["revoked_at"] is None
        login(client, d.org.users[Role.PAYMENTS_LEAD])
        page = client.get("/console/mandates").text
        assert "mnd_demo_ap_agent" in page and "50000.00 USDC" in page
        assert (
            client.post("/console/mandates/mnd_demo_ap_agent/revoke", follow_redirects=False).status_code
            == 303
        )
        assert client.get("/v1/mandates", headers=d.auth()).json()["data"][0]["revoked_at"] is not None


def test_keys_bound_to_a_mandate_can_only_propose_under_it(
    engine: Engine, clock: FrozenClock, d: DecisionOrg
) -> None:
    with engine.begin() as c:
        agent_key = issue_key(
            c,
            clock,
            d.id,
            d.org.users[Role.PAYMENTS_LEAD],
            ["intents:create"],
            PEPPER,
            mandate_id="mnd_demo_ap_agent",
        )
    app = create_app(
        make_settings(d.id, api_key_pepper=SecretStr(PEPPER), mandate_signing_key_demo=KEY),
        engine=engine,
        clock=clock,
        configure_logging=False,
    )
    h = {"Authorization": f"Bearer {agent_key}"}
    with TestClient(app) as client:
        ok = client.post(
            "/v1/payment_intents",
            json=bluefin(d, "100.00").model_dump(mode="json"),
            headers={**h, "Idempotency-Key": "a1"},
        )
        assert ok.status_code == 201
        as_platform = {
            **bluefin(d, "100.00").model_dump(mode="json"),
            "source": "platform",
            "mandate_id": None,
        }
        r = client.post("/v1/payment_intents", json=as_platform, headers={**h, "Idempotency-Key": "a2"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "mandate_mismatch"
        assert client.post("/v1/kill_switch", headers=h).json()["error"]["code"] == "insufficient_scope"


def test_an_unreadable_stored_signature_is_invalid_not_a_crash(
    engine: Engine, clock: FrozenClock, d: DecisionOrg
) -> None:
    with engine.begin() as c:
        c.execute(text("UPDATE mandates SET signature='not json' WHERE org_id=:o"), {"o": d.id})
    body = decide(engine, clock, d, bluefin(d, "100.00"))
    assert body["status"] == "BLOCKED" and mandate_check(body)["reason"] == "MANDATE_SIGNATURE_INVALID"
