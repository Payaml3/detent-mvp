-- 0010 (slice P1, WHK-01 to WHK-03, API-07): webhook endpoints, events and the delivery log.
--
-- Signing secrets are stored encrypted with CREDENTIALS_ENCRYPTION_KEY (C-19, D-12): every delivery is
-- signed with the plaintext, which a hash cannot give back. secret_hash keeps a SHA-256 fingerprint so a
-- secret can be identified without decrypting it. Endpoints created before this migration had no secret
-- that could sign, so none exist in practice; the column is nullable only for that reason.
ALTER TABLE webhook_endpoints
    ADD COLUMN secret_encrypted TEXT,
    ADD COLUMN description      TEXT,
    ADD CONSTRAINT webhook_endpoints_url_scheme CHECK (url ~ '^https?://');

-- Events carry the payment they concern (filter for GET /v1/events) and a test flag (G-20).
-- pos gives a total order for cursor paging (IDs made in the same millisecond do not sort by time).
ALTER TABLE webhook_events
    ADD COLUMN payment_id TEXT,
    ADD COLUMN test       BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN pos        BIGINT GENERATED ALWAYS AS IDENTITY;
CREATE INDEX webhook_events_org_pos ON webhook_events (org_id, pos DESC);
CREATE INDEX webhook_events_org_payment ON webhook_events (org_id, payment_id, sequence);
CREATE INDEX webhook_events_org_subject ON webhook_events (org_id, subject_id, sequence);

-- Events are facts: never edited or removed, like the audit log they come from.
CREATE FUNCTION webhook_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'webhook_events is append-only' USING ERRCODE = 'check_violation';
END $$;
CREATE TRIGGER webhook_events_no_change BEFORE UPDATE OR DELETE ON webhook_events
    FOR EACH ROW EXECUTE FUNCTION webhook_events_append_only();
CREATE TRIGGER webhook_events_no_truncate BEFORE TRUNCATE ON webhook_events
    FOR EACH STATEMENT EXECUTE FUNCTION webhook_events_append_only();

-- The delivery log: one row per attempt, with the response status and time (WHK-03).
ALTER TABLE webhook_deliveries
    ADD COLUMN latency_ms      INTEGER,
    ADD COLUMN outcome         TEXT CHECK (outcome IN ('succeeded', 'retrying', 'failed')),
    ADD COLUMN next_attempt_at TIMESTAMPTZ,
    ADD COLUMN manual          BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN pos             BIGINT GENERATED ALWAYS AS IDENTITY;
CREATE INDEX webhook_deliveries_org_endpoint ON webhook_deliveries (org_id, endpoint_id, pos DESC);
CREATE INDEX webhook_deliveries_org_event ON webhook_deliveries (org_id, event_id);
