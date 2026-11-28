-- Slice L group 3.
-- RAL-08: a circuit breaker per rail. It opens after `circuit_failures` technical failures in a row (TECHNICAL_*,
-- TIMEOUT; a rejection by the rail is a business answer and doesn't count) and closes after a successful health
-- probe. An open circuit takes the rail out of routing.
ALTER TABLE rails
    ADD COLUMN circuit_state       TEXT NOT NULL DEFAULT 'closed' CHECK (circuit_state IN ('closed', 'open')),
    ADD COLUMN circuit_failures    INTEGER NOT NULL DEFAULT 3 CHECK (circuit_failures BETWEEN 1 AND 100),
    ADD COLUMN circuit_changed_at  TIMESTAMPTZ,
    ADD COLUMN circuit_probe_at    TIMESTAMPTZ,
    ADD COLUMN circuit_probe_ok    BOOLEAN;

-- RAL-09: how a rail was connected (mock consent screen or scoped keys). The credential is Fernet-encrypted with
-- CREDENTIALS_ENCRYPTION_KEY and never shown again; only a hint is kept for display. Disconnecting removes the
-- credential (a new row state, not a delete) and disables the rail.
CREATE TABLE rail_connections (
    id                TEXT PRIMARY KEY CHECK (id LIKE 'rcn\_%'),
    org_id            TEXT NOT NULL REFERENCES organisations(id),
    rail_id           TEXT NOT NULL,
    method            TEXT NOT NULL CHECK (method IN ('consent', 'api_key')),
    scopes            TEXT[] NOT NULL CHECK (cardinality(scopes) >= 1),
    credential        TEXT,
    credential_hint   TEXT CHECK (credential_hint IS NULL OR length(credential_hint) <= 12),
    connected_by      TEXT NOT NULL,
    connected_at      TIMESTAMPTZ NOT NULL,
    disconnected_by   TEXT,
    disconnected_at   TIMESTAMPTZ,
    FOREIGN KEY (org_id, rail_id) REFERENCES rails(org_id, id),
    CHECK ((disconnected_at IS NULL) = (credential IS NOT NULL)),
    CHECK ((disconnected_at IS NULL) = (disconnected_by IS NULL))
);
CREATE UNIQUE INDEX one_live_rail_connection ON rail_connections (org_id, rail_id) WHERE disconnected_at IS NULL;
CREATE INDEX rail_connections_org ON rail_connections (org_id, connected_at DESC);
