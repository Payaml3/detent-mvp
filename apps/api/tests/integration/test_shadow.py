"""SHD-01 to SHD-04, EXC-09 and DSH-13: shadow import, anonymisation, the report, mode gates, agent
agreement and the production-mode request."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from conftest import login, make_settings
from decision_helpers import PEPPER, DecisionOrg, payout, setup_decision_org
from detent.api.app import create_app
from detent.audit.log import Actor
from detent.clock import FrozenClock
from detent.dashboard import production
from detent.dashboard.access import AccessError, Member
from detent.domain.ids import Prefix, new_id
from detent.domain.roles import Role
from detent.exceptions.agreement import sample
from detent.exceptions.cases import reject
from detent.execution.modes import ModeError, approve_mode_change, propose_mode_change
from detent.policy.changes import approve_draft, propose_draft
from detent.policy.screening import MockScreening
from detent.rails.registry import install_rail
from detent.shadow import gates, imports, pdf, report
from fastapi.testclient import TestClient
from policy_helpers import v2
from pydantic import SecretStr
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

MAPPING = {
    "ref": "Payment Ref",
    "occurred_at": "When",
    "direction": "Direction",
    "amount": "Amount",
    "currency": "Ccy",
    "counterparty": "Payee",
    "network": "Rail",
    "destination": "Destination",
    "platform_decision": "Our decision",
    "payee_text": "Memo",
    "fee": "Fee",
}
HEADER = "Payment Ref,When,Direction,Amount,Ccy,Payee,Rail,Destination,Our decision,Memo,Fee\n"


def csv_for(d: DecisionOrg) -> bytes:
    blue = d.wallets["WALLET_BLUEFIN_BASE"]
    rows = [
        "P-1,2026-11-20T09:00:00Z,payout,2000.00,EUR,cpt_harbor,banksim-sepa-inst,,approved,Harbor invoice 1,1.50",
        "P-2,2026-11-20T10:00:00Z,payout,2100.00,EUR,cpt_harbor,banksim-sepa-inst,,rejected,Harbor invoice 2,1.50",
        f"P-3,2026-11-21T09:00:00Z,payout,18500.00,USDC,cpt_bluefin,base-sepolia,{blue},held,INV-2026-0142,",
        "P-4,2026-11-22T09:00:00Z,payout,500.00,EUR,Acme Widgets Ltd,banksim-sepa-inst,GB29NWBK60161331926819,"
        "approved,Acme Widgets refund,",
        "D-1,2026-11-22T11:00:00Z,deposit,300.00,USDC,cpt_bluefin,base-sepolia,,,,",
        "P-5,2026-11-23T09:00:00Z,payout,abc,EUR,cpt_harbor,banksim-sepa-inst,,approved,,",
        "P-6,2026-11-24T09:00:00Z,payout,10.00,EUR,cpt_harbor,banksim-sepa-inst,,approved,,",
        "P-6,2026-11-24T09:05:00Z,payout,10.00,EUR,cpt_harbor,banksim-sepa-inst,,approved,,",
    ]
    return (HEADER + "\n".join(rows) + "\n").encode()


@pytest.fixture
def setup(engine: Engine, clock: FrozenClock) -> Iterator[tuple[DecisionOrg, TestClient]]:
    d = setup_decision_org(engine, clock, mode="shadow")
    with engine.begin() as c:  # a connected EUR rail, for the simulated routing saving
        install_rail(
            c, d.id, rail_id="banksim-sepa-inst", kind="banksim", network="banksim-sepa-inst", currency="EUR",
            est_fee_minor=25,
        )  # fmt: skip
    s = make_settings(d.id, api_key_pepper=SecretStr(PEPPER))
    with TestClient(create_app(s, engine=engine, clock=clock, configure_logging=False)) as c:
        yield d, c


def who(d: DecisionOrg, role: Role) -> Actor:
    return Actor(d.org.users[role], role.value)


def run(
    engine: Engine, clock: FrozenClock, d: DecisionOrg, data: bytes, mapping: dict[str, str] = MAPPING
) -> str:
    imp, _ = imports.run_import(
        engine,
        clock,
        org_id=d.id,
        actor=who(d, Role.PAYMENTS_LEAD),
        data=data,
        mapping=mapping,
        label="November export",
        screening=MockScreening.from_fixture(),
    )
    return imp


def rows(engine: Engine, d: DecisionOrg, imp: str) -> dict[str, object]:
    with engine.connect() as c:
        return {(r.platform_ref, r.row_no): r for r in report.rows_for(c, d.id, imp)}


# ------------------------------------------------------------------------------------------ SHD-01
def test_mapping_guess_and_validation_report_store_nothing(
    setup: tuple[DecisionOrg, TestClient], engine: Engine
) -> None:
    d, _ = setup
    data = csv_for(d)
    cols = imports.read_header(data)
    guess = imports.guess_mapping(["Ref", "Date", "Direction", "Amount", "Currency", "Payee", "Rail"])
    assert guess == {
        "ref": "Ref", "occurred_at": "Date", "direction": "Direction", "amount": "Amount", "currency": "Currency",
        "counterparty": "Payee", "network": "Rail",
    }  # fmt: skip
    rep = imports.validate(data, MAPPING)
    s = rep.summary()
    assert (s["rows_read"], s["rows_valid"], s["rows_invalid"]) == (8, 5, 3)
    assert s["problems"] == {
        "duplicate ref": 2,
        "amount is not a positive amount in the currency's minor units": 1,
    }
    assert cols[0] == "Payment Ref"
    with pytest.raises(imports.ImportError_, match="missing: network"):
        imports.validate(data, {k: v for k, v in MAPPING.items() if k != "network"})
    with pytest.raises(imports.ImportError_, match="not in the file"):
        imports.validate(data, {**MAPPING, "fee": "Nope"})
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM shadow_imports WHERE org_id=:o"), {"o": d.id}).scalar_one()
            == 0
        )


def test_decisions_run_and_nothing_is_executed(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, _ = setup
    with engine.connect() as c:
        before = {
            t: c.execute(text(f"SELECT count(*) FROM {t} WHERE org_id=:o"), {"o": d.id}).scalar_one()
            for t in ("payment_intents", "decisions", "attempts", "jobs", "destinations")
        }
    imp = run(engine, clock, d, csv_for(d))
    r = rows(engine, d, imp)
    assert r[("P-1", 1)].outcome == "EXECUTE"
    assert r[("P-3", 3)].outcome == "ESCALATE"
    assert r[("P-4", 4)].outcome in ("ESCALATE", "BLOCK") and r[("P-4", 4)].counterparty_id is None
    assert r[("D-1", 5)].outcome is None and r[("D-1", 5)].direction == "deposit"
    assert r[("P-5", 6)].outcome is None and r[("P-5", 6)].problems
    assert all(not c.get("evidence") for row in r.values() for c in row.checks)
    with engine.connect() as c:
        after = {
            t: c.execute(text(f"SELECT count(*) FROM {t} WHERE org_id=:o"), {"o": d.id}).scalar_one()
            for t in before
        }
        imp_row = c.execute(
            text("SELECT * FROM shadow_imports WHERE org_id=:o AND id=:i"), {"o": d.id, "i": imp}
        ).one()
        ev = c.execute(
            text("SELECT payload FROM audit_events WHERE org_id=:o AND kind='shadow.imported'"), {"o": d.id}
        ).scalar_one()
    assert after == before  # no payment, decision row, attempt, job or destination was created
    assert (imp_row.rows_read, imp_row.rows_decided, imp_row.rows_invalid) == (8, 4, 3)
    assert ev["executed"] is False and ev["policy_version"] == 1
    with pytest.raises(Exception, match="append-only"), engine.begin() as c:
        c.execute(text("DELETE FROM shadow_rows WHERE org_id=:o"), {"o": d.id})


def test_daily_caps_count_inside_the_import(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    """Payouts that would execute on one day add up against that day's cap (EUR 10,000 per counterparty)."""
    d, _ = setup
    body = HEADER + "".join(
        f"C-{i},2026-11-20T0{i}:00:00Z,payout,3000.00,EUR,cpt_harbor,banksim-sepa-inst,,approved,,\n"
        for i in range(1, 9)
    )
    r = rows(engine, d, run(engine, clock, d, body.encode()))
    outcomes = [r[(f"C-{i}", i)].outcome for i in range(1, 9)]
    assert outcomes[0] == "EXECUTE" and outcomes[-1] != "EXECUTE"


