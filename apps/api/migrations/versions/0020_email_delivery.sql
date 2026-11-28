-- Dashboard emails can be sent for real through ZeptoMail (founder, 2026-11-28). Such a message is written to
-- the outbox with channel 'email' and a job sends it; 'email_mock' messages are only stored, as before.
ALTER TABLE outbox DROP CONSTRAINT IF EXISTS outbox_channel_check;
ALTER TABLE outbox ADD CONSTRAINT outbox_channel_check CHECK (channel IN ('email_mock', 'email', 'webhook'));
ALTER TABLE outbox ADD COLUMN provider_message_id TEXT;  -- the provider's request ID once accepted
ALTER TABLE outbox ADD COLUMN last_error TEXT;           -- why the last send failed, if it did
