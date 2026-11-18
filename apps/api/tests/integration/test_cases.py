"""EXC-01, EXC-04, EXC-05, EXC-07, POL-06: cases, approval with a policy re-run, and finality of blocks."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from conftest import make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.exceptions.cases import (
    AlreadyResolved,
    NotPermitted,
    PaymentBlocked,
    SelfApproval,
    approve,
    reject,
)
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

QUILL = {"destination_id": "dst_quill_acct", "kind": "bank_account", "network": "banksim-fps"}


@pytest.fixture
def dorg(engine: Engine, clock: FrozenClock) -> DecisionOrg:
    return setup_decision_org(engine, clock)


@pytest.fixture
def api(dorg: DecisionOrg, engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    s = make_settings(dorg.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def create(api: TestClient, d: DecisionOrg, body: dict[str, object]) -> dict[str, object]:
    r = api.post("/v1/payment_intents", json=body, headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 201, r.text
    return dict(r.json())


def bluefin(d: DecisionOrg, amount: str = "18500.00") -> dict[str, object]:
    dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": d.wallets["WALLET_BLUEFIN_BASE"]}
    return payout("cpt_bluefin", amount, "USDC", dest, reference="INV-2026-0142")


def case_row(engine: Engine, org: str, pid: str) -> object:
    with engine.connect() as c:
        return c.execute(
            text("SELECT * FROM exception_cases WHERE org_id=:o AND payment_id=:p ORDER BY created_at, id"),
            {"o": org, "p": pid},
        ).all()


def reviewer(d: DecisionOrg) -> Actor:
    return Actor(d.org.users[Role.REVIEWER], Role.REVIEWER.value)


# ------------------------------------------------------------------------------------ EXC-01, EXC-07
def test_escalation_opens_a_case_with_owner_tier_and_deadline(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    j = create(api, dorg, bluefin(dorg))
    [case] = case_row(engine, dorg.id, str(j["id"]))  # type: ignore[misc]
    assert case.status == "OPEN" and case.type == "payout"
    assert set(case.reasons) == {"FIRST_PAYMENT", "ABOVE_AUTO_LIMIT"}
    assert (
        case.owner_id == dorg.org.users[Role.REVIEWER]
        and case.backup_owner_id == dorg.org.users[Role.BACKUP_OWNER]
    )
    assert case.tier == 1 and case.deadline_at == clock.now() + timedelta(
        hours=2
    )  # above the auto limit (C-07)
    assert j["exception"] == {
        "id": case.id,
        "owner": case.owner_id,
        "deadline_at": (clock.now() + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
    }
    with engine.connect() as c:
        box = c.execute(
            text("SELECT channel, recipient, template FROM outbox WHERE org_id=:o"), {"o": dorg.id}
        ).all()
        ev = (
            c.execute(
                text("SELECT kind FROM audit_events WHERE org_id=:o AND subject_id=:s"),
                {"o": dorg.id, "s": case.id},
            )
            .scalars()
            .all()
        )
    assert ("email_mock", f"{case.owner_id}@test.invalid", "case.assigned") in [tuple(b) for b in box]
    assert "case.opened" in ev


def test_other_payout_gets_tier_2_and_four_hours(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    j = create(api, dorg, payout("cpt_quill", "500.00", "GBP", QUILL))
    [case] = case_row(engine, dorg.id, str(j["id"]))  # type: ignore[misc]
    assert case.tier == 2 and case.deadline_at == clock.now() + timedelta(hours=4)


def test_owner_is_the_reviewer_with_fewest_open_cases(engine: Engine, clock: FrozenClock) -> None:  # G-24
    d = setup_decision_org(engine, clock)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO users (id, org_id, email, display_name, role, created_at) VALUES "
                "(:id, :o, :e, 'Second reviewer', 'reviewer', :t)"
            ),
            {
                "id": f"usr_{d.id[4:]}_rv2",
                "o": d.id,
                "e": f"rv2{d.id}@test.invalid",
                "t": clock.now() + timedelta(seconds=1),
            },
        )
    s = make_settings(d.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        owners = [
            case_row(
                engine, d.id, str(create(c, d, payout("cpt_quill", f"{10 + i}.00", "GBP", QUILL))["id"])
            )[0].owner_id  # type: ignore[index]
            for i in range(4)
        ]
    assert owners.count(d.org.users[Role.REVIEWER]) == 2 and owners.count(f"usr_{d.id[4:]}_rv2") == 2


# ------------------------------------------------------------------------------------ EXC-04
def test_approval_reruns_policy_and_proceeds(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pid = str(create(api, dorg, bluefin(dorg))["id"])
    [case] = case_row(engine, dorg.id, pid)  # type: ignore[misc]
    clock.advance(timedelta(minutes=10))
    res = approve(
        engine,
        clock,
        case_id=case.id,
        org_id=dorg.id,
        actor=reviewer(dorg),
        reason="Invoice checked against PO-77",
    )
    assert res.payment_status == "READY"
    with engine.connect() as c:
        dec = c.execute(
            text(
                "SELECT outcome, approved_reasons FROM decisions WHERE org_id=:o AND payment_id=:p "
                "ORDER BY decided_at DESC LIMIT 1"
            ),
            {"o": dorg.id, "p": pid},
        ).one()
        case2 = c.execute(
            text(
                "SELECT status, resolution, resolution_reason, resolved_by FROM exception_cases WHERE org_id=:o AND id=:i"
            ),
            {"o": dorg.id, "i": case.id},
        ).one()
        job = c.execute(
            text("SELECT count(*) FROM jobs WHERE org_id=:o AND payment_id=:p AND kind='payment.send'"),
            {"o": dorg.id, "p": pid},
        ).scalar()
    assert dec.outcome == "EXECUTE" and set(dec.approved_reasons) == {"FIRST_PAYMENT", "ABOVE_AUTO_LIMIT"}
    assert tuple(case2) == ("RESOLVED", "approved", "Invoice checked against PO-77", reviewer(dorg).id)
    assert job == 1


def test_changed_facts_after_escalation_open_a_new_case(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pid = str(create(api, dorg, bluefin(dorg))["id"])
    [case] = case_row(engine, dorg.id, pid)  # type: ignore[misc]
    with engine.begin() as c:  # the payee's wallet is changed while the case waits
        c.execute(
            text(
                "UPDATE destinations SET last_changed_at=:t, last_changed_by='usr_x' WHERE org_id=:o AND id='dst_bluefin_base'"
            ),
            {"o": dorg.id, "t": clock.now()},
        )
    res = approve(engine, clock, case_id=case.id, org_id=dorg.id, actor=reviewer(dorg), reason="ok")
    assert res.payment_status == "ESCALATED" and res.new_case_id
    cases = case_row(engine, dorg.id, pid)
    by_status = {c.status: c for c in cases}  # type: ignore[attr-defined]
    assert by_status["RESOLVED"].resolution == "superseded" and by_status["OPEN"].id == res.new_case_id
    assert "CHANGED_DETAILS" in by_status["OPEN"].reasons


def test_a_new_block_on_rerun_stays_blocked(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pid = str(create(api, dorg, bluefin(dorg))["id"])
    [case] = case_row(engine, dorg.id, pid)  # type: ignore[misc]
    with engine.begin() as c:
        c.execute(
            text("UPDATE counterparties SET kyb_status='failed' WHERE org_id=:o AND id='cpt_bluefin'"),
            {"o": dorg.id},
        )
    res = approve(engine, clock, case_id=case.id, org_id=dorg.id, actor=reviewer(dorg), reason="ok")
    assert res.payment_status == "BLOCKED"
    with engine.connect() as c:
        jobs = c.execute(
            text("SELECT count(*) FROM jobs WHERE org_id=:o AND payment_id=:p"), {"o": dorg.id, "p": pid}
        ).scalar()
    assert jobs == 0


def test_reject_is_terminal_and_needs_a_reason(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pid = str(create(api, dorg, bluefin(dorg))["id"])
    [case] = case_row(engine, dorg.id, pid)  # type: ignore[misc]
    with pytest.raises(ValueError, match="reason"):
        reject(engine, clock, case_id=case.id, org_id=dorg.id, actor=reviewer(dorg), reason="  ")
    with pytest.raises(ValueError, match="reason"):
        approve(engine, clock, case_id=case.id, org_id=dorg.id, actor=reviewer(dorg), reason="")
    assert (
        reject(
            engine, clock, case_id=case.id, org_id=dorg.id, actor=reviewer(dorg), reason="Not our supplier"
        ).payment_status
        == "REJECTED"
    )


def test_initiator_cannot_approve(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pid = str(create(api, dorg, bluefin(dorg))["id"])  # created with the payments lead's key (G-08)
    [case] = case_row(engine, dorg.id, pid)  # type: ignore[misc]
    lead = Actor(dorg.org.users[Role.PAYMENTS_LEAD], Role.PAYMENTS_LEAD.value)
    with pytest.raises(SelfApproval):
        approve(engine, clock, case_id=case.id, org_id=dorg.id, actor=lead, reason="mine")


def test_only_permitted_roles_approve(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:  # G-06
    pid = str(create(api, dorg, bluefin(dorg))["id"])
    [case] = case_row(engine, dorg.id, pid)  # type: ignore[misc]
    for role in (Role.COMPLIANCE_LEAD, Role.ONCALL, Role.ADMIN):
        with pytest.raises(NotPermitted):
            approve(
                engine,
                clock,
                case_id=case.id,
                org_id=dorg.id,
                actor=Actor(dorg.org.users[role], role.value),
                reason="x",
            )


# ------------------------------------------------------------------------------------ EXC-05
def test_parallel_approvals_one_wins(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pid = str(create(api, dorg, bluefin(dorg))["id"])
    [case] = case_row(engine, dorg.id, pid)  # type: ignore[misc]
    actors = [reviewer(dorg), Actor(dorg.org.users[Role.BACKUP_OWNER], Role.BACKUP_OWNER.value)] * 4

    def one(a: Actor) -> str:
        try:
            approve(engine, clock, case_id=case.id, org_id=dorg.id, actor=a, reason="ok")
            return "ok"
        except AlreadyResolved:
            return "409"

    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(one, actors))
    assert results.count("ok") == 1 and results.count("409") == 7
    with engine.connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM decisions WHERE org_id=:o AND payment_id=:p"), {"o": dorg.id, "p": pid}
        ).scalar()
    assert n == 2


def test_parallel_approvals_through_api_and_console(engine: Engine, clock: FrozenClock) -> None:
    from conftest import login

    d = setup_decision_org(engine, clock)
    # A second key, for the reviewer, approves through the API while the backup owner uses the console.
    from detent.api.auth import issue_key

    with engine.begin() as c:
        rkey = issue_key(c, clock, d.id, d.org.users[Role.REVIEWER], ["read", "exceptions:approve"], PEPPER)
    app = create_app(
        make_settings(d.id, api_key_pepper=SecretStr(PEPPER)),
        engine=engine,
        clock=clock,
        configure_logging=False,
    )
    with TestClient(app) as c:
        pid = str(create(c, d, bluefin(d))["id"])
    [case] = case_row(engine, d.id, pid)  # type: ignore[misc]

    def via_api(_: int) -> int:
        with TestClient(app) as c:
            return c.post(
                f"/v1/exceptions/{case.id}/approve",
                json={"reason": "api"},  # type: ignore[attr-defined]
                headers={"Authorization": f"Bearer {rkey}"},
            ).status_code

    def via_console(_: int) -> int:
        with TestClient(app) as c:
            login(c, d.org.users[Role.BACKUP_OWNER])
            r = c.post(
                f"/console/exceptions/{case.id}/approve", data={"reason": "console"}, follow_redirects=False
            )  # type: ignore[attr-defined]
            return 200 if r.status_code == 303 else r.status_code

    with ThreadPoolExecutor(6) as ex:
        codes = list(ex.map(lambda i: via_api(i) if i % 2 else via_console(i), range(6)))
    assert codes.count(200) == 1 and codes.count(409) == 5, codes


# ------------------------------------------------------------------------------------ POL-06
def test_blocked_payment_cannot_be_approved_or_sent(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pid = str(create(api, dorg, bluefin(dorg))["id"])
    [case] = case_row(engine, dorg.id, pid)  # type: ignore[misc]
    with engine.begin() as c:  # the payment is blocked by another path while its case is still open
        c.execute(
            text("UPDATE payment_intents SET status='BLOCKED' WHERE org_id=:o AND id=:p"),
            {"o": dorg.id, "p": pid},
        )
    with pytest.raises(PaymentBlocked):
        approve(engine, clock, case_id=case.id, org_id=dorg.id, actor=reviewer(dorg), reason="ok")
    with engine.connect() as c:
        st = c.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": dorg.id, "p": pid}
        ).scalar()
    assert st == "BLOCKED"


def test_api_approval_errors(api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock) -> None:
    from detent.api.auth import issue_key

    with engine.begin() as c:
        rkey = issue_key(
            c, clock, dorg.id, dorg.org.users[Role.REVIEWER], ["read", "exceptions:approve"], PEPPER
        )
    rv = {"Authorization": f"Bearer {rkey}"}
    pid = str(create(api, dorg, bluefin(dorg))["id"])
    [case] = case_row(engine, dorg.id, pid)  # type: ignore[misc]
    assert api.post(f"/v1/exceptions/{case.id}/approve", json={"reason": ""}, headers=rv).status_code == 422  # type: ignore[attr-defined]
    me = api.post(f"/v1/exceptions/{case.id}/approve", json={"reason": "x"}, headers=dorg.auth())  # type: ignore[attr-defined]
    assert me.status_code == 403 and me.json()["error"]["code"] == "self_approval_forbidden"
    assert api.post(f"/v1/exceptions/{case.id}/approve", json={"reason": "ok"}, headers=rv).status_code == 200  # type: ignore[attr-defined]
    again = api.post(f"/v1/exceptions/{case.id}/reject", json={"reason": "late"}, headers=rv)  # type: ignore[attr-defined]
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_resolved"
    assert api.post("/v1/exceptions/exc_nope/approve", json={"reason": "x"}, headers=rv).status_code == 404


def test_api_approving_a_blocked_payment_is_409(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    from detent.api.auth import issue_key

    with engine.begin() as c:
        rkey = issue_key(c, clock, dorg.id, dorg.org.users[Role.REVIEWER], ["exceptions:approve"], PEPPER)
    pid = str(create(api, dorg, bluefin(dorg))["id"])
    [case] = case_row(engine, dorg.id, pid)  # type: ignore[misc]
    with engine.begin() as c:
        c.execute(
            text("UPDATE payment_intents SET status='BLOCKED' WHERE org_id=:o AND id=:p"),
            {"o": dorg.id, "p": pid},
        )
    r = api.post(
        f"/v1/exceptions/{case.id}/approve", json={"reason": "x"}, headers={"Authorization": f"Bearer {rkey}"}
    )  # type: ignore[attr-defined]
    assert r.status_code == 409 and r.json()["error"]["code"] == "payment_blocked"
