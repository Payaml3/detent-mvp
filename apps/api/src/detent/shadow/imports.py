"""Shadow CSV import (SHD-01) with anonymisation on import (SHD-04). Spec: docs/product/shadow-report.md.

1. ``read_header`` gives the column names, and ``guess_mapping`` a first mapping, for the mapping screen.
2. ``validate`` checks every row against the mapping and returns a validation report; nothing is stored.
3. ``run_import`` validates again, decides every valid payout with the active rule version (the same checks
   as POL-08, run in memory) and stores the result. Nothing is executed: no payment intent, decision row or
   attempt is created, and counters are simulated per day inside the import.

SHD-04: names and account identifiers (the counterparty reference, the destination and any payee text) are
hashed with a random per-import salt before anything is stored, and the salt is thrown away. Hashes are
consistent within one import and can't be linked across imports. Checks keep their result and reason, never
their evidence (which can quote an address). When the counterparty reference is a registry ID (``cpt_...``),
the registry's own facts are used, and that ID is kept: it is DekernAI's record, not the export's.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import secrets
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Connection, Engine, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.db.engine import transaction
from detent.domain.ids import Prefix, new_id
from detent.domain.money import Currency, Money, MoneyError
from detent.policy.engine import evaluate
from detent.policy.facts import CounterpartyFacts, DestinationFacts, Facts
from detent.policy.screening import Screening
from detent.policy.store import NoActivePolicy, active_policy

MAX_ROWS = 20_000
MAX_BYTES = 5 * 1024 * 1024

# field -> (required, description). The mapping screen lists these in order.
FIELDS: dict[str, tuple[bool, str]] = {
    "ref": (True, "Platform payment reference"),
    "occurred_at": (True, "Date and time (UTC, ISO 8601)"),
    "direction": (True, "Direction: payout or deposit"),
    "amount": (True, "Amount (decimal, for example 1250.00)"),
    "currency": (True, "Currency (USDC, GBP or EUR)"),
    "counterparty": (True, "Counterparty reference"),
    "network": (True, "Rail or network used, for example base-sepolia or banksim-fps"),
    "destination": (False, "Destination wallet address or account number"),
    "platform_decision": (False, "Your own decision: approved, held or rejected"),
    "payee_text": (False, "Invoice or payee text"),
    "fee": (False, "Fee paid (decimal, same currency)"),
}
_GUESS = {
    "ref": ("ref", "reference", "payment_ref", "id", "payment_id"),
    "occurred_at": ("occurred_at", "date", "datetime", "timestamp", "created_at", "time"),
    "direction": ("direction", "type", "kind"),
    "amount": ("amount", "value"),
    "currency": ("currency", "ccy"),
    "counterparty": ("counterparty", "counterparty_ref", "payee", "beneficiary"),
    "network": ("network", "rail", "rail_used"),
    "destination": ("destination", "address", "wallet", "account", "iban"),
    "platform_decision": ("platform_decision", "decision", "our_decision", "outcome"),
    "payee_text": ("payee_text", "memo", "description", "invoice"),
    "fee": ("fee", "fee_paid"),
}
_DECISIONS = {
    "approved": "approved", "approve": "approved", "executed": "approved", "paid": "approved",
    "held": "held", "hold": "held", "escalated": "held", "review": "held",
    "rejected": "rejected", "reject": "rejected", "blocked": "rejected", "declined": "rejected",
}  # fmt: skip


class ImportError_(ValueError):
    pass


@dataclass
class RowResult:
    row_no: int
    values: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    columns: list[str]
    rows: list[RowResult]
    mapping: dict[str, str]

    @property
    def valid(self) -> list[RowResult]:
        return [r for r in self.rows if not r.problems]

    @property
    def invalid(self) -> list[RowResult]:
        return [r for r in self.rows if r.problems]

    def summary(self) -> dict[str, Any]:
        reasons = Counter(p for r in self.invalid for p in r.problems)
        return {
            "rows_read": len(self.rows),
            "rows_valid": len(self.valid),
            "rows_invalid": len(self.invalid),
            "problems": dict(reasons.most_common()),
        }


def _decode(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise ImportError_(f"the file is over {MAX_BYTES // (1024 * 1024)} MB")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportError_("the file is not UTF-8 text") from None


def read_header(data: bytes) -> list[str]:
    reader = csv.reader(io.StringIO(_decode(data)))
    header = next(reader, None)
    if not header or not any(h.strip() for h in header):
        raise ImportError_("the file has no header row")
    return [h.strip() for h in header]


def guess_mapping(columns: list[str]) -> dict[str, str]:
    low = {c.lower().replace(" ", "_"): c for c in columns}
    out: dict[str, str] = {}
    for f, names in _GUESS.items():
        for n in names:
            if n in low:
                out[f] = low[n]
                break
    return out


def _parse_time(v: str) -> datetime:
    t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC)


def _parse_amount(v: str, currency: Currency) -> Money:
    try:
        Decimal(v)
    except InvalidOperation:
        raise MoneyError(f"{v!r} is not a number") from None
    return Money.parse(v, currency)


def _money(r: RowResult, get: dict[str, str]) -> None:
    """Currency, amount and fee: integer minor units in a supported currency."""
    try:
        cur = Currency(get["currency"].upper())
    except ValueError:
        r.problems.append("currency is not USDC, GBP or EUR")
        cur = None
    if cur is not None:
        try:
            m = _parse_amount(get["amount"], cur)
            if m.amount_minor <= 0:
                raise MoneyError("not positive")
            r.values["amount"] = m
        except (MoneyError, ValueError):
            r.problems.append("amount is not a positive amount in the currency's minor units")
        if get.get("fee"):
            try:
                fee = _parse_amount(get["fee"], cur)
                if fee.amount_minor < 0:
                    raise MoneyError("negative")
                r.values["fee"] = fee
            except (MoneyError, ValueError):
                r.problems.append("fee is not an amount")


def _row(row_no: int, raw: dict[str, str], mapping: dict[str, str]) -> RowResult:
    r = RowResult(row_no)
    get = {f: (raw.get(col) or "").strip() for f, col in mapping.items()}
    for f, (required, _) in FIELDS.items():
        if required and not get.get(f):
            r.problems.append(f"missing {f}")
    if r.problems:
        return r
    r.values["ref"] = get["ref"][:140]
    try:
        r.values["occurred_at"] = _parse_time(get["occurred_at"])
    except ValueError:
        r.problems.append("occurred_at is not an ISO 8601 date and time")
    direction = get["direction"].lower()
    if direction in ("payout", "out", "debit", "withdrawal"):
        r.values["direction"] = "payout"
    elif direction in ("deposit", "in", "credit"):
        r.values["direction"] = "deposit"
    else:
        r.problems.append("direction is not payout or deposit")
    _money(r, get)
    if get.get("platform_decision"):
        d = _DECISIONS.get(get["platform_decision"].lower())
        if d is None:
            r.problems.append("platform_decision is not approved, held or rejected")
        r.values["platform_decision"] = d
    r.values["counterparty"] = get["counterparty"]
    r.values["network"] = get["network"]
    r.values["destination"] = get.get("destination") or None
    r.values["payee_text"] = get.get("payee_text") or None
    return r


def validate(data: bytes, mapping: dict[str, str]) -> ValidationReport:
    columns = read_header(data)
    mapping = {f: c for f, c in mapping.items() if c}
    unknown = [f for f in mapping if f not in FIELDS]
    if unknown:
        raise ImportError_(f"unknown field {unknown[0]!r}")
    missing = [f for f, (req, _) in FIELDS.items() if req and f not in mapping]
    if missing:
        raise ImportError_(f"map a column to every required field; missing: {', '.join(missing)}")
    absent = [c for c in mapping.values() if c not in columns]
    if absent:
        raise ImportError_(f"column {absent[0]!r} is not in the file")
    reader = csv.DictReader(io.StringIO(_decode(data)), fieldnames=columns)
    next(reader, None)  # the header line
    rows: list[RowResult] = []
    seen: Counter[str] = Counter()
    for i, raw in enumerate(reader, start=1):
        if i > MAX_ROWS:
            raise ImportError_(f"the file has more than {MAX_ROWS} rows")
        if not any((v or "").strip() for v in raw.values() if isinstance(v, str)):
            continue
        r = _row(i, raw, mapping)
        ref = r.values.get("ref")
        if ref:
            seen[ref] += 1
        rows.append(r)
    for r in rows:  # a duplicate reference is listed, not dropped
        if r.values.get("ref") and seen[r.values["ref"]] > 1:
            r.problems.append("duplicate ref")
    return ValidationReport(columns, rows, mapping)


# ------------------------------------------------------------------------------------- deciding
def _hasher(salt: bytes) -> Any:
    def h(v: str | None) -> str | None:
        if not v:
            return None
        return hashlib.sha256(salt + v.strip().lower().encode()).hexdigest()[:24]

    return h


def _counterparty(conn: Connection, org_id: str, ref: str) -> tuple[CounterpartyFacts, str | None]:
    from detent.intents.service import load_counterparty

    if ref.startswith("cpt_"):
        known = conn.execute(
            text("SELECT 1 FROM counterparties WHERE org_id=:o AND id=:c"), {"o": org_id, "c": ref}
        ).scalar_one_or_none()
        if known:
            return load_counterparty(conn, org_id, ref), ref
    # Not in the registry: unknown KYB, not allowlisted, no history. The rules decide what that means.
    return CounterpartyFacts("unregistered", "", "unknown", False, 0, None), None


def _destination(
    conn: Connection, org_id: str, cpt: str | None, network: str, value: str | None, at: datetime
) -> DestinationFacts:
    if cpt is not None:
        rows = conn.execute(
            text(
                "SELECT id, address, account_masked, first_seen_at, last_changed_at, last_changed_by "
                "FROM destinations WHERE org_id=:o AND counterparty_id=:c AND network=:n ORDER BY "
                "first_seen_at"
            ),
            {"o": org_id, "c": cpt, "n": network},
        ).all()
        for r in rows:
            if value is None and len(rows) == 1:
                return DestinationFacts(
                    r.id,
                    True,
                    r.address,
                    r.account_masked,
                    r.first_seen_at,
                    r.last_changed_at,
                    r.last_changed_by,
                )
            if value and (
                (r.address or "").lower() == value.lower()
                or (r.account_masked and value[-4:] == r.account_masked[-4:])
            ):
                return DestinationFacts(
                    r.id,
                    True,
                    r.address,
                    r.account_masked,
                    r.first_seen_at,
                    r.last_changed_at,
                    r.last_changed_by,
                )
    # Not registered: first seen at the payment, so NEW_WALLET applies (G-01).
    address = value if value and value.startswith("0x") else None
    return DestinationFacts(None, False, address, None if address else value, at, at, None)


def _simulated_route(conn: Connection, org_id: str, amount: Money) -> tuple[str | None, int | None]:
    """SHD-02: the lowest estimated fee among the organisation's connected rails in the same currency."""
    r = conn.execute(
        text(
            "SELECT id, est_fee_minor FROM rails WHERE org_id=:o AND enabled AND currency=:c "
            "ORDER BY est_fee_minor, id LIMIT 1"
        ),
        {"o": org_id, "c": amount.currency.value},
    ).one_or_none()
    return (r.id, int(r.est_fee_minor)) if r else (None, None)


