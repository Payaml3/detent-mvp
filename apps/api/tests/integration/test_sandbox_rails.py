"""P2 group 3a: the simulated chain rail, the sandbox test values, real test-network mode with the shared
faucet wallet's caps, and the sandbox controls page (RAL-11, SBX-01, SBX-02, SBX-03, DSH-07)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from conftest import make_settings
from detent.api.app import create_app
from detent.api.auth import issue_key
from detent.clock import FrozenClock
from detent.dashboard import access
from detent.dashboard.access import Member
from detent.domain.money import Money
from detent.domain.roles import Role
from detent.execution import send
from detent.rails.registry import SharedWalletCap, build_adapters
from detent.rails.simchain import SimChainAdapter, cents
from detent.runtime import Runtime
from detent.worker.loop import Worker
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from test_dashboard_access import PASSWORD, _email, audit_kinds, owner_of, sign_in, token_of

pytestmark = pytest.mark.db

PEPPER = "test-pepper-abcdef123456"
SETTINGS = make_settings("org_detent", api_key_pepper=SecretStr(PEPPER))
TESTNET = make_settings(
    "org_detent",
    api_key_pepper=SecretStr(PEPPER),
    base_sepolia_rpc_url="http://127.0.0.1:9",
    test_wallet_private_key_base=SecretStr("0x" + "11" * 32),
)


@pytest.fixture
def staff(engine: Engine, clock: FrozenClock) -> Member:
    with engine.begin() as conn:
        return access.create_staff(
            conn, clock, email=_email("staff"), display_name="Staff", password=PASSWORD
        )


@pytest.fixture
def owner(engine: Engine, clock: FrozenClock, staff: Member) -> Member:
    _org, member = owner_of(engine, clock, staff)
    with engine.begin() as conn:  # sandbox organisations start in shadow mode; these tests send
        conn.execute(text("UPDATE organisations SET mode='auto' WHERE org_id=:o"), {"o": member.org_id})
    return member


@pytest.fixture
def api(engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    with TestClient(create_app(SETTINGS, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def key_for(engine: Engine, clock: FrozenClock, m: Member) -> dict[str, str]:
    scopes = ["read", "intents:create", "exceptions:approve", "admin"]
    with engine.begin() as conn:
        return {"Authorization": "Bearer " + issue_key(conn, clock, m.org_id, m.id, scopes, PEPPER)}


def pay(api: TestClient, auth: dict[str, str], amount: str, cpt: str = "cpt_lumen", dst: str = "dst_lumen_base",
        *, switch: bool = True) -> dict[str, Any]:  # fmt: skip
    body = {
        "kind": "payout",
        "source": "platform",
        "counterparty_id": cpt,
        "destination": {"kind": "evm_wallet", "network": "base-sepolia", "destination_id": dst},
        "amount": {"amount": amount, "currency": "USDC"},
        "allow_network_switch": switch,
    }
    r = api.post("/v1/payment_intents", json=body, headers={**auth, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 201, r.text
    return dict(r.json())


def drain(engine: Engine, clock: FrozenClock, org_id: str, *, seconds: int = 0, rounds: int = 1) -> None:
    w = Worker(Runtime(SETTINGS, engine, clock), worker_id="test-sandbox", org_id=org_id)
    for _ in range(rounds):
        while w.run_one():
            pass
        clock.advance(timedelta(seconds=seconds))
    while w.run_one():
        pass


def state(engine: Engine, org_id: str, pid: str) -> tuple[str, list[Any], list[Any]]:
    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org_id, "p": pid}
        ).scalar_one()
        attempts = conn.execute(
            text(
                "SELECT attempt_no, rail_id, status, failure_class, tx_hash, explorer_url, raw_tx FROM attempts "
                "WHERE org_id=:o AND payment_id=:p ORDER BY attempt_no"
            ),
            {"o": org_id, "p": pid},
        ).all()
        chain = conn.execute(
            text(
                "SELECT rail_id, tx_hash, outcome, test_value FROM simchain_transfers WHERE org_id=:o ORDER BY seq"
            ),
            {"o": org_id},
        ).all()
    return str(status), list(attempts), list(chain)


# ------------------------------------------------------------------------------------------ RAL-11
def test_a_new_sandbox_organisation_pays_on_the_simulated_chain(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    with engine.connect() as conn:
        mode = conn.execute(
            text("SELECT sandbox_rails FROM organisations WHERE org_id=:o"), {"o": owner.org_id}
        ).scalar_one()
    assert mode == "simulated"
    adapters = build_adapters(SETTINGS, engine, owner.org_id, clock=clock)
    assert isinstance(adapters["base-sepolia"], SimChainAdapter) and isinstance(
        adapters["eth-sepolia"], SimChainAdapter
    )
    out = pay(api, key_for(engine, clock, owner), "90.00")
    drain(engine, clock, owner.org_id)
    status, attempts, chain = state(engine, owner.org_id, out["id"])
    assert status == "CONFIRMED"
    assert len(attempts) == 1 and attempts[0].rail_id == "base-sepolia" and attempts[0].explorer_url is None
    assert attempts[0].raw_tx.startswith("sim:")
    assert [(c.rail_id, c.tx_hash, c.outcome) for c in chain] == [
        ("base-sepolia", attempts[0].tx_hash, "confirmed")
    ]
    view = api.get(f"/v1/payment_intents/{out['id']}", headers=key_for(engine, clock, owner)).json()
    assert view["attempts"][0]["simulated"] is True and view["attempts"][0]["explorer_url"] is None


def test_the_simulated_chain_is_append_only_and_deduplicates_a_rebroadcast(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    out = pay(api, key_for(engine, clock, owner), "90.00")
    drain(engine, clock, owner.org_id)
    _status, attempts, chain = state(engine, owner.org_id, out["id"])
    adapter = SimChainAdapter(rail_id="base-sepolia", org_id=owner.org_id, engine=engine, clock=clock)
    from detent.rails.base import AttemptView

    a = attempts[0]
    view = AttemptView("att_x", out["id"], 1, "base-sepolia", "k", Money.parse("90.00", "USDC"), "0x" + "1" * 40,
                       None, a.raw_tx, a.tx_hash)  # fmt: skip
    adapter.submit(view)  # the same signed bytes again: still one transaction
    assert len(state(engine, owner.org_id, out["id"])[2]) == len(chain)
    with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
        conn.execute(text("DELETE FROM simchain_transfers WHERE org_id=:o"), {"o": owner.org_id})


def test_test_values_are_exact_cents() -> None:
    assert cents(Money.parse("10.13", "USDC")) == 13 and cents(Money.parse("10.42", "USDC")) == 42
    assert cents(Money.parse("10.1301", "USDC")) is None and cents(Money.parse("10.00", "USDC")) == 0
    assert cents(Money.parse("7.13", "GBP")) == 13


# ------------------------------------------------------------------------------------------ SBX-01
def test_point_13_times_out_to_unknown_then_confirms_without_a_resend(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    out = pay(api, key_for(engine, clock, owner), "90.13")
    drain(engine, clock, owner.org_id)
    status, attempts, chain = state(engine, owner.org_id, out["id"])
    assert status == "UNKNOWN" and attempts[0].status == "UNKNOWN"
    assert [c.test_value for c in chain] == ["timeout_after_forward"]
    drain(engine, clock, owner.org_id, seconds=20, rounds=4)
    status, attempts, chain = state(engine, owner.org_id, out["id"])
    assert status == "CONFIRMED"
    assert len(attempts) == 1 and attempts[0].status == "CONFIRMED"
    assert len(chain) == 1  # nothing was sent twice


def test_point_42_reverts_on_the_first_rail_and_fails_over_under_the_same_id(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    out = pay(api, key_for(engine, clock, owner), "90.42")
    drain(engine, clock, owner.org_id, seconds=5, rounds=3)
    status, attempts, chain = state(engine, owner.org_id, out["id"])
    assert status == "CONFIRMED"
    assert [(a.attempt_no, a.rail_id, a.status) for a in attempts] == [
        (1, "base-sepolia", "FAILED"),
        (2, "eth-sepolia", "CONFIRMED"),
    ]
    assert attempts[0].failure_class == "TECHNICAL_FINAL"
    assert [(c.rail_id, c.outcome) for c in chain] == [
        ("base-sepolia", "reverted"),
        ("eth-sepolia", "confirmed"),
    ]


def test_point_42_without_a_network_switch_ends_failed(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    out = pay(api, key_for(engine, clock, owner), "90.42", switch=False)
    drain(engine, clock, owner.org_id, seconds=5, rounds=3)
    status, attempts, _chain = state(engine, owner.org_id, out["id"])
    assert status in ("FAILED", "FAILED_FINAL") and len(attempts) == 1


def test_an_approver_can_allow_the_network_switch_and_it_is_audited(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    """RAL-07: without the intent's flag, a human approval of the switch lets the payment fail over."""
    from detent.audit.log import Actor
    from detent.exceptions.cases import approve

    with engine.begin() as conn:  # a first payment to the payee, so the payout escalates for a person
        conn.execute(
            text("UPDATE counterparties SET payment_count=0 WHERE org_id=:o AND id='cpt_lumen'"),
            {"o": owner.org_id},
        )
    out = pay(api, key_for(engine, clock, owner), "90.42", switch=False)
    assert out["status"] == "ESCALATED", out
    approve(
        engine,
        clock,
        case_id=out["exception"]["id"],
        org_id=owner.org_id,
        actor=Actor("usr_switch_approver", Role.REVIEWER.value),
        reason="Payee confirmed both wallets",
        allow_network_switch=True,
    )
    drain(engine, clock, owner.org_id, seconds=5, rounds=3)
    status, attempts, _chain = state(engine, owner.org_id, out["id"])
    assert status == "CONFIRMED"
    assert [(a.rail_id, a.status) for a in attempts] == [
        ("base-sepolia", "FAILED"),
        ("eth-sepolia", "CONFIRMED"),
    ]
    assert "payment.network_switch_approved" in audit_kinds(engine, owner.org_id)


