"""Mandates in the database: issue, revoke, verify against an intent (MND-01 to MND-03).

``verify`` is what the policy's mandate check reads (MND-02). It is deterministic and needs no model:
signature, revocation, validity window, payee, per-payment amount, currency, network and the cumulative
total. The total covers the mandate's whole validity window (G-12, D-29): confirmed plus in-flight
payments count, and a payment stops counting when it is BLOCKED, REJECTED, CANCELLED or FAILED_FINAL.
The usage row is locked while it is read, so parallel intents can't overrun the total.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from pydantic import SecretStr
from sqlalchemy import Connection, text

from detent.audit.log import Actor, append
from detent.clock import Clock
from detent.domain.money import Currency, Money, MoneyError
from detent.mandates.signing import sign, verify_signature
from detent.policy.facts import MandateFacts, Unavailable
from detent.settings import REPO_ROOT

FIXTURE = REPO_ROOT / "fixtures" / "mandates" / "ap-agent-mandate.json"


def fixture_mandate(clock: Clock, org_id: str, *, days: int = 30) -> dict[str, Any]:
    """The demo accounts-payable agent's mandate, valid from yesterday for `days` days (unsigned)."""
    raw = FIXTURE.read_text()
    now = clock.now()
    raw = raw.replace("{{NOW_MINUS_1D}}", (now - timedelta(days=1)).isoformat()).replace(
        "{{NOW_PLUS_30D}}", (now + timedelta(days=days)).isoformat()
    )
    doc: dict[str, Any] = json.loads(raw)
    doc["principal"]["org_id"] = org_id
    doc["signature"]["value"] = None
    return doc


def issue_mandate(
    conn: Connection, clock: Clock, org_id: str, doc: dict[str, Any], key: SecretStr, *, actor: Actor
) -> str:
    doc = json.loads(json.dumps(doc))
    doc["principal"]["org_id"] = org_id
    doc.setdefault("signature", {"alg": "HS256", "key_id": "mk_demo_1"})
    doc["signature"]["alg"] = "HS256"
    doc["signature"]["value"] = sign(doc, key)
    conn.execute(
        text(
            "INSERT INTO mandates (id, org_id, agent_id, version, payload, signature, valid_from, "
            "expires_at, created_at) "
            "VALUES (:id, :o, :a, :v, CAST(:p AS jsonb), :s, :vf, :ex, :t)"
        ),
        {
            "id": doc["mandate_id"],
            "o": org_id,
            "a": doc["agent"]["agent_id"],
            "v": int(doc["version"]),
            "p": json.dumps({k: v for k, v in doc.items() if k != "signature"}),
            "s": json.dumps(doc["signature"]),
            "vf": doc["valid_from"],
            "ex": doc["expires_at"],
            "t": clock.now(),
        },
    )
    conn.execute(
        text("INSERT INTO mandate_usage (org_id, mandate_id) VALUES (:o, :m) ON CONFLICT DO NOTHING"),
        {"o": org_id, "m": doc["mandate_id"]},
    )
    append(
        conn,
        clock,
        org_id=org_id,
        actor=actor,
        kind="mandate.issued",
        subject_id=doc["mandate_id"],
        payload={
            "agent_id": doc["agent"]["agent_id"],
            "version": int(doc["version"]),
            "scope": doc["scope"],
            "valid_from": doc["valid_from"],
            "expires_at": doc["expires_at"],
            # The MAC (not a key): verify() checks the stored document is the one issued last (S8).
            "signature": doc["signature"]["value"],
        },
    )
    return str(doc["mandate_id"])


def revoke_mandate(conn: Connection, clock: Clock, org_id: str, mandate_id: str, *, actor: Actor) -> None:
    """MND-03: takes effect for every intent not yet SUBMITTED (the pre-send re-check blocks them)."""
    done = conn.execute(
        text(
            "UPDATE mandates SET revoked_at=:t, revoked_by=:a WHERE org_id=:o AND id=:m AND revoked_at IS "
            "NULL "
            "RETURNING id"
        ),
        {"t": clock.now(), "a": actor.id, "o": org_id, "m": mandate_id},
    ).scalar_one_or_none()
    if done is None:
        exists = conn.execute(
            text("SELECT 1 FROM mandates WHERE org_id=:o AND id=:m"), {"o": org_id, "m": mandate_id}
        ).first()
        if exists is None:
            raise LookupError(mandate_id)
        return  # already revoked
    append(conn, clock, org_id=org_id, actor=actor, kind="mandate.revoked", subject_id=mandate_id, payload={})


