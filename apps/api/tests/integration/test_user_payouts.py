"""Slice U: user payouts (USR-01 user destinations, USR-02 the user payout profile; spec/04, G-10, D-40)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from conftest import login, make_settings
from decision_helpers import PEPPER, DecisionOrg, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.exceptions.cases import approve
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

WALLET = "0x" + "1a" * 20
OTHER = "0x" + "2b" * 20
SCREENED = "0x000000000000000000000000000000000000dEaD"
SKIPPED = {"kyb_status", "allowlist", "first_payment", "above_norm", "daily_cap_counterparty"}
KEPT = {
    "screening", "travel_rule", "allowed_networks", "hard_max", "auto_limit", "daily_cap_platform",
    "new_wallet", "changed_details", "resubmission_after_block",
}  # fmt: skip


@pytest.fixture
def setup(engine: Engine, clock: FrozenClock) -> Iterator[tuple[DecisionOrg, TestClient]]:
    d = setup_decision_org(engine, clock)
    s = make_settings(d.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield d, c


def register(
    api: TestClient, d: DecisionOrg, ref: str, *, verified: bool = True, address: str = WALLET, **kw: Any
) -> dict[str, Any]:
    dest = kw.pop("destination", {"kind": "evm_wallet", "network": "base-sepolia", "address": address})
    r = api.put(
        f"/v1/user_accounts/{ref}",
        json={"user_verified": verified, "destination": dest, **kw},
        headers=d.auth(),
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def pay(api: TestClient, d: DecisionOrg, ref: str, amount: str, *, address: str = WALLET, **kw: Any) -> Any:
    dest = kw.pop("destination", {"kind": "evm_wallet", "network": "base-sepolia", "address": address})
    body = {
        "kind": "payout",
        "source": "platform",
        "user_account_ref": ref,
        "destination": dest,
        "amount": {"amount": amount, "currency": kw.pop("currency", "USDC")},
        **kw,
    }
    return api.post(
        "/v1/payment_intents", json=body, headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())}
    )


def checks(p: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["check"]: c for c in p["decision"]["checks"]}


def events(engine: Engine, org: str, kind: str) -> list[Any]:
    with engine.connect() as c:
        return list(
            c.execute(
                text(
                    "SELECT subject_id, actor, payload FROM audit_events WHERE org_id=:o AND kind=:k ORDER BY seq"
                ),
                {"o": org, "k": kind},
            ).all()
        )


# --------------------------------------------------------------------------------------------- USR-01
def test_a_user_account_has_one_destination_and_a_typed_verified_flag(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    lead = d.org.users[Role.PAYMENTS_LEAD]
    u = register(api, d, "u-1001", holder_name="Ada Example (fictional)")
    assert u["user_verified"] is True and u["verified_set_by"] == lead
    assert u["verified_set_at"] == clock.now().isoformat()
    dst = u["destination"]["id"]
    assert dst.startswith("dst_") and u["destination"]["address"] == WALLET
    assert api.get("/v1/user_accounts/u-1001", headers=d.auth()).json() == u
    assert api.get("/v1/user_accounts/u-none", headers=d.auth()).status_code == 404

    clock.advance(timedelta(hours=1))
    assert register(api, d, "u-1001", holder_name="Ada Example (fictional)") == u  # the same: nothing changes
    v = register(api, d, "u-1001", verified=False, address=OTHER)
    assert v["destination"]["id"] == dst and v["destination"]["address"] == OTHER  # replaced in place
    assert v["user_verified"] is False and v["verified_set_at"] == clock.now().isoformat()
    (changed,) = events(engine, d.id, "destination.changed")
    assert changed.subject_id == dst and changed.payload["old"]["address"] == WALLET
    assert changed.payload["new"]["address"] == OTHER and changed.payload["user_account_ref"] == "u-1001"
    (flag,) = events(engine, d.id, "user_account.verification_changed")
    assert flag.payload == {"from": True, "to": False} and flag.actor == lead
    with engine.connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM destinations WHERE org_id=:o AND user_account_ref='u-1001'"),
            {"o": d.id},
        ).scalar()
    assert n == 1


def test_bad_registrations_are_refused(setup: tuple[DecisionOrg, TestClient]) -> None:
    d, api = setup
    bad = [
        {"user_verified": "yes", "destination": {"kind": "evm_wallet", "network": "base-sepolia", "address": WALLET}},
        {"user_verified": True, "destination": {"kind": "bank_account", "network": "banksim-fps", "address": WALLET}},
        {"user_verified": True, "destination": {"kind": "evm_wallet", "network": "base-sepolia"}},
    ]  # fmt: skip
    for body in bad:
        assert api.put("/v1/user_accounts/u-1", json=body, headers=d.auth()).status_code == 422, body
    assert api.put("/v1/user_accounts/bad ref", json=bad[0], headers=d.auth()).status_code == 422


def test_a_user_payout_goes_only_to_the_registered_destination(
    setup: tuple[DecisionOrg, TestClient], engine: Engine
) -> None:
    d, api = setup
    register(api, d, "u-1")
    r = pay(api, d, "u-1", "50.00", address=OTHER)
    assert r.status_code == 422 and r.json()["error"]["param"] == "destination"
    r = pay(api, d, "u-1", "50.00", source="agent", mandate_id="mnd_demo_ap_agent")
    assert r.status_code == 422 and r.json()["error"]["param"] == "user_account_ref"
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM payment_intents WHERE org_id=:o"), {"o": d.id}).scalar() == 0
        )


# --------------------------------------------------------------------------------------------- USR-02
def test_the_user_payout_profile_skips_counterparty_checks_and_keeps_the_safety_checks(
    setup: tuple[DecisionOrg, TestClient], clock: FrozenClock
) -> None:
    d, api = setup
    register(api, d, "u-1")
    first = pay(api, d, "u-1", "50.00").json()
    assert first["status"] == "ESCALATED" and first["decision"]["outcome"] == "ESCALATE"
    assert checks(first)["new_wallet"]["reason"] == "NEW_WALLET"  # a new destination still escalates
    clock.advance(timedelta(days=8))
    p = pay(api, d, "u-1", "50.00").json()
    assert p["user_account_ref"] == "u-1" and p["counterparty_id"] is None
    assert p["decision"]["outcome"] == "EXECUTE" and p["status"] == "READY", p["decision"]
    cs = checks(p)
    for name in SKIPPED:
        assert cs[name]["result"] == "NOT_EVALUATED" and "user payout profile" in cs[name]["evidence"]["note"]
    assert cs["user_verified"]["result"] == "PASS"
    for name in KEPT:
        assert cs[name]["result"] in ("PASS", "NOT_EVALUATED") and name in cs, name
    assert cs["screening"]["result"] == "PASS" and cs["daily_cap_platform"]["result"] == "PASS"


def test_an_unverified_user_escalates_and_approval_reruns_policy(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    register(api, d, "u-2", verified=False)
    clock.advance(timedelta(days=8))
    p = pay(api, d, "u-2", "75.00").json()
    assert p["status"] == "ESCALATED" and p["decision"]["outcome"] == "ESCALATE"
    nv = checks(p)["user_verified"]
    assert nv["reason"] == "USER_NOT_VERIFIED" and nv["evidence"]["user_account_ref"] == "u-2"
    assert {c["reason"] for c in p["decision"]["checks"] if c["result"] == "ESCALATE"} == {
        "USER_NOT_VERIFIED"
    }
    reviewer = Actor(d.org.users[Role.REVIEWER], Role.REVIEWER.value)
    approve(
        engine,
        clock,
        case_id=p["exception"]["id"],
        org_id=d.id,
        actor=reviewer,
        reason="KYC confirmed by phone",
    )
    after = api.get(f"/v1/payment_intents/{p['id']}", headers=d.auth()).json()
    assert after["status"] == "READY" and after["decision"]["outcome"] == "EXECUTE"
    replay = api.get(f"/v1/payment_intents/{p['id']}/replay", headers=d.auth()).json()
    assert replay["match"] is True and replay["model_called"] is False


def test_an_approval_does_not_cover_a_changed_verification(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    register(api, d, "u-3")
    clock.advance(timedelta(days=8))
    p = pay(api, d, "u-3", "12000.00").json()  # above the auto limit: escalates
    assert checks(p)["auto_limit"]["result"] == "ESCALATE"
    register(api, d, "u-3", verified=False)  # the platform withdraws its KYC before the approval
    reviewer = Actor(d.org.users[Role.REVIEWER], Role.REVIEWER.value)
    approve(
        engine, clock, case_id=p["exception"]["id"], org_id=d.id, actor=reviewer, reason="Large but known"
    )
    after = api.get(f"/v1/payment_intents/{p['id']}", headers=d.auth()).json()
    assert after["status"] == "ESCALATED" and checks(after)["user_verified"]["reason"] == "USER_NOT_VERIFIED"


def test_a_replaced_destination_escalates_changed_details(
    setup: tuple[DecisionOrg, TestClient], clock: FrozenClock
) -> None:
    d, api = setup
    register(api, d, "u-4")
    clock.advance(timedelta(days=8))
    assert pay(api, d, "u-4", "40.00").json()["status"] == "READY"
    register(api, d, "u-4", address=OTHER)
    p = pay(api, d, "u-4", "40.00", address=OTHER).json()
    ch = checks(p)["changed_details"]
    assert p["status"] == "ESCALATED" and ch["reason"] == "CHANGED_DETAILS"
    assert ch["evidence"]["previous"] == WALLET and ch["evidence"]["current"] == OTHER


def test_screening_networks_and_resubmission_still_apply(
    setup: tuple[DecisionOrg, TestClient], clock: FrozenClock
) -> None:
    d, api = setup
    register(api, d, "u-5", address=SCREENED)
    clock.advance(timedelta(days=8))
    blocked = pay(api, d, "u-5", "10.00", address=SCREENED).json()
    assert blocked["status"] == "BLOCKED" and checks(blocked)["screening"]["reason"] == "SCREENING_HIT"
    register(api, d, "u-5", address=WALLET)
    again = pay(api, d, "u-5", "10.00").json()
    reasons = {c["reason"] for c in again["decision"]["checks"] if c["result"] == "ESCALATE"}
    assert {"RESUBMISSION_AFTER_BLOCK", "CHANGED_DETAILS"} <= reasons
    register(api, d, "u-6", destination={"kind": "evm_wallet", "network": "eth-sepolia", "address": OTHER})
    clock.advance(timedelta(days=8))
    eur = pay(
        api, d, "u-6", "10.00", currency="EUR",
        destination={"kind": "evm_wallet", "network": "eth-sepolia", "address": OTHER},
    ).json()  # fmt: skip
    assert eur["status"] == "BLOCKED" and checks(eur)["allowed_networks"]["reason"] == "NETWORK_NOT_ALLOWED"


def test_the_travel_rule_needs_the_users_name_above_the_threshold(
    setup: tuple[DecisionOrg, TestClient], clock: FrozenClock
) -> None:
    d, api = setup
    register(api, d, "u-8")
    clock.advance(timedelta(days=8))
    tr = checks(pay(api, d, "u-8", "1500.00").json())["travel_rule"]
    assert tr["reason"] == "TRAVEL_RULE_MISSING" and tr["evidence"]["missing"] == ["beneficiary.name"]
    register(api, d, "u-8", holder_name="Alan Example (fictional)")
    assert checks(pay(api, d, "u-8", "1500.00").json())["travel_rule"]["result"] == "PASS"


def test_user_payouts_count_against_the_platform_cap_only(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    register(api, d, "u-7", holder_name="Grace Example (fictional)")
    clock.advance(timedelta(days=8))
    # 9,000 a time: the per-counterparty cap (20,000) would stop the third; the platform cap (50,000) the sixth.
    statuses = [pay(api, d, "u-7", "9000.00").json() for _ in range(6)]
    assert [p["status"] for p in statuses[:5]] == ["READY"] * 5
    last = checks(statuses[5])
    assert last["daily_cap_platform"]["reason"] == "DAILY_CAP_PLATFORM"
    assert last["daily_cap_counterparty"]["result"] == "NOT_EVALUATED"
    with engine.connect() as c:
        scopes = dict(
            c.execute(text("SELECT scope, amount_minor FROM counters WHERE org_id=:o"), {"o": d.id}).all()
        )
    assert scopes == {"platform:USDC": 45_000_000_000}  # minor units; no counterparty row for a user payout


# --------------------------------------------------------------------------------------------- USR-03
def test_the_console_shows_the_user_account_and_the_profile(
    setup: tuple[DecisionOrg, TestClient], clock: FrozenClock
) -> None:
    d, api = setup
    register(api, d, "u-9", verified=False, holder_name="Mary Example (fictional)")
    clock.advance(timedelta(days=8))
    p = pay(api, d, "u-9", "30.00").json()
    case = p["exception"]["id"]
    detail = api.get(f"/v1/exceptions/{case}", headers=d.auth()).json()["raw_facts"]
    assert (
        detail["profile"] == "user"
        and detail["user_account_ref"] == "u-9"
        and detail["user_verified"] is False
    )
    login(api, d.org.users[Role.REVIEWER])
    for url in (
        "/console/payments",
        "/console/exceptions",
        f"/console/payments/{p['id']}",
        f"/console/exceptions/{case}",
    ):
        html = api.get(url).text
        assert "u-9" in html and "user payout profile" in html, url
    assert "Mary Example (fictional)" in api.get(f"/console/exceptions/{case}").text


# --------------------------------------------------------------------------------------------- USR-04
def test_new_organisations_are_seeded_with_fictional_users_as_test_values(
    setup: tuple[DecisionOrg, TestClient],
) -> None:
    d, api = setup  # the same registry seed every sandbox organisation gets (G-18)
    want = {"acct_u1001": "READY", "acct_u1002": "USER_NOT_VERIFIED", "acct_u1003": "CHANGED_DETAILS"}
    for ref, expect in want.items():
        u = api.get(f"/v1/user_accounts/{ref}", headers=d.auth()).json()
        assert "(fictional)" in u["holder_name"] and u["verified_set_by"] == "system:seed"
        dest = {k: u["destination"][k] for k in ("kind", "network")} | {
            "destination_id": u["destination"]["id"]
        }
        currency = "GBP" if dest["kind"] == "bank_account" else "USDC"
        p = pay(api, d, ref, "20.00", currency=currency, destination=dest).json()
        reasons = {c["reason"] for c in p["decision"]["checks"] if c["result"] == "ESCALATE"}
        assert (p["status"] == "READY") if expect == "READY" else (reasons == {expect}), (ref, p["decision"])
