"""DSH-02: dashboard emails (invites). Development and the prototype write to the outbox (G-02); the
transactional email provider for production is an open founder decision, so nothing else can be configured
yet (settings refuse any other EMAIL_PROVIDER). Until then an admin copies the invite link from the admin
screen, which shows it once."""

from __future__ import annotations

from sqlalchemy import Connection, text

from detent.clock import Clock
from detent.domain.ids import Prefix, new_id


def send_email(conn: Connection, clock: Clock, *, org_id: str, to: str, template: str, body: str) -> str:
    now = clock.now()
    mid = new_id(Prefix.OBX, now)
    conn.execute(
        text(
            "INSERT INTO outbox (id, org_id, channel, recipient, template, body, created_at) "
            "VALUES (:id, :o, 'email_mock', :to, :t, :b, :now)"
        ),
        {"id": mid, "o": org_id, "to": to, "t": template, "b": body, "now": now},
    )
    return mid
