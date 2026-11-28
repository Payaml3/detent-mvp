"""DSH-02: dashboard emails (invites, the sales inbox notice of an access request).

Every email is written to the outbox in the caller's transaction. With ``EMAIL_PROVIDER=outbox`` (development,
tests, the demo) that is all: an admin copies an invite link from the admin screen, which shows it once. With
``EMAIL_PROVIDER=zeptomail`` the row's channel is ``email`` and an ``email.send`` job, committed with it,
sends it through ZeptoMail (``dashboard/email_delivery.py``). Nothing is sent inside a request's
transaction.

Only these dashboard emails are ever sent. The console's counterparty notices and case messages stay
``email_mock`` (fictional recipients) whatever the provider.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from detent.clock import Clock
from detent.domain.ids import Prefix, new_id
from detent.settings import Settings, get_settings
from detent.worker import queue

SEND_JOB = "email.send"


def send_email(
    conn: Connection,
    clock: Clock,
    *,
    org_id: str,
    to: str,
    template: str,
    body: str,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    live = settings.email_provider == "zeptomail"
    now = clock.now()
    mid = new_id(Prefix.OBX, now)
    channel = "email" if live else "email_mock"
    conn.execute(
        text(
            "INSERT INTO outbox (id, org_id, channel, recipient, template, body, created_at) "
            "VALUES (:id, :o, :ch, :to, :t, :b, :now)"
        ),
        {
            "id": mid,
            "o": org_id,
            "ch": channel,
            "to": to,
            "t": template,
            "b": body,
            "now": now,
        },
    )
    if live:
        queue.enqueue(conn, clock, org_id=org_id, kind=SEND_JOB, payload={"outbox_id": mid}, dedupe_key=mid)
    return mid
