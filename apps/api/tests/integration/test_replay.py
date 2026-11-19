"""AUD-02: replay any payment from its stored inputs and rule version; a mismatch raises an alert."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

import pytest
import yaml
from conftest import make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.audit.replay import replay_payment
from detent.clock import FrozenClock
from detent.domain.ids import Prefix, new_id
from detent.domain.roles import Role
from detent.exceptions.cases import approve
from detent.policy.changes import approve_draft, propose_draft
from detent.settings import REPO_ROOT
from fastapi.testclient import TestClient
from policy_helpers import v2
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.db
BATCH = yaml.safe_load((REPO_ROOT / "fixtures" / "batches" / "demo-batch-20.yaml").read_text())
DEST = {
    "cpt_harbor": {
        "destination_id": "dst_harbor_iban",
        "kind": "bank_account",
        "network": "banksim-sepa-inst",
    },
    "cpt_quill": {"destination_id": "dst_quill_acct", "kind": "bank_account", "network": "banksim-fps"},
}


@pytest.fixture
def dorg(engine: Engine, clock: FrozenClock) -> DecisionOrg:
    return setup_decision_org(engine, clock)


@pytest.fixture
def api(dorg: DecisionOrg, engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    s = make_settings(dorg.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield c


def _dest(d: DecisionOrg, cpt: str, cur: str) -> dict[str, str]:
    if cpt in DEST:
        return DEST[cpt]
    key = {"cpt_flagged": "WALLET_FLAGGED_BASE", "cpt_nova": "WALLET_NOVA_ETH"}.get(cpt)
    network = "eth-sepolia" if cpt == "cpt_nova" else "base-sepolia"
    return {"kind": "evm_wallet", "network": network, "address": d.wallets.get(key or "", "0x" + "1" * 40)}


def submit(api: TestClient, d: DecisionOrg, body: dict[str, object]) -> dict[str, object]:
    r = api.post("/v1/payment_intents", json=body, headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_every_demo_payment_replays_to_its_recorded_decision(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    ids = []
    for p in BATCH["payouts"]:
        if "counterparty" not in p:
            continue  # user payouts are deferred (founder decision before S1)
        ids.append(
            str(
                submit(
                    api,
                    dorg,
                    payout(
                        p["counterparty"],
                        p["amount"],
                        p["currency"],
                        _dest(dorg, p["counterparty"], p["currency"]),
                        reference=p["ref"],
                    ),
                )["id"]
            )
        )
    bluefin = submit(
        api,
        dorg,
        payout(
            "cpt_bluefin",
            "18500.00",
            "USDC",
            {"kind": "evm_wallet", "network": "base-sepolia", "address": dorg.wallets["WALLET_BLUEFIN_BASE"]},
        ),
    )
    ids.append(str(bluefin["id"]))
    approve(
        engine,
        clock,
        case_id=str(bluefin["exception"]["id"]),
        org_id=dorg.id,  # type: ignore[index]
        actor=Actor(dorg.org.users[Role.REVIEWER], Role.REVIEWER.value),
        reason="checked",
    )
    # A rule change between decisions: each replays against the version it used.
    pl, cl = (Actor(dorg.org.users[r], r.value) for r in (Role.PAYMENTS_LEAD, Role.COMPLIANCE_LEAD))
    dr = propose_draft(
        engine,
        clock,
        org_id=dorg.id,
        actor=pl,
        yaml_text=v2(('GBP: "5000.00", EUR: "5000.00"}', 'GBP: "5000.00", EUR: "2000.00"}')),
    )
    approve_draft(engine, clock, org_id=dorg.id, draft_id=dr.id, actor=cl, attest=True)
    later = submit(api, dorg, payout("cpt_harbor", "2400.00", "EUR", DEST["cpt_harbor"]))
    assert later["decision"]["policy_version"] == 2 and later["status"] == "ESCALATED"  # type: ignore[index]
    ids.append(str(later["id"]))
    with engine.connect() as c:
        statuses = {
            r.status
            for r in c.execute(text("SELECT status FROM payment_intents WHERE org_id=:o"), {"o": dorg.id})
        }
    assert {"BLOCKED", "ESCALATED", "READY"} <= statuses
    for pid in ids:
        r = api.get(f"/v1/payment_intents/{pid}/replay", headers=dorg.auth())
        assert r.status_code == 200
        j = r.json()
        bad = [(x["recorded"], x["replayed"]) for x in j["steps"] if not x["match"]]
        assert j["match"] is True and j["model_called"] is False, (pid, json.dumps(bad)[:3000])
    bl = replay_payment(engine, clock, org_id=dorg.id, payment_id=str(bluefin["id"]))
    assert [s["recorded"]["outcome"] for s in bl["steps"]] == [
        "ESCALATE",
        "EXECUTE",
    ]  # the approval re-run too
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM incidents WHERE org_id=:o"), {"o": dorg.id}).scalar_one()
            == 0
        )


def test_decisions_cannot_be_edited(api: TestClient, dorg: DecisionOrg, engine: Engine) -> None:
    pid = str(submit(api, dorg, payout("cpt_harbor", "2400.00", "EUR", DEST["cpt_harbor"]))["id"])
    with pytest.raises(DBAPIError, match="only its route"), engine.begin() as c:
        c.execute(
            text("UPDATE decisions SET outcome='BLOCK' WHERE org_id=:o AND payment_id=:p"),
            {"o": dorg.id, "p": pid},
        )
    with pytest.raises(DBAPIError), engine.begin() as c:
        c.execute(text("DELETE FROM decisions WHERE org_id=:o AND payment_id=:p"), {"o": dorg.id, "p": pid})


def test_a_mismatch_raises_an_alert(
    api: TestClient, dorg: DecisionOrg, engine: Engine, clock: FrozenClock
) -> None:
    pid = str(submit(api, dorg, payout("cpt_harbor", "2400.00", "EUR", DEST["cpt_harbor"]))["id"])
    with engine.begin() as c:  # a forged decision record: EXECUTE claimed for facts that say BLOCK
        d = c.execute(
            text("SELECT * FROM decisions WHERE org_id=:o AND payment_id=:p"), {"o": dorg.id, "p": pid}
        ).one()
        snap = dict(d.inputs_snapshot)
        snap["facts"] = {
            **snap["facts"],
            "counterparty": {**snap["facts"]["counterparty"], "kyb_status": "failed"},
        }
        c.execute(
            text(
                "INSERT INTO decisions (id, org_id, payment_id, outcome, policy_version_id, policy_hash, inputs_snapshot, "
                "checks, decided_at, actor) VALUES (:id, :o, :p, 'EXECUTE', :pv, :ph, CAST(:s AS jsonb), CAST(:c AS jsonb), :t, 'x')"
            ),
            {
                "id": new_id(Prefix.DEC, clock.now()),
                "o": dorg.id,
                "p": pid,
                "pv": d.policy_version_id,
                "ph": d.policy_hash,
                "s": json.dumps(snap),
                "c": json.dumps(d.checks),
                "t": clock.now(),
            },
        )
    r = replay_payment(engine, clock, org_id=dorg.id, payment_id=pid)
    assert r["match"] is False and [s["match"] for s in r["steps"]] == [True, False]
    with engine.connect() as c:
        inc = c.execute(
            text("SELECT trigger, subject_id, severity FROM incidents WHERE org_id=:o"), {"o": dorg.id}
        ).one()
        ev = c.execute(
            text("SELECT count(*) FROM audit_events WHERE org_id=:o AND kind='replay.mismatch'"),
            {"o": dorg.id},
        ).scalar_one()
    assert tuple(inc) == ("replay_mismatch", pid, 2) and ev == 1


def test_replay_of_unknown_payment_is_404(api: TestClient, dorg: DecisionOrg) -> None:
    assert api.get("/v1/payment_intents/pay_nope/replay", headers=dorg.auth()).status_code == 404
