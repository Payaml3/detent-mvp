"""The ``email.send`` job: sends one outbox email through Zoho ZeptoMail (UK), then records the outcome.

- 2xx: ``sent_at`` and the provider's request ID are stored.
- 429, 5xx, a timeout or a connection error: the job raises, so the worker retries it with backoff.
- Any other 4xx (bad token, unverified sender, bad address): stored in ``last_error`` and not retried, because
  sending again can't help. The admin screen still shows invite links, so nobody is locked out.

The token is a secret (``ZEPTOMAIL_TOKEN``) and is never logged; settings redact it from every log line.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import text

from detent.dashboard.email import SEND_JOB
from detent.settings import Settings
from detent.worker.registry import JobContext, handler

log = logging.getLogger(__name__)

SUBJECTS = {
    "invite.account_owner": "You're invited to {brand}",
    "invite.member": "You're invited to join your team on {brand}",
    "access_request": "New access request from the {brand} website",
}
TIMEOUT_SECONDS = 15.0


class RetryableSendError(RuntimeError):
    """ZeptoMail could not take the email right now; the worker tries again later."""


def subject_for(template: str, brand: str) -> str:
    return SUBJECTS.get(template, "A message from {brand}").format(brand=brand)


def request_body(settings: Settings, to: str, subject: str, body: str) -> dict[str, object]:
    return {
        "from": {"address": settings.email_from, "name": settings.brand_name},
        "to": [{"email_address": {"address": to}}],
        "subject": subject,
        "textbody": body,
    }


@handler(SEND_JOB)
def send_job(ctx: JobContext) -> None:
    settings = ctx.settings
    if settings is None:
        raise RuntimeError("email delivery needs settings")
    org_id, outbox_id = ctx.job.org_id, str(ctx.job.payload["outbox_id"])
    row = ctx.conn.execute(
        text(
            "SELECT recipient, template, body, sent_at FROM outbox "
            "WHERE org_id=:o AND id=:id AND channel='email' FOR UPDATE"
        ),
        {"o": org_id, "id": outbox_id},
    ).one_or_none()
    if row is None or row.sent_at is not None:
        return  # gone or already sent: never send twice
    payload = request_body(settings, row.recipient, subject_for(row.template, settings.brand_name), row.body)
    headers = {
        "Authorization": f"Zoho-enczapikey {settings.zeptomail_token.get_secret_value()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        r = httpx.post(settings.zeptomail_api_url, json=payload, headers=headers, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise RetryableSendError(f"ZeptoMail unreachable: {type(exc).__name__}") from exc
    if r.status_code == 429 or r.status_code >= 500:
        raise RetryableSendError(f"ZeptoMail answered HTTP {r.status_code}")
    if 200 <= r.status_code < 300:
        try:
            request_id = str(r.json().get("request_id") or "") or None
        except ValueError:
            request_id = None
        ctx.conn.execute(
            text(
                "UPDATE outbox SET sent_at=:now, provider_message_id=:rid, last_error=NULL "
                "WHERE org_id=:o AND id=:id"
            ),
            {"now": ctx.clock.now(), "rid": request_id, "o": org_id, "id": outbox_id},
        )
        return
    error = f"HTTP {r.status_code}: {r.text[:300]}"
    log.warning("email not sent", extra={"outbox_id": outbox_id, "status": r.status_code})
    ctx.conn.execute(
        text("UPDATE outbox SET last_error=:e WHERE org_id=:o AND id=:id"),
        {"e": error, "o": org_id, "id": outbox_id},
    )