def load_document(
    conn: Connection, org_id: str, mandate_id: str
) -> tuple[dict[str, Any], datetime | None] | None:
    r = conn.execute(
        text("SELECT payload, signature, revoked_at FROM mandates WHERE org_id=:o AND id=:m"),
        {"o": org_id, "m": mandate_id},
    ).one_or_none()
    if r is None:
        return None
    try:
        sig = r.signature if isinstance(r.signature, dict) else json.loads(r.signature)
    except ValueError:
        sig = {}  # an unreadable signature is simply invalid (MANDATE_SIGNATURE_INVALID)
    if not isinstance(sig, dict):
        sig = {}
    return {**r.payload, "signature": sig}, r.revoked_at


def _issued_record(conn: Connection, org_id: str, mandate_id: str) -> dict[str, Any] | None:
    """The last ``mandate.issued`` audit event's payload (the append-only, hash-chained record)."""
    p = conn.execute(
        text(
            "SELECT payload FROM audit_events WHERE org_id=:o AND kind='mandate.issued' AND subject_id=:m "
            "ORDER BY seq DESC LIMIT 1"
        ),
        {"o": org_id, "m": mandate_id},
    ).scalar_one_or_none()
    return dict(p) if p is not None else None


def _revoked_in_audit(conn: Connection, org_id: str, mandate_id: str) -> bool:
    last = conn.execute(
        text(
            "SELECT kind FROM audit_events WHERE org_id=:o AND kind IN ('mandate.issued','mandate.revoked') "
            "AND subject_id=:m ORDER BY seq DESC LIMIT 1"
        ),
        {"o": org_id, "m": mandate_id},
    ).scalar_one_or_none()
    return last == "mandate.revoked"


def _block(mandate_id: str, reason: str, **evidence: Any) -> MandateFacts:
    return MandateFacts(mandate_id, False, reason, {"mandate_id": mandate_id, **evidence})


