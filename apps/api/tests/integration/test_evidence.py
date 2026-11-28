"""AUD-03: an evidence pack for a payment or a date range, as JSON plus readable HTML and PDF."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from conftest import login, make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.audit import evidence
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.domain.roles import Role
from detent.exceptions.cases import approve
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

QUILL = {"destination_id": "dst_quill_acct", "kind": "bank_account", "network": "banksim-fps"}
HARBOR = {"destination_id": "dst_harbor_iban", "kind": "bank_account", "network": "banksim-sepa-inst"}
TX = "0x" + "ab" * 32


@pytest.fixture
def setup(engine: Engine, clock: FrozenClock) -> Iterator[tuple[DecisionOrg, TestClient]]:
    d = setup_decision_org(engine, clock)
    s = make_settings(d.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield d, c


def create(api: TestClient, d: DecisionOrg, body: dict[str, object]) -> dict[str, object]:
    r = api.post("/v1/payment_intents", json=body, headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 201, r.text
    return dict(r.json())


def approved_and_sent(api: TestClient, d: DecisionOrg, engine: Engine, clock: FrozenClock) -> str:
    """An escalated payment a reviewer approves, then an attempt with a transaction hash."""
    p = create(api, d, payout("cpt_quill", "820.00", "GBP", QUILL, reference="INV-Q-7"))
    assert p["status"] == "ESCALATED"
    case = p["exception"]["id"]  # type: ignore[index]
    reviewer = Actor(d.org.users[Role.REVIEWER], Role.REVIEWER.value)
    approve(
        engine, clock, case_id=case, org_id=d.id, actor=reviewer, reason="Called Quill to confirm new details"
    )
    pid = str(p["id"])
    with engine.begin() as c:
        from detent.rails.registry import install_rail

        install_rail(c, d.id, rail_id="banksim-fps", kind="banksim", network="banksim-fps", currency="GBP")
        c.execute(
            text(
                "INSERT INTO attempts (id, org_id, payment_id, attempt_no, rail_id, status, idempotency_key, tx_hash, "
                "explorer_url, created_at) VALUES (:id, :o, :p, 1, 'banksim-fps', 'SUBMITTED', :k, :tx, :u, :t)"
            ),
            {
                "id": f"att_{uuid.uuid4().hex}", "o": d.id, "p": pid, "k": f"{pid}:1", "tx": TX,
                "u": f"https://sepolia.basescan.org/tx/{TX}", "t": clock.now(),
            },
        )  # fmt: skip
    return pid


def test_pack_for_one_payment(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = approved_and_sent(api, d, engine, clock)
    with engine.connect() as c:
        pack = evidence.build(c, d.id, now=clock.now(), payment_id=pid)
    assert pack["hash_chain"]["ok"] is True and pack["hash_chain"]["events"] > 0
    (p,) = pack["payments"]
    assert p["inputs"]["amount"] == "820.00 GBP" and p["inputs"]["reference"] == "INV-Q-7"
    first, *rest = p["decisions"]
    assert first["outcome"] == "ESCALATE" and first["rule_version"] == 1 and first["checks"]
    assert rest and rest[-1]["outcome"] == "EXECUTE"  # approval re-runs policy (invariant 8)
    (a,) = p["approvals"]
    assert a["resolution"] == "approved" and a["by"] == d.org.users[Role.REVIEWER]
    assert a["reason"] == "Called Quill to confirm new details"
    assert [s["to"] for s in p["state_changes"]][:2] == ["ESCALATED", "READY"]
    (att,) = p["attempts"]
    assert att["tx_hash"] == TX and att["explorer_url"].endswith(TX)
    json.dumps(pack)  # the pack is plain JSON


def test_pack_for_a_range_and_bad_scopes(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    a = str(create(api, d, payout("cpt_harbor", "2000.00", "EUR", HARBOR, reference="INV-H-1"))["id"])
    clock.advance(timedelta(days=2))
    b = str(create(api, d, payout("cpt_harbor", "2100.00", "EUR", HARBOR, reference="INV-H-2"))["id"])
    with engine.connect() as c:
        both = evidence.build(
            c, d.id, now=clock.now(), start=clock.now() - timedelta(days=3), end=clock.now() + timedelta(1)
        )
        last = evidence.build(
            c, d.id, now=clock.now(), start=clock.now() - timedelta(days=1), end=clock.now() + timedelta(1)
        )
        with pytest.raises(evidence.EvidenceError, match="date range"):
            evidence.build(c, d.id, now=clock.now(), start=clock.now())
        with pytest.raises(evidence.EvidenceError, match="no payment"):
            evidence.build(c, d.id, now=clock.now(), payment_id="pay_missing")
    assert [p["id"] for p in both["payments"]] == [a, b]
    assert [p["id"] for p in last["payments"]] == [b]


def test_a_broken_chain_is_reported(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = str(create(api, d, payout("cpt_harbor", "2000.00", "EUR", HARBOR, reference="INV-H-1"))["id"])
    with engine.begin() as c:  # simulate tampering: the trigger blocks edits, so move the head instead
        c.execute(text("UPDATE audit_heads SET hash='0' WHERE org_id=:o"), {"o": d.id})
    with engine.connect() as c:
        pack = evidence.build(c, d.id, now=clock.now(), payment_id=pid)
    assert pack["hash_chain"]["ok"] is False and "head" in pack["hash_chain"]["problem"]
    assert any("BROKEN" in line for line in evidence.as_lines(pack))


def test_console_exports_json_html_and_pdf(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    pid = approved_and_sent(api, d, engine, clock)
    login(api, d.org.users[Role.AUDITOR])
    page = api.get("/console/audit").text
    assert (
        "Hash chain" in page
        and "Verified" in page
        and "Evidence export" in page
        and "payment.status_changed" in page
    )
    j = api.get(f"/console/audit/evidence.json?payment_id={pid}")
    assert j.status_code == 200 and j.json()["payments"][0]["id"] == pid
    assert f"evidence-{pid}.json" in j.headers["content-disposition"]
    h = api.get(f"/console/audit/evidence.html?payment_id={pid}")
    assert h.status_code == 200 and "attachment" in h.headers["content-disposition"]
    for want in ("Evidence pack", "verified", "v1", "approved", "ESCALATED to READY", TX, "basescan.org"):
        assert want in h.text, want
    p = api.get(f"/console/audit/evidence.pdf?payment_id={pid}")
    assert (
        p.status_code == 200
        and p.content.startswith(b"%PDF-1.4")
        and p.headers["content-type"] == "application/pdf"
    )
    r = api.get(f"/console/audit/evidence.json?start={clock.now().date()}&end={clock.now().date()}")
    assert [x["id"] for x in r.json()["payments"]] == [pid]
    assert api.get("/console/audit/evidence.json").status_code == 422
