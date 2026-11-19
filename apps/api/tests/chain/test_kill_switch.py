"""EXE-08 and G-15 (D-28): the kill switch stops a batch; only the payments lead releases it; held
payments re-run the rules on release; UNKNOWN keeps resolving read-only."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest
from chain_helpers import ChainOrg, balance, needs_chain, setup_chain_org
from conftest import login, make_settings
from decision_helpers import PEPPER
from detent import devchain
from detent.api.app import create_app
from detent.api.auth import issue_key
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.execution.kill_switch import engage, release
from detent.execution.resolver import resolve_unknown
from detent.execution.send import send_payment
from detent.policy.screening import MockScreening
from detent.rails.evm import EvmAdapter
from fastapi.testclient import TestClient
from faultproxy.app import create_app as proxy_app
from pydantic import SecretStr
from servers import fault, serve
from sqlalchemy import Engine, text

pytestmark = [pytest.mark.db, *needs_chain]


@pytest.fixture
def co(engine: Engine, clock: FrozenClock, chain: devchain.LocalChain) -> ChainOrg:
    return setup_chain_org(engine, clock, chain)


def send(engine: Engine, clock: FrozenClock, co: ChainOrg, pid: str) -> str:
    return send_payment(
        engine, clock, co.adapters, org_id=co.id, payment_id=pid, screening=MockScreening.from_fixture()
    ).value


def statuses(engine: Engine, org: str, pids: list[str]) -> list[str]:
    with engine.connect() as c:
        return [
            str(
                c.execute(
                    text("SELECT status FROM payment_intents WHERE org_id=:o AND id=:p"), {"o": org, "p": p}
                ).scalar()
            )
            for p in pids
        ]


def actor(co: ChainOrg, role: Role) -> Actor:
    return Actor(co.d.org.users[role], role.value)


def test_kill_switch_stops_a_batch_and_release_resumes_it(
    engine: Engine, clock: FrozenClock, co: ChainOrg
) -> None:
    pids = [co.payout(engine, clock, f"{i + 1}.00", key=f"b{i}") for i in range(5)]
    before = balance(co.chain, co.payee)
    engage(engine, clock, org_id=co.id, actor=actor(co, Role.ONCALL))
    assert statuses(engine, co.id, pids) == ["HELD"] * 5
    assert [send(engine, clock, co, p) for p in pids] == ["HELD"] * 5
    assert balance(co.chain, co.payee) == before
    with pytest.raises(PermissionError):  # on-call engaged it, but only the payments lead releases
        release(engine, clock, org_id=co.id, actor=actor(co, Role.ONCALL))
    resumed = release(engine, clock, org_id=co.id, actor=actor(co, Role.PAYMENTS_LEAD))
    assert sorted(resumed["READY"]) == sorted(pids)
    assert statuses(engine, co.id, pids) == ["READY"] * 5
    assert [send(engine, clock, co, p) for p in pids] == ["CONFIRMED"] * 5
    assert balance(co.chain, co.payee) - before == 15_000_000
    with engine.connect() as c:
        kinds = (
            c.execute(
                text(
                    "SELECT kind FROM audit_events WHERE org_id=:o AND kind LIKE 'kill_switch.%' ORDER BY seq"
                ),
                {"o": co.id},
            )
            .scalars()
            .all()
        )
        reruns = c.execute(
            text(
                "SELECT count(*) FROM decisions WHERE org_id=:o AND inputs_snapshot->>'rerun_reason' = 'kill switch released'"
            ),
            {"o": co.id},
        ).scalar()
    assert kinds == ["kill_switch.engaged", "kill_switch.released"] and reruns == 5


def test_release_reruns_the_rules_for_each_held_payment(
    engine: Engine, clock: FrozenClock, co: ChainOrg
) -> None:
    pid = co.payout(engine, clock, "10.00")
    engage(engine, clock, org_id=co.id, actor=actor(co, Role.PAYMENTS_LEAD))
    with engine.begin() as c:  # while held, the payee is put on the screening list's blocked KYB
        c.execute(
            text("UPDATE counterparties SET kyb_status='failed' WHERE org_id=:o AND id='cpt_local'"),
            {"o": co.id},
        )
    resumed = release(engine, clock, org_id=co.id, actor=actor(co, Role.PAYMENTS_LEAD))
    assert resumed["BLOCKED"] == [pid] and statuses(engine, co.id, [pid]) == ["BLOCKED"]


def test_unknown_keeps_resolving_read_only(
    engine: Engine, clock: FrozenClock, co: ChainOrg, chain: devchain.LocalChain
) -> None:
    with serve(proxy_app(chain.rpc_url, hold_seconds=2.0)) as url:
        a = EvmAdapter(
            rail_id="local-evm",
            rpc_url=url,
            expected_chain_id=31337,
            token_address=chain.usdc_address,
            signer=co.adapter._signer,
            confirmations=1,
            timeout_seconds=1.0,
        )  # type: ignore[attr-defined]
        c2 = dataclasses.replace(co, adapter=a, adapters={"local-evm": a})
        p1, p2 = c2.payout(engine, clock, "11.00", key="u1"), c2.payout(engine, clock, "12.00", key="u2")
        fault(url, "eth_sendRawTransaction", "timeout_after_forward")
        fault(url, "eth_sendRawTransaction", "timeout_before_forward")
        assert send(engine, clock, c2, p1) == "UNKNOWN"  # reached the chain
        assert send(engine, clock, c2, p2) == "UNKNOWN"  # never left
        engage(engine, clock, org_id=co.id, actor=actor(co, Role.ONCALL))
        assert resolve_unknown(engine, clock, c2.adapters, org_id=co.id, payment_id=p1).value == "CONFIRMED"
        assert (
            resolve_unknown(engine, clock, c2.adapters, org_id=co.id, payment_id=p2).value == "UNKNOWN"
        )  # no re-broadcast
        with engine.connect() as c:
            n = c.execute(
                text("SELECT count(*) FROM audit_events WHERE org_id=:o AND kind='attempt.rebroadcast'"),
                {"o": co.id},
            ).scalar()
        assert n == 0


@pytest.fixture
def api(
    co: ChainOrg, engine: Engine, clock: FrozenClock
) -> Iterator[tuple[TestClient, dict[str, str], dict[str, str]]]:
    with engine.begin() as c:
        oncall = issue_key(c, clock, co.id, co.d.org.users[Role.ONCALL], ["admin"], PEPPER)
        lead = issue_key(c, clock, co.id, co.d.org.users[Role.PAYMENTS_LEAD], ["admin"], PEPPER)
    app = create_app(
        make_settings(co.id, api_key_pepper=SecretStr(PEPPER)),
        engine=engine,
        clock=clock,
        configure_logging=False,
    )
    with TestClient(app) as client:
        yield client, {"Authorization": f"Bearer {oncall}"}, {"Authorization": f"Bearer {lead}"}


def test_api_engage_and_release(api: tuple[TestClient, dict[str, str], dict[str, str]], co: ChainOrg) -> None:
    client, oncall, lead = api
    assert client.post("/v1/kill_switch", headers=oncall).json()["engaged"] is True
    assert (
        client.post("/v1/kill_switch", headers=co.d.auth() | {}).status_code == 200
    )  # the payments lead may engage too
    r = client.delete("/v1/kill_switch", headers=oncall)
    assert r.status_code == 403 and r.json()["error"]["code"] == "insufficient_role"
    assert client.delete("/v1/kill_switch", headers=lead).json()["engaged"] is False


def test_console_banner_and_buttons(
    api: tuple[TestClient, dict[str, str], dict[str, str]], co: ChainOrg
) -> None:
    client, *_ = api
    login(client, co.d.org.users[Role.ONCALL])
    assert client.post("/console/kill_switch/engage", follow_redirects=False).status_code == 303
    for path in ("/console/", "/console/payments", "/console/exceptions"):
        assert "Kill switch engaged" in client.get(path).text
    assert client.post("/console/kill_switch/release", follow_redirects=False).status_code == 403
    login(client, co.d.org.users[Role.PAYMENTS_LEAD])
    assert client.post("/console/kill_switch/release", follow_redirects=False).status_code == 303
    assert "Kill switch engaged" not in client.get("/console/").text