def _iso(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def verify(  # noqa: PLR0911, PLR0912 - one return per MND-02 reason
    conn: Connection,
    *,
    org_id: str,
    mandate_id: str,
    key: SecretStr | None,
    now: datetime,
    payee: str | None,
    amount: Money,
    network: str,
    already_counted: bool = False,
) -> MandateFacts | Unavailable:
    loaded = load_document(conn, org_id, mandate_id)
    if loaded is None:
        return _block(mandate_id, "MANDATE_MISSING")
    if key is None:
        return Unavailable("mandate_key", "not_configured")  # fail closed: escalate, never pass
    doc, revoked_at = loaded
    if not verify_signature(doc, key) or doc.get("principal", {}).get("org_id") != org_id:
        return _block(mandate_id, "MANDATE_SIGNATURE_INVALID")
    issued = _issued_record(conn, org_id, mandate_id)
    if issued is not None and (
        issued.get("version", doc.get("version")) != doc.get("version")
        or issued.get("signature", doc["signature"].get("value")) != doc["signature"].get("value")
    ):
        # A validly signed but older (or otherwise replaced) document: only the last issued one counts.
        return _block(mandate_id, "MANDATE_SIGNATURE_INVALID", note="not the last issued version")
    if revoked_at is None and _revoked_in_audit(conn, org_id, mandate_id):
        revoked_at = now  # the audit log says it was revoked, even if the row was edited since
    if revoked_at is not None:
        return _block(mandate_id, "MANDATE_REVOKED", revoked_at=revoked_at.isoformat())
    if not (_iso(doc["valid_from"]) <= now <= _iso(doc["expires_at"])):
        return _block(
            mandate_id, "MANDATE_EXPIRED", valid_from=doc["valid_from"], expires_at=doc["expires_at"]
        )
    scope = doc["scope"]
    if payee not in scope.get("payees", []):
        return _block(mandate_id, "MANDATE_PAYEE_OUT_OF_SCOPE", payee=payee, payees=scope.get("payees", []))
    if network not in scope.get("networks", []):
        return _block(
            mandate_id, "MANDATE_NETWORK_OUT_OF_SCOPE", network=network, networks=scope.get("networks", [])
        )
    try:
        per = Money.parse(scope["max_per_payment"]["amount"], scope["max_per_payment"]["currency"])
        total = Money.parse(scope["max_total"]["amount"], scope["max_total"]["currency"])
    except (KeyError, MoneyError, ValueError):
        return _block(mandate_id, "MANDATE_SIGNATURE_INVALID", note="scope amounts unreadable")
    if (
        amount.currency.value not in scope.get("currencies", [])
        or amount.currency is not per.currency
        or amount > per
    ):
        return _block(
            mandate_id, "MANDATE_AMOUNT_EXCEEDED", amount=amount.to_api(), max_per_payment=per.to_api()
        )
    conn.execute(
        text("INSERT INTO mandate_usage (org_id, mandate_id) VALUES (:o, :m) ON CONFLICT DO NOTHING"),
        {"o": org_id, "m": mandate_id},
    )
    used = Money(
        int(
            conn.execute(
                text("SELECT total_minor FROM mandate_usage WHERE org_id=:o AND mandate_id=:m FOR UPDATE"),
                {"o": org_id, "m": mandate_id},
            ).scalar_one()
        ),
        Currency(total.currency),
    )
    if already_counted:
        used = used - amount
    if used + amount > total:
        return _block(
            mandate_id,
            "MANDATE_TOTAL_EXCEEDED",
            used=used.to_decimal_str(),
            this_payment=amount.to_decimal_str(),
            max_total=total.to_decimal_str(),
        )
    return MandateFacts(
        mandate_id,
        True,
        None,
        {
            "mandate_id": mandate_id,
            "max_per_payment": per.to_decimal_str(),
            "used": used.to_decimal_str(),
            "max_total": total.to_decimal_str(),
        },
    )


def add_usage(conn: Connection, org_id: str, mandate_id: str, amount: Money) -> None:
    conn.execute(
        text(
            "UPDATE mandate_usage SET total_minor = total_minor + :a, count = count + 1 WHERE org_id=:o "
            "AND mandate_id=:m"
        ),
        {"a": amount.amount_minor, "o": org_id, "m": mandate_id},
    )


def release_usage(conn: Connection, org_id: str, mandate_id: str, amount: Money) -> None:
    conn.execute(
        text(
            "UPDATE mandate_usage SET total_minor = greatest(total_minor - :a, 0), count = greatest(count "
            "- 1, 0) "
            "WHERE org_id=:o AND mandate_id=:m"
        ),
        {"a": amount.amount_minor, "o": org_id, "m": mandate_id},
    )


def list_mandates(conn: Connection, org_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, agent_id, version, payload, valid_from, expires_at, revoked_at, revoked_by, "
            "created_at, "
            "coalesce(u.total_minor, 0) AS used FROM mandates m LEFT JOIN mandate_usage u ON u.org_id = "
            "m.org_id "
            "AND u.mandate_id = m.id WHERE m.org_id=:o ORDER BY m.created_at, m.id"
        ),
        {"o": org_id},
    ).all()
    out = []
    for r in rows:
        scope = r.payload["scope"]
        total = Money.parse(scope["max_total"]["amount"], scope["max_total"]["currency"])
        out.append(
            {
                "mandate_id": r.id,
                "agent_id": r.agent_id,
                "version": r.version,
                "scope": scope,
                "valid_from": r.valid_from.isoformat(),
                "expires_at": r.expires_at.isoformat(),
                "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
                "revoked_by": r.revoked_by,
                "used": str(Money(int(r.used), total.currency)),
                "max_total": str(total),
            }
        )
    return out