def _decide(
    conn: Connection,
    org_id: str,
    rules: Any,
    screening: Screening,
    row: RowResult,
    used: dict[tuple[str, str], Money],
    cache: dict[str, Any],
) -> dict[str, Any]:
    from detent.intents.service import load_org, load_travel_rule

    v = row.values
    at: datetime = v["occurred_at"]
    amount: Money = v["amount"]
    if v["counterparty"] not in cache:
        cache[v["counterparty"]] = _counterparty(conn, org_id, v["counterparty"])
    cp, cpt_id = cache[v["counterparty"]]
    dest = _destination(conn, org_id, cpt_id, v["network"], v["destination"], at)
    day = at.date().isoformat()
    zero = Money.zero(amount.currency)
    p_key, c_key = (
        (day, f"platform:{amount.currency.value}"),
        (day, f"{v['counterparty']}:{amount.currency.value}"),
    )
    if "_org" not in cache:
        cache["_org"] = load_org(conn, org_id)
    org = cache["_org"]
    facts = Facts(
        now=at,
        source="platform",
        amount=amount,
        network=v["network"],
        counterparty=cp,
        destination=dest,
        screening=screening.check(address=dest.address, name=cp.name or None),
        travel_rule=load_travel_rule(org, cp, dest, None, "platform"),
        used_today_platform=used.get(p_key, zero),
        used_today_counterparty=used.get(c_key, zero),
        recent_block_id=None,
        mandate=None,
    )
    try:
        ev = evaluate(facts, rules)
    except Exception as exc:  # fail closed (invariant 9): a failed evaluation is an escalation
        return {"outcome": "ESCALATE", "reasons": ["SYSTEM_UNAVAILABLE"], "checks": [], "cpt": cpt_id,
                "error": type(exc).__name__}  # fmt: skip
    if ev.outcome == "EXECUTE":  # only amounts that would have gone out count toward the day's caps
        used[p_key] = used.get(p_key, zero) + amount
        used[c_key] = used.get(c_key, zero) + amount
    checks = [
        {"check": c.check, "result": c.result, **({"reason": c.reason} if c.reason else {})}
        for c in ev.checks
    ]
    return {"outcome": ev.outcome, "reasons": ev.reasons, "checks": checks, "cpt": cpt_id}


