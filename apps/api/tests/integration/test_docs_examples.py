"""P3 group 1: the docs' examples run against the sandbox API (DOC-01, DOC-02, SBX-01 criterion 1).

The quickstart's request body is read from the page itself and sent, so the page can't drift from the API.
The sandbox page's test values are checked against the code that applies them.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.dashboard import access
from detent.dashboard.access import Member
from detent.rails import simchain
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from test_dashboard_access import PASSWORD, _email, owner_of
from test_sandbox_rails import SETTINGS, drain, key_for

pytestmark = pytest.mark.db

DOCS = Path(__file__).resolve().parents[4] / "docs"


def _block(page: str, tag: str) -> str:
    m = re.search(r"```" + re.escape(tag) + r"\n(.*?)```", (DOCS / page).read_text(), re.S)
    assert m, f"{page}: no ```{tag} block"
    return m.group(1)


@pytest.fixture
def owner(engine: Engine, clock: FrozenClock) -> Member:
    with engine.begin() as conn:
        staff = access.create_staff(
            conn, clock, email=_email("staff"), display_name="Staff", password=PASSWORD
        )
    return owner_of(engine, clock, staff)[1]


@pytest.fixture
def api(engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    with TestClient(create_app(SETTINGS, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def _post(api: TestClient, auth: dict[str, str], body: dict[str, Any]) -> Any:
    r = api.post("/v1/payment_intents", json=body, headers={**auth, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 201, r.text
    return r.json()


def test_the_quickstart_request_works_as_written(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    body = json.loads(_block("quickstart.mdx", "json payout.json"))
    auth = key_for(engine, clock, owner)
    shown = json.loads(_block("quickstart.mdx", "json"))
    got = _post(api, auth, body)
    assert (got["status"], got["decision"]["outcome"], got["exception"]) == (
        shown["status"], shown["decision"]["outcome"], shown["exception"]
    )  # fmt: skip
    assert got["decision"]["policy_version"] == shown["decision"]["policy_version"]
    checks = {c["check"]: c["result"] for c in got["decision"]["checks"]}
    assert all(checks.get(c["check"]) == c["result"] for c in shown["decision"]["checks"]), checks

    # "In auto mode the same request returns READY, and the payout is sent on the simulated chain."
    with engine.begin() as conn:
        conn.execute(text("UPDATE organisations SET mode='auto' WHERE org_id=:o"), {"o": owner.org_id})
    ready = _post(api, auth, body)
    assert ready["status"] == "READY"
    drain(engine, clock, owner.org_id)
    assert api.get(f"/v1/payment_intents/{ready['id']}", headers=auth).json()["status"] == "CONFIRMED"


def test_the_quickstart_table_of_other_outcomes_holds(
    api: TestClient, owner: Member, engine: Engine, clock: FrozenClock
) -> None:
    auth = key_for(engine, clock, owner)
    base = json.loads(_block("quickstart.mdx", "json payout.json"))
    nova = {
        **base,
        "counterparty_id": "cpt_nova",
        "destination": {"kind": "evm_wallet", "network": "eth-sepolia", "destination_id": "dst_nova_eth"},
    }
    flagged = {**base, "counterparty_id": "cpt_flagged",
               "destination": {**base["destination"], "destination_id": "dst_flagged"}}  # fmt: skip
    shadowed = _post(api, auth, nova)  # shadow mode: decided and recorded, nothing else
    assert (shadowed["decision"]["outcome"], shadowed["status"], shadowed["exception"]) == (
        "ESCALATE",
        "SHADOWED",
        None,
    )
    reasons = {c.get("reason") for c in shadowed["decision"]["checks"]}
    assert {"KYB_PENDING", "NOT_ALLOWLISTED", "NEW_WALLET", "FIRST_PAYMENT"} <= reasons
    with engine.begin() as conn:
        conn.execute(text("UPDATE organisations SET mode='auto' WHERE org_id=:o"), {"o": owner.org_id})
    escalated = _post(api, auth, nova)
    assert escalated["status"] == "ESCALATED" and escalated["exception"]["deadline_at"]
    blocked = _post(api, auth, flagged)
    assert (blocked["decision"]["outcome"], blocked["status"]) == ("BLOCK", "BLOCKED")
    unknown = _post(api, auth, {**base, "amount": {"amount": "90.13", "currency": "USDC"}})
    drain(engine, clock, owner.org_id)
    assert api.get(f"/v1/payment_intents/{unknown['id']}", headers=auth).json()["status"] == "UNKNOWN"
    drain(engine, clock, owner.org_id, seconds=20, rounds=4)
    done = api.get(f"/v1/payment_intents/{unknown['id']}", headers=auth).json()
    assert done["status"] == "CONFIRMED" and len(done["attempts"]) == 1


def test_the_sandbox_page_lists_the_test_values_the_simulated_chain_applies() -> None:
    page = (DOCS / "sandbox.mdx").read_text()
    for cents in (simchain.TIMEOUT_CENTS, simchain.REVERT_CENTS):
        assert f"`.{cents}`" in page
    for text_ in ("0x000000000000000000000000000000000000dEaD", "MANDATE_AMOUNT_EXCEEDED", "NOT_ALLOWLISTED",
                  "FIRST_PAYMENT", "SCREENING_HIT", "`timeout`", "`rail_failure`", "`flagged_address`"):  # fmt: skip
        assert text_ in page, text_
