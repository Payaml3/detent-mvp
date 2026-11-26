-- P2 group 2: the keys page (DSH-04), usage metering (LED-08, DSH-08) and sandbox quotas (SBX-02).

-- DSH-04: a key's name, who created it, and the roll chain (the old key keeps working until its overlap ends).
ALTER TABLE api_keys
    ADD COLUMN name        TEXT CHECK (name IS NULL OR length(name) BETWEEN 1 AND 80),
    ADD COLUMN created_by  TEXT,
    ADD COLUMN rolled_from TEXT,
    ADD COLUMN rolled_to   TEXT;
CREATE INDEX api_keys_by_org ON api_keys (org_id, created_at DESC);

-- LED-08: daily counts per organisation (UTC days); a month is the sum of its days.
CREATE TABLE usage_daily (
    org_id TEXT NOT NULL REFERENCES organisations(id),
    day    DATE NOT NULL,
    metric TEXT NOT NULL CHECK (metric IN ('api_calls', 'payments_decided', 'agent_investigations')),
    count  BIGINT NOT NULL DEFAULT 0 CHECK (count >= 0),
    PRIMARY KEY (org_id, day, metric)
);

-- SBX-02: daily quotas. NULL means no quota (the demo and test organisations); client and evaluation
-- organisations get the spec/08 defaults when they are created.
ALTER TABLE organisations
    ADD COLUMN daily_payment_quota       INTEGER CHECK (daily_payment_quota IS NULL OR daily_payment_quota > 0),
    ADD COLUMN daily_investigation_quota INTEGER CHECK (daily_investigation_quota IS NULL OR daily_investigation_quota > 0);