def run_import(
    engine: Engine,
    clock: Clock,
    *,
    org_id: str,
    actor: Actor,
    data: bytes,
    mapping: dict[str, str],
    label: str,
    screening: Screening,
) -> tuple[str, ValidationReport]:
    report = validate(data, mapping)
    if not report.rows:
        raise ImportError_("the file has no data rows")
    salt = secrets.token_bytes(16)  # SHD-04: never stored
    h = _hasher(salt)
    now = clock.now()
    imp = new_id(Prefix.SHI, now)
    with transaction(engine) as conn:
        try:
            pol = active_policy(conn, org_id)
        except NoActivePolicy:
            raise ImportError_("the organisation has no active rule set") from None
        used: dict[tuple[str, str], Money] = {}
        cache: dict[str, Any] = {}
        stored: list[dict[str, Any]] = []
        times = [r.values["occurred_at"] for r in report.rows if "occurred_at" in r.values]
        ordered = sorted(report.rows, key=lambda r: (r.values.get("occurred_at") or now, r.row_no))
        for r in ordered:
            v = r.values
            res: dict[str, Any] = {}
            sim_rail = sim_fee = None
            if not r.problems and v["direction"] == "payout":
                res = _decide(conn, org_id, pol.rules, screening, r, used, cache)
                sim_rail, sim_fee = _simulated_route(conn, org_id, v["amount"])
            elif not r.problems and v["counterparty"].startswith("cpt_"):
                res = {"cpt": _counterparty(conn, org_id, v["counterparty"])[1]}
            amount: Money | None = v.get("amount")
            fee: Money | None = v.get("fee")
            stored.append(
                {
                    "id": new_id(Prefix.SHR, now),
                    "o": org_id,
                    "i": imp,
                    "n": r.row_no,
                    "ref": v.get("ref"),
                    "at": v.get("occurred_at"),
                    "dir": v.get("direction"),
                    "amt": amount.amount_minor if amount else None,
                    "cur": amount.currency.value if amount else None,
                    "cpt": res.get("cpt"),
                    "ch": h(v.get("counterparty")),
                    "dh": h(v.get("destination")),
                    "ph": h(v.get("payee_text")),
                    "net": v.get("network"),
                    "pd": v.get("platform_decision"),
                    "fee": fee.amount_minor if fee else None,
                    "out": res.get("outcome"),
                    "reasons": list(res.get("reasons", [])),
                    "checks": json.dumps(res.get("checks", [])),
                    "problems": list(r.problems),
                    "srail": sim_rail,
                    "sfee": sim_fee,
                }
            )
        decided = sum(1 for s in stored if s["out"])
        conn.execute(
            text(
                "INSERT INTO shadow_imports (id, org_id, label, mapping, policy_version_id, policy_version, "
                "rows_read, rows_decided, rows_invalid, period_from, period_to, created_by, "
                "created_at) VALUES "
                "(:id, :o, :l, CAST(:m AS jsonb), :pid, :pv, :rr, :rd, :ri, :pf, :pt, :by, :t)"
            ),
            {
                "id": imp,
                "o": org_id,
                "l": label.strip()[:200] or "Shadow import",
                "m": json.dumps(report.mapping),
                "pid": pol.id,
                "pv": pol.version,
                "rr": len(report.rows),
                "rd": decided,
                "ri": len(report.invalid),
                "pf": min(times) if times else None,
                "pt": max(times) if times else None,
                "by": actor.id,
                "t": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO shadow_rows (id, org_id, import_id, row_no, platform_ref, occurred_at, "
                "direction, "
                "amount_minor, currency, counterparty_id, counterparty_hash, destination_hash, "
                "payee_hash, network, "
                "platform_decision, fee_minor, outcome, reasons, checks, problems, simulated_rail, "
                "simulated_fee_minor) VALUES (:id, :o, :i, :n, :ref, :at, :dir, :amt, :cur, :cpt, "
                ":ch, :dh, :ph, "
                ":net, :pd, :fee, :out, :reasons, CAST(:checks AS jsonb), :problems, :srail, :sfee)"
            ),
            stored,
        )
        append(
            conn,
            clock,
            org_id=org_id,
            actor=actor,
            kind="shadow.imported",
            subject_id=imp,
            payload={
                "rows_read": len(report.rows),
                "rows_decided": decided,
                "rows_invalid": len(report.invalid),
                "policy_version": pol.version,
                "mapping": report.mapping,
                "executed": False,
            },
        )
    return imp, report