# ------------------------------------------------------------------------------------------ SHD-04
def test_raw_names_and_account_identifiers_are_never_stored(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, _ = setup
    data = csv_for(d)
    imp1, imp2 = run(engine, clock, d, data), run(engine, clock, d, data)
    with engine.connect() as c:
        dump = " ".join(
            str(tuple(r))
            for r in c.execute(text("SELECT * FROM shadow_rows WHERE org_id=:o"), {"o": d.id}).all()
        ) + " ".join(
            str(tuple(r))
            for r in c.execute(text("SELECT * FROM shadow_imports WHERE org_id=:o"), {"o": d.id})
        )
        audit = str(
            c.execute(
                text("SELECT payload FROM audit_events WHERE org_id=:o AND kind='shadow.imported'"),
                {"o": d.id},
            ).all()
        )
    for raw in ("Acme Widgets", "GB29NWBK60161331926819", d.wallets["WALLET_BLUEFIN_BASE"], "Harbor invoice"):
        assert raw not in dump and raw not in audit, raw
    a, b = rows(engine, d, imp1), rows(engine, d, imp2)
    # Consistent within one import (P-1 and P-2 share a payee), different across imports.
    assert a[("P-1", 1)].counterparty_hash == a[("P-2", 2)].counterparty_hash
    assert a[("P-1", 1)].counterparty_hash != b[("P-1", 1)].counterparty_hash
    assert a[("P-4", 4)].destination_hash and a[("P-4", 4)].destination_hash != b[("P-4", 4)].destination_hash


# ------------------------------------------------------------------------------------------ SHD-02
def test_report_sections_and_exports(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    imp = run(engine, clock, d, csv_for(d))
    with engine.connect() as c:
        rep = report.build(c, d.id, imp)
        weeks = report.weeks(c, d.id, imp)
        same = report.build(c, d.id, imp)
    mix = {m["outcome"]: m["count"] for m in rep["mix"]}
    assert sum(mix.values()) == 4 and mix["EXECUTE"] >= 2
    agr = rep["agreement"]
    assert agr["compared"] == 4
    assert [r.platform_ref for r in agr["unsafe"]] == ["P-2"]  # DekernAI would execute; the platform rejected
    assert [r.platform_ref for r in agr["stopped"]] == ["P-4"]
    assert {r.row_no for r in rep["unreconciled"]} == {6, 7, 8}
    assert rep["routing"]["rows"] == 2 and rep["routing"]["saving"]
    assert report.as_lines(rep) == report.as_lines(same)  # replayable: same rows, same report
    assert weeks == ["2026-W47", "2026-W48"]
    start, end = report.week_bounds("2026-W48")
    with engine.connect() as c:
        wk = report.build(c, d.id, imp, start, end)
    assert wk["filtered"] and wk["rows_read"] == 3
    body = pdf.render(report.as_lines(rep), title="t")
    assert body.startswith(b"%PDF-1.4") and body.rstrip().endswith(b"%%EOF") and b"Unsafe approvals" in body

    login(api, d.org.users[Role.REVIEWER])
    html = api.get(f"/console/shadow/{imp}").text
    for section in ("summary", "mix", "agreement", "unsafe", "unreconciled", "routing", "method"):
        assert f'data-section="{section}"' in html, section
    assert "Nothing was sent" in html
    f = api.get(f"/console/shadow/{imp}/report.html")
    assert (
        f.status_code == 200
        and "attachment" in f.headers["content-disposition"]
        and "Unsafe approvals" in f.text
    )
    p = api.get(f"/console/shadow/{imp}/report.pdf?week=2026-W47")
    assert (
        p.status_code == 200 and p.headers["content-type"] == "application/pdf" and p.content[:4] == b"%PDF"
    )
    assert api.get("/console/shadow/shi_nope").status_code == 404


def test_console_upload_map_validate_and_decide(
    setup: tuple[DecisionOrg, TestClient], engine: Engine
) -> None:
    d, api = setup
    data = csv_for(d)
    login(api, d.org.users[Role.REVIEWER])
    assert api.post("/console/shadow/map", files={"file": ("x.csv", data)}).status_code == 403
    login(api, d.org.users[Role.PAYMENTS_LEAD])
    m = api.post("/console/shadow/map", files={"file": ("nov.csv", data)})
    assert m.status_code == 200 and 'value="Payment Ref" selected' in m.text
    form = {f"map_{k}": v for k, v in MAPPING.items()}
    v = api.post(
        "/console/shadow/import", data={**form, "action": "validate"}, files={"file": ("nov.csv", data)}
    )
    assert v.status_code == 200 and "8 rows read: 5 valid, 3 with problems" in v.text
    r = api.post(
        "/console/shadow/import",
        data={**form, "action": "decide", "label": "Nov"},
        files={"file": ("nov.csv", data)},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/console/shadow/shi_")
    assert "Nov" in api.get("/console/shadow").text


# ------------------------------------------------------------------------------------------ SHD-03
def clean_csv(n: int = 20) -> bytes:
    body = HEADER + "".join(
        f"G-{i},2026-11-{10 + i % 15:02d}T09:00:00Z,payout,100.00,EUR,cpt_harbor,banksim-sepa-inst,,approved,,\n"
        for i in range(n)
    )
    return body.encode()


def test_gate_fails_on_an_unsafe_approval_and_cannot_be_signed(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, _ = setup
    run(engine, clock, d, csv_for(d))
    g = gates.create_gate(engine, clock, org_id=d.id, actor=who(d, Role.PAYMENTS_LEAD), to_mode="assist")
    with engine.connect() as c:
        row = c.execute(text("SELECT * FROM mode_gates WHERE org_id=:o AND id=:g"), {"o": d.id, "g": g}).one()
    assert not row.passed and row.unsafe_approvals == 1 and row.threshold_bp == 9500  # D-41
    with pytest.raises(gates.GateError, match="did not pass"):
        gates.sign_gate(engine, clock, org_id=d.id, gate_id=g, actor=who(d, Role.PAYMENTS_LEAD))


def test_passed_gate_signed_by_both_leads_is_linked_to_the_mode_change(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, api = setup
    with engine.begin() as c:
        c.execute(text("UPDATE organisations SET production=true WHERE org_id=:o"), {"o": d.id})
    pl, cl = who(d, Role.PAYMENTS_LEAD), who(d, Role.COMPLIANCE_LEAD)
    # A production organisation can't move up without a gate; a sandbox one can (test_docs_guides).
    with pytest.raises(ModeError, match="signed mode gate"):
        propose_mode_change(engine, clock, org_id=d.id, actor=pl, to_mode="assist", reason="x")
    run(engine, clock, d, clean_csv())
    g = gates.create_gate(engine, clock, org_id=d.id, actor=pl, to_mode="assist")
    with engine.connect() as c:
        row = c.execute(text("SELECT * FROM mode_gates WHERE org_id=:o AND id=:g"), {"o": d.id, "g": g}).one()
    assert row.passed and row.compared == 20 and row.agreed == 20 and row.unsafe_approvals == 0
    with pytest.raises(gates.GateError, match="only the payments lead"):
        gates.sign_gate(engine, clock, org_id=d.id, gate_id=g, actor=who(d, Role.REVIEWER))
    gates.sign_gate(engine, clock, org_id=d.id, gate_id=g, actor=pl)
    with pytest.raises(gates.GateError, match="already signed"):
        gates.sign_gate(engine, clock, org_id=d.id, gate_id=g, actor=pl)
    with pytest.raises(ModeError, match="not passed and signed"):
        propose_mode_change(engine, clock, org_id=d.id, actor=pl, to_mode="assist", reason="x", gate_id=g)
    gates.sign_gate(engine, clock, org_id=d.id, gate_id=g, actor=cl)
    with pytest.raises(ModeError, match="is for shadow to assist"):
        propose_mode_change(engine, clock, org_id=d.id, actor=pl, to_mode="auto", reason="x", gate_id=g)
    ch = propose_mode_change(
        engine, clock, org_id=d.id, actor=pl, to_mode="assist", reason="gate passed", gate_id=g
    )
    approve_mode_change(engine, clock, org_id=d.id, change_id=ch, actor=cl)
    with engine.connect() as c:
        row = c.execute(text("SELECT * FROM mode_gates WHERE org_id=:o AND id=:g"), {"o": d.id, "g": g}).one()
        mode = c.execute(text("SELECT mode FROM organisations WHERE org_id=:o"), {"o": d.id}).scalar_one()
        kinds = (
            c.execute(
                text(
                    "SELECT kind FROM audit_events WHERE org_id=:o AND kind LIKE 'mode_gate.%' ORDER BY seq"
                ),
                {"o": d.id},
            )
            .scalars()
            .all()
        )
    assert (row.mode_change_id, mode) == (ch, "assist")
    assert kinds == ["mode_gate.created", "mode_gate.signed", "mode_gate.signed"]
    login(api, d.org.users[Role.COMPLIANCE_LEAD])
    assert "assist" in api.get("/console/shadow").text


def test_the_gate_window_is_30_days(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, _ = setup
    run(engine, clock, d, clean_csv())
    with engine.connect() as c:
        now = gates.measure(c, d.id, clock.now())
        later = gates.measure(c, d.id, clock.now() + timedelta(days=60))
    assert now["compared"] == 20 and now["passed"]
    assert later["compared"] == 0 and not later["passed"]


# ------------------------------------------------------------------------------------------ EXC-09
def test_agent_versus_human_agreement(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    import json

    d, api = setup
    with engine.begin() as c:
        c.execute(text("UPDATE organisations SET mode='auto' WHERE org_id=:o"), {"o": d.id})
    dest = {"kind": "evm_wallet", "network": "base-sepolia", "address": d.wallets["WALLET_BLUEFIN_BASE"]}
    cases = []
    for rec in ("reject", "approve", "needs_information"):
        r = api.post(
            "/v1/payment_intents",
            json=payout("cpt_bluefin", "18500.00", "USDC", dest, reference=f"INV-{rec}"),
            headers={**d.auth(), "Idempotency-Key": str(uuid.uuid4())},
        )
        case = r.json()["exception"]["id"]
        cases.append(case)
        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO agent_calls (id, org_id, kind, subject_id, model, prompt_version, input_hash, parsed, "
                    "created_at, status) VALUES (:id, :o, 'investigation', :s, 'stand-in', 'v1', 'h', "
                    "CAST(:p AS jsonb), :t, 'recorded')"
                ),
                {
                    "id": new_id(Prefix.AGC, clock.now()),
                    "o": d.id,
                    "s": case,
                    "p": json.dumps(
                        {"recommendation": rec, "confidence": 0.7, "claims": [{"text": f"claim {rec}"}]}
                    ),
                    "t": clock.now(),
                },
            )
        reject(
            engine,
            clock,
            case_id=case,
            org_id=d.id,
            actor=who(d, Role.REVIEWER),
            reason=f"human reason {rec}",
        )
    with engine.connect() as c:
        s = sample(c, d.id, clock.now() - timedelta(days=1), clock.now() + timedelta(seconds=1))
    assert (s["cases"], s["compared"], s["not_compared"], s["agreed"]) == (3, 2, 1, 1)
    assert s["rate"] == "50.00%"
    (dis,) = s["disagreements"]
    assert (dis["agent"], dis["human"], dis["agent_rationale"], dis["human_rationale"]) == (
        "approve", "rejected", ["claim approve"], "human reason approve",
    )  # fmt: skip
    login(api, d.org.users[Role.REVIEWER])
    html = api.get("/console/agreement?days=2").text
    assert "50.00%" in html and "human reason approve" in html and cases[1] in html


# ------------------------------------------------------------------------------------------ DSH-13
def test_production_request_needs_verification_and_signed_rules_and_changes_nothing(
    setup: tuple[DecisionOrg, TestClient], engine: Engine, clock: FrozenClock
) -> None:
    d, _ = setup
    owner = Member(d.org.users[Role.ACCOUNT_OWNER], d.id, "o@test.invalid", "Owner", Role.ACCOUNT_OWNER)
    dev = Member(d.org.users[Role.DEVELOPER], d.id, "d@test.invalid", "Dev", Role.DEVELOPER)
    with engine.begin() as c, pytest.raises(AccessError, match="verified integration"):
        production.request_production(c, clock, by=owner)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO verification_requests (id, org_id, requested_by, requested_at, checklist, status, "
                "decided_by, decided_at) VALUES (:id, :o, :u, :t, '[]', 'verified', 'usr_staff', :t)"
            ),
            {"id": new_id(Prefix.VER, clock.now()), "o": d.id, "u": owner.id, "t": clock.now()},
        )
        assert production.readiness(c, d.id)["verified"] and not production.readiness(c, d.id)["rules_signed"]
    tighter = ('auto_limit: {USDC: "10000.00"', 'auto_limit: {USDC: "8000.00"')
    draft = propose_draft(engine, clock, org_id=d.id, actor=who(d, Role.PAYMENTS_LEAD), yaml_text=v2(tighter))
    approve_draft(
        engine, clock, org_id=d.id, draft_id=draft.id, actor=who(d, Role.COMPLIANCE_LEAD), attest=True
    )
    with engine.begin() as c, pytest.raises(AccessError, match="role"):
        production.request_production(c, clock, by=dev)
    with engine.begin() as c:
        before = c.execute(text("SELECT mode, kind FROM organisations WHERE org_id=:o"), {"o": d.id}).one()
        keys_before = c.execute(
            text("SELECT count(*) FROM api_keys WHERE org_id=:o"), {"o": d.id}
        ).scalar_one()
        rid = production.request_production(c, clock, by=owner)
    with engine.begin() as c, pytest.raises(AccessError, match="already"):
        production.request_production(c, clock, by=owner)
    with engine.connect() as c:
        after = c.execute(text("SELECT mode, kind FROM organisations WHERE org_id=:o"), {"o": d.id}).one()
        keys_after = c.execute(
            text("SELECT count(*) FROM api_keys WHERE org_id=:o"), {"o": d.id}
        ).scalar_one()
        ev = c.execute(
            text("SELECT payload FROM audit_events WHERE org_id=:o AND kind='production.requested'"),
            {"o": d.id},
        ).scalar_one()
    assert rid.startswith("prq_") and tuple(after) == tuple(before) and keys_after == keys_before
    assert ev["starts_in"] == "shadow" and ev["available_in_prototype"] is False and ev["policy_version"] == 2
