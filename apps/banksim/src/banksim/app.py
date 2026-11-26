"""Simulated instant bank rail (RAL-04, spec/06). Test networks only: no real bank is involved.

Two schemes: Faster Payments-style (``fps``, GBP) and SEPA Instant-style (``sepa_inst``, EUR).

- ``POST /payments`` with an ``Idempotency-Key`` header: the same key and body return the same payment;
  the same key with a different body is 409. Per-payment and daily limits reject (422 REJECTED);
  inside a cut-off window the rail is unavailable (503, nothing accepted).
- ``GET /payments/{key}``: ACCEPTED, SETTLED, FAILED or REJECTED; 404 when the rail never saw the key.
- ``GET /statements/{YYYY-MM-DD}``: the day's settled payments and inbound credits, as JSON or, with
  ``?format=csv``, as CSV (LED-07 reconciles against it).
- ``POST /inbound``: simulate a payer sending money in with a reference (tests and the demo use it;
  a real bank would push this). ``GET /inbound?scheme=&after=<seq>`` lists inbound credits (LED-04).
- Settlement is asynchronous after ``settle_seconds``; a callback is POSTed to ``callback_url`` if set.

Deterministic test values (SBX-01): an amount ending in .13 is accepted but its first answer is held
until the client times out, then it settles; an amount ending in .42 fails technically. A configurable
failure rate fails a deterministic share of keys.

Storage: its own Postgres schema ``banksim``; it never touches DekernAI's tables.
Run it with ``uvicorn banksim.app:create_app --factory --port 8100``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, create_engine, text

SCHEMES = {"fps": "GBP", "sepa_inst": "EUR"}

DDL = """
CREATE SCHEMA IF NOT EXISTS banksim;
CREATE TABLE IF NOT EXISTS banksim.payments (
    key          TEXT PRIMARY KEY,
    body_hash    TEXT NOT NULL,
    scheme       TEXT NOT NULL,
    amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
    currency     TEXT NOT NULL,
    account      TEXT NOT NULL,
    reference    TEXT,
    debtor       TEXT NOT NULL DEFAULT '',
    fee_minor    BIGINT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('ACCEPTED','SETTLED','FAILED','REJECTED')),
    reason       TEXT,
    created_at   TIMESTAMPTZ NOT NULL,
    settle_at    TIMESTAMPTZ,
    settled_at   TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS banksim.inbound (
    id           TEXT PRIMARY KEY,
    seq          BIGSERIAL UNIQUE,
    scheme       TEXT NOT NULL,
    amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
    currency     TEXT NOT NULL,
    reference    TEXT NOT NULL,
    payer        TEXT NOT NULL,
    account      TEXT NOT NULL DEFAULT '',
    received_at  TIMESTAMPTZ NOT NULL
);
-- Columns added after a schema may already exist locally.
ALTER TABLE banksim.payments ADD COLUMN IF NOT EXISTS debtor TEXT NOT NULL DEFAULT '';
ALTER TABLE banksim.inbound ADD COLUMN IF NOT EXISTS account TEXT NOT NULL DEFAULT '';
"""


@dataclass
class SchemeConfig:
    per_payment_limit_minor: int = 25_000_00
    daily_limit_minor: int = 100_000_00
    fee_flat_minor: int = 20
    fee_bps: int = 0
    cutoff: tuple[int, int] | None = None  # (start hour, end hour) UTC when the rail is closed


@dataclass
class Config:
    schemes: dict[str, SchemeConfig] = field(
        default_factory=lambda: {
            "fps": SchemeConfig(fee_flat_minor=20),
            "sepa_inst": SchemeConfig(fee_flat_minor=25, fee_bps=5),
        }
    )
    failure_rate: float = 0.0  # simulator configuration, not money
    settle_seconds: float = 0.0
    hold_seconds: float = (
        12.0  # how long a ".13" first answer is held back: longer than the adapter timeout (10 s)
    )
    callback_url: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)  # the simulator is a separate app; it is not bound by DekernAI's Clock


def _fails(key: str, rate: float) -> bool:
    if rate <= 0:
        return False
    bucket = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return bucket < rate


def _row(r: Any) -> dict[str, Any]:
    return {
        "key": r.key,
        "scheme": r.scheme,
        "amount_minor": int(r.amount_minor),
        "currency": r.currency,
        "account": r.account,
        "reference": r.reference,
        "fee_minor": int(r.fee_minor),
        "status": r.status,
        "reason": r.reason,
        "created_at": r.created_at.isoformat(),
        "settled_at": r.settled_at.isoformat() if r.settled_at else None,
    }


def create_app(database_url: str | None = None, config: Config | None = None) -> FastAPI:  # noqa: PLR0915
    cfg = config or Config()
    url = (
        database_url
        or os.environ.get("BANKSIM_DATABASE_URL")
        or os.environ.get("DATABASE_URL", "postgresql+psycopg://detent:detent@localhost:5432/detent")
    )
    engine: Engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql(DDL)
    app = FastAPI(title="DekernAI bank simulator (test only; not a real bank)")
    app.state.config = cfg
    held_once: set[str] = set()
    lock = threading.Lock()

    def settle_due() -> list[dict[str, Any]]:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    "UPDATE banksim.payments SET status='SETTLED', settled_at=now() "
                    "WHERE status='ACCEPTED' AND settle_at <= now() RETURNING *"
                )
            ).all()
        out = [_row(r) for r in rows]
        if cfg.callback_url:
            for p in out:
                with contextlib.suppress(httpx.HTTPError):  # best effort; DekernAI also polls
                    httpx.post(cfg.callback_url, json={"key": p["key"], "status": p["status"]}, timeout=3)
        return out

    def _settler() -> None:
        while True:
            time.sleep(0.2)
            try:
                settle_due()
            except Exception:  # keep settling after a transient database error
                time.sleep(1)

    if cfg.callback_url:
        # Settle in the background only when someone listens for callbacks; otherwise payments settle
        # when they are read (status or statement), which is enough for polling clients.
        threading.Thread(target=_settler, daemon=True).start()

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        # business_date: the simulated bank's own day, which its statements are cut by (S9 close the day)
        return {
            "status": "ok",
            "schemes": list(SCHEMES),
            "simulated": True,
            "business_date": _now().date().isoformat(),
        }

    @app.post("/payments")
    async def create(
        request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key")
    ) -> JSONResponse:
        body = await request.json()
        scheme = body.get("scheme")
        if scheme not in SCHEMES:
            return JSONResponse({"error": "unknown scheme"}, status_code=400)
        sc = cfg.schemes[scheme]
        amount = int(body.get("amount_minor", 0))
        body_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        with engine.begin() as conn:
            existing = conn.execute(
                text("SELECT * FROM banksim.payments WHERE key=:k"), {"k": idempotency_key}
            ).one_or_none()
        if existing is not None:
            if existing.body_hash != body_hash:
                return JSONResponse(
                    {"error": "idempotency key reused with a different body"}, status_code=409
                )
            return JSONResponse(_row(existing), status_code=200)
        if sc.cutoff and sc.cutoff[0] <= _now().hour < sc.cutoff[1]:
            return JSONResponse(
                {"error": "inside the scheme's cut-off window", "reason": "CUT_OFF"}, status_code=503
            )
        now = _now()
        reason, status = None, "ACCEPTED"
        if body.get("currency") != SCHEMES[scheme] or amount <= 0:
            status, reason = "REJECTED", "INVALID"
        elif amount > sc.per_payment_limit_minor:
            status, reason = "REJECTED", "PER_PAYMENT_LIMIT"
        else:
            with engine.connect() as conn:
                today = conn.execute(
                    text(
                        "SELECT coalesce(sum(amount_minor), 0) FROM banksim.payments WHERE scheme=:s "
                        "AND status IN ('ACCEPTED','SETTLED') AND created_at::date = :d"
                    ),
                    {"s": scheme, "d": now.date()},
                ).scalar_one()
            if int(today) + amount > sc.daily_limit_minor:
                status, reason = "REJECTED", "DAILY_LIMIT"
        if status == "ACCEPTED" and (amount % 100 == 42 or _fails(idempotency_key, cfg.failure_rate)):
            status, reason = "FAILED", "TECHNICAL"
        fee = sc.fee_flat_minor + amount * sc.fee_bps // 10_000
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO banksim.payments (key, body_hash, scheme, amount_minor, currency, "
                    "account, reference, debtor, "
                    "fee_minor, status, reason, created_at, settle_at) VALUES (:k, :h, :s, :a, :c, :acct, "
                    ":ref, :debtor, :fee, "
                    ":st, :r, :t, CASE WHEN :st = 'ACCEPTED' THEN :t + make_interval(secs => :delay) END) "
                    "ON CONFLICT (key) DO NOTHING"
                ),
                {
                    "k": idempotency_key,
                    "h": body_hash,
                    "s": scheme,
                    "a": amount,
                    "c": body.get("currency"),
                    "acct": str(body.get("account", "")),
                    "ref": body.get("reference"),
                    "debtor": str(body.get("debtor", "")),
                    "fee": fee,
                    "st": status,
                    "r": reason,
                    "t": now,
                    "delay": cfg.settle_seconds,
                },
            )
            row = conn.execute(
                text("SELECT * FROM banksim.payments WHERE key=:k"), {"k": idempotency_key}
            ).one()
        if amount % 100 == 13:
            with lock:
                first = idempotency_key not in held_once
                held_once.add(idempotency_key)
            if first:
                import asyncio

                await asyncio.sleep(cfg.hold_seconds)  # accepted, but the client gives up waiting
        code = 422 if row.status == "REJECTED" else 201
        return JSONResponse(_row(row), status_code=code)

    @app.get("/payments/{key}")
    def get(key: str) -> JSONResponse:
        settle_due()
        with engine.connect() as conn:
            r = conn.execute(text("SELECT * FROM banksim.payments WHERE key=:k"), {"k": key}).one_or_none()
        if r is None:
            return JSONResponse({"key": key, "status": "NOT_FOUND"}, status_code=404)
        return JSONResponse(_row(r))

    def _inbound_row(r: Any) -> dict[str, Any]:
        return {
            "id": r.id,
            "seq": int(r.seq),
            "scheme": r.scheme,
            "amount_minor": int(r.amount_minor),
            "currency": r.currency,
            "reference": r.reference,
            "payer": r.payer,
            "account": r.account,
            "received_at": r.received_at.isoformat(),
        }

    @app.post("/inbound")
    async def inbound_credit(request: Request) -> JSONResponse:
        b = await request.json()
        scheme = str(b.get("scheme", ""))
        if scheme not in SCHEMES:
            return JSONResponse({"error": "unknown scheme"}, status_code=422)
        amount = b.get("amount_minor")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            return JSONResponse({"error": "amount_minor must be a positive integer"}, status_code=422)
        iid = str(
            b.get("id") or f"bin_{hashlib.sha256(json.dumps(b, sort_keys=True).encode()).hexdigest()[:16]}"
        )
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO banksim.inbound (id, scheme, amount_minor, currency, reference, "
                    "payer, account, "
                    "received_at) VALUES (:i, :s, :a, :c, :r, :p, :acc, now()) ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "i": iid,
                    "s": scheme,
                    "a": amount,
                    "c": SCHEMES[scheme],
                    "r": str(b.get("reference", "")),
                    "p": str(b.get("payer", "unknown payer (fictional)")),
                    "acc": str(b.get("account", "")),
                },
            )
            r = conn.execute(text("SELECT * FROM banksim.inbound WHERE id=:i"), {"i": iid}).one()
        return JSONResponse(_inbound_row(r), status_code=201)

    @app.get("/inbound")
    def list_inbound(scheme: str, after: int = 0, account: str | None = None) -> dict[str, Any]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM banksim.inbound WHERE scheme=:s AND seq > :a "
                    "AND (CAST(:acc AS text) IS NULL OR account = :acc) ORDER BY seq LIMIT 500"
                ),
                {"s": scheme, "a": after, "acc": account},
            ).all()
        return {"data": [_inbound_row(r) for r in rows]}

    @app.get("/statements/{day}", response_model=None)
    def statement(
        day: date, scheme: str | None = None, format: str = "json", account: str | None = None
    ) -> Any:
        settle_due()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM banksim.payments WHERE status='SETTLED' AND settled_at::date = :d "
                    "AND (CAST(:s AS text) IS NULL OR scheme = :s) "
                    "AND (CAST(:acc AS text) IS NULL OR debtor = :acc) ORDER BY settled_at"
                ),
                {"d": day, "s": scheme, "acc": account},
            ).all()
            inbound = conn.execute(
                text(
                    "SELECT * FROM banksim.inbound WHERE received_at::date = :d "
                    "AND (CAST(:s AS text) IS NULL OR scheme = :s) "
                    "AND (CAST(:acc AS text) IS NULL OR account = :acc) ORDER BY seq"
                ),
                {"d": day, "s": scheme, "acc": account},
            ).all()
        if format == "csv":
            lines = ["line_id,direction,scheme,amount_minor,currency,reference,party,at"]
            lines += [
                f"{r.key},out,{r.scheme},{int(r.amount_minor)},{r.currency},{r.reference or ''},"
                f"{r.account.replace(',', ' ')},{r.settled_at.isoformat()}"
                for r in rows
            ]
            lines += [
                f"{r.id},in,{r.scheme},{int(r.amount_minor)},{r.currency},{r.reference.replace(',', ' ')},"
                f"{r.payer.replace(',', ' ')},{r.received_at.isoformat()}"
                for r in inbound
            ]
            from fastapi.responses import PlainTextResponse

            return PlainTextResponse("\n".join(lines) + "\n", media_type="text/csv")
        return {
            "date": day.isoformat(),
            "payments": [_row(r) for r in rows],
            "inbound": [_inbound_row(r) for r in inbound],
        }

    return app