def test_the_approval_api_takes_the_network_switch_flag(api: TestClient) -> None:
    from detent.api.openapi import build

    schema = build(api.app)  # type: ignore[arg-type]
    body = schema["paths"]["/v1/exceptions/{case_id}/approve"]["post"]["requestBody"]["content"]
    ref = body["application/json"]["schema"]["$ref"].rsplit("/", 1)[1]
    assert "allow_network_switch" in schema["components"]["schemas"][ref]["properties"]


def test_flagged_address_blocks_and_a_payee_off_the_allowlist_escalates(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    auth = key_for(engine, clock, owner)
    assert pay(api, auth, "90.00", "cpt_flagged", "dst_flagged")["status"] == "BLOCKED"
    nova = api.post(
        "/v1/payment_intents",
        json={
            "kind": "payout", "source": "platform", "counterparty_id": "cpt_nova",
            "destination": {"kind": "evm_wallet", "network": "eth-sepolia", "destination_id": "dst_nova_eth"},
            "amount": {"amount": "90.00", "currency": "USDC"},
        },
        headers={**auth, "Idempotency-Key": str(uuid.uuid4())},
    ).json()  # fmt: skip
    assert nova["status"] == "ESCALATED"


# ------------------------------------------------------------------------------------------ SBX-02, SBX-03
def _shared(engine: Engine, clock: FrozenClock, org_id: str, amount: str, cap: SharedWalletCap) -> str | None:
    try:
        with engine.begin() as conn:
            send._check_shared_wallet(
                conn, org_id, "base-sepolia", Money.parse(amount, "USDC"), clock.now().date().isoformat(), cap
            )
    except send._Hold as h:
        return h.reason
    return None


def test_the_shared_faucet_wallet_has_daily_caps_for_everyone_and_each_org(
    engine: Engine, clock: FrozenClock, staff: Member
) -> None:
    a, _ = owner_of(engine, clock, staff)
    b, _ = owner_of(engine, clock, staff)
    total = 10**9  # isolate this test from other organisations' counters today: a fresh scope per run
    cap = SharedWalletCap(daily_minor=total, org_daily_minor=40_000_000)  # 40 USDC each
    assert _shared(engine, clock, a, "30.00", cap) is None
    assert _shared(engine, clock, a, "20.00", cap) == "SHARED_WALLET_DAILY_CAP"  # over a's own cap
    assert _shared(engine, clock, b, "40.00", cap) is None
    with engine.connect() as conn:
        used = conn.execute(
            text("SELECT coalesce(sum(amount_minor), 0) FROM counters WHERE scope='faucet:base-sepolia' AND period=:p")
            .execution_options(cross_org="test"),
            {"p": clock.now().date().isoformat()},
        ).scalar_one()  # fmt: skip
    tight = SharedWalletCap(daily_minor=int(used) + 5_000_000, org_daily_minor=40_000_000)
    c, _ = owner_of(engine, clock, staff)
    assert _shared(engine, clock, c, "10.00", tight) == "SHARED_WALLET_DAILY_CAP"  # over everyone's cap
    assert _shared(engine, clock, c, "5.00", tight) is None
    clock.advance(timedelta(days=1))
    assert _shared(engine, clock, a, "30.00", cap) is None  # a new UTC day


def test_moving_to_real_test_networks_needs_configuration_and_no_payout_in_flight(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    from detent.dashboard import sandbox

    with pytest.raises(access.AccessError, match="not configured"), engine.begin() as conn:
        sandbox.set_rails_mode(conn, clock, SETTINGS, by=owner, mode="testnet")
    pay(api, key_for(engine, clock, owner), "90.13")
    drain(engine, clock, owner.org_id)  # UNKNOWN: in flight on the simulated chain
    with pytest.raises(access.AccessError, match="in flight"), engine.begin() as conn:
        sandbox.set_rails_mode(conn, clock, TESTNET, by=owner, mode="testnet")
    drain(engine, clock, owner.org_id, seconds=20, rounds=4)
    with engine.begin() as conn:
        assert sandbox.set_rails_mode(conn, clock, TESTNET, by=owner, mode="testnet") == "testnet"
    assert "sandbox.rails_mode_changed" in audit_kinds(engine, owner.org_id)
    with engine.begin() as conn:
        assert sandbox.set_rails_mode(conn, clock, TESTNET, by=owner, mode="simulated") == "simulated"


# ------------------------------------------------------------------------------------------ DSH-07
@pytest.fixture
def web(engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    with TestClient(create_app(SETTINGS, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def test_the_sandbox_page_forces_scenarios_and_shows_the_rails(
    web: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    assert sign_in(web, owner.email).status_code == 303
    page = web.get("/dashboard/sandbox").text
    assert "simulated chain" in page and "Timeout to UNKNOWN" in page and "Not configured" in page
    for scenario in ("flagged_address", "timeout", "rail_failure"):
        r = web.post(
            "/dashboard/sandbox/scenarios",
            data={"scenario": scenario, "csrf": token_of(web, "/dashboard/sandbox")},
            follow_redirects=False,
        )
        assert r.status_code == 303, r.text
    drain(engine, clock, owner.org_id, seconds=20, rounds=4)
    with engine.connect() as conn:
        rows = dict(
            conn.execute(
                text("SELECT reference, status FROM payment_intents WHERE org_id=:o"), {"o": owner.org_id}
            ).all()
        )
    assert rows == {
        "SANDBOX-FLAGGED_ADDRESS": "BLOCKED",
        "SANDBOX-TIMEOUT": "CONFIRMED",
        "SANDBOX-RAIL_FAILURE": "CONFIRMED",
    }
    page = web.get("/dashboard/sandbox").text
    assert "simulated" in page and "eth-sepolia: CONFIRMED" in page
    assert audit_kinds(engine, owner.org_id).count("sandbox.scenario_run") == 3
    bad = web.post(
        "/dashboard/sandbox/scenarios",
        data={"scenario": "drain", "csrf": token_of(web, "/dashboard/sandbox")},
    )
    assert bad.status_code == 422


def test_roles_without_sandbox_control_cannot_use_it(
    web: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    email = _email("rev")
    with engine.begin() as conn:
        token = access.invite(
            conn, clock, SETTINGS, org_id=owner.org_id, email=email, role=Role.REVIEWER, by=owner
        )
        access.accept_invite(conn, clock, token=token, display_name="Rae", password=PASSWORD)
    assert sign_in(web, email).status_code == 303
    assert web.get("/dashboard/sandbox").status_code == 403
    r = web.post(
        "/dashboard/sandbox/scenarios", data={"scenario": "timeout", "csrf": token_of(web, "/dashboard/")}
    )
    assert r.status_code == 403


# ------------------------------------------------------------------------------------------ LED-04 on simchain
def test_the_watcher_records_simulated_payouts_for_reconciliation(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    from detent.ledger.watchers import watch_evm

    out = pay(api, key_for(engine, clock, owner), "90.00")
    drain(engine, clock, owner.org_id)
    adapter = SimChainAdapter(rail_id="base-sepolia", org_id=owner.org_id, engine=engine, clock=clock)
    watch_evm(engine, clock, owner.org_id, "base-sepolia", adapter)
    _s, attempts, _c = state(engine, owner.org_id, out["id"])
    with engine.connect() as conn:
        rec = conn.execute(
            text("SELECT external_id, direction, amount_minor FROM rail_records WHERE org_id=:o AND rail_id='base-sepolia'"),
            {"o": owner.org_id},
        ).all()  # fmt: skip
    assert [(r.external_id, r.direction, r.amount_minor) for r in rec] == [
        (f"{attempts[0].tx_hash}:0", "out", 90_000_000)
    ]
