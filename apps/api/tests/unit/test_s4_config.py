"""S4 configuration checks: the resolver's poll schedule (EXE-06), fault injection off in demo mode
(RAL-05), and the Ethereum Sepolia rail's own profile (RAL-03)."""

from __future__ import annotations

from datetime import timedelta

import yaml
from detent.execution.resolver import next_poll_delay
from detent.settings import REPO_ROOT
from fastapi.testclient import TestClient
from faultproxy.app import create_app as proxy_app


def test_resolver_polls_on_the_spec_06_schedule() -> None:
    assert [next_poll_delay(i) for i in range(6)] == [timedelta(seconds=s) for s in (5, 15, 30, 60, 120, 120)]


def test_faults_are_refused_in_demo_mode_unless_the_scenario_runner_asks() -> None:
    c = TestClient(proxy_app("http://127.0.0.1:9", demo_mode=True))
    body = {"match": "eth_sendRawTransaction", "fault": "timeout_after_forward"}
    assert c.post("/__faults", json=body).status_code == 403
    assert c.post("/__faults", json=body, headers={"X-Dekernai-Scenario-Runner": "1"}).status_code == 201
    assert (
        TestClient(proxy_app("http://127.0.0.1:9"))
        .post("/__faults", json={**body, "fault": "nope"})
        .status_code
        == 422
    )


def test_eth_sepolia_has_its_own_fee_profile_and_threshold() -> None:
    rails = {r["id"]: r for r in yaml.safe_load((REPO_ROOT / "fixtures" / "rails.yaml").read_text())["rails"]}
    base, eth = rails["base-sepolia"], rails["eth-sepolia"]
    assert (base["kind"], eth["kind"]) == ("evm", "evm")  # one EvmAdapter class serves both (RAL-03)
    assert eth["chain_id"] == 11155111 and eth["confirmations"] == 2 and base["confirmations"] == 3
    assert eth["est_fee_minor"] > base["est_fee_minor"]  # the higher fee profile routing scores against
