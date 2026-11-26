-- 0001 baseline schema (FND-03). Source: spec/02-domain-model.md.
--
-- Conventions
--   * Every table has org_id NOT NULL (invariant 16). Child tables reference their parent with a
--     composite (org_id, id) foreign key, so a row can never point at another organisation's row.
--   * Money is amount_minor BIGINT plus currency (invariant 15). No float or numeric money columns.
--   * Status columns are TEXT with CHECK constraints listing the values from detent.domain.
--   * Exactly-once and idempotency guarantees are partial unique indexes (invariant 2).
--   * Terminal payment states are frozen by trigger (invariant 4); audit and ledger rows are
--     append-only by trigger (invariant 12).

CREATE SCHEMA IF NOT EXISTS detent;
SET search_path TO detent;

-- ------------------------------------------------------------------------------------------------
-- Organisations, users, keys

CREATE TABLE organisations (
    id           TEXT PRIMARY KEY CHECK (id LIKE 'org\_%'),
    org_id       TEXT GENERATED ALWAYS AS (id) STORED NOT NULL,
    name         TEXT NOT NULL,
    mode         TEXT NOT NULL DEFAULT 'shadow' CHECK (mode IN ('shadow','assist','auto')),
    fail_safe    TEXT NOT NULL DEFAULT 'manual_queue' CHECK (fail_safe IN ('hold','manual_queue')),
    kind         TEXT NOT NULL DEFAULT 'demo' CHECK (kind IN ('demo','sandbox','test')),
    api_version  TEXT NOT NULL DEFAULT '2026-12-01',
    expires_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE users (
    id            TEXT PRIMARY KEY CHECK (id LIKE 'usr\_%'),
    org_id        TEXT NOT NULL REFERENCES organisations(id),
    email         TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('payments_lead','compliance_lead','reviewer','backup_owner','oncall','admin')),
    password_hash TEXT,
    created_at    TIMESTAMPTZ NOT NULL,
    UNIQUE (org_id, id),
    UNIQUE (org_id, email)
);

CREATE TABLE api_keys (
    id           TEXT PRIMARY KEY CHECK (id LIKE 'key\_%'),
    org_id       TEXT NOT NULL REFERENCES organisations(id),
    prefix       TEXT NOT NULL CHECK (prefix LIKE 'sk\_test\_%'),   -- sk_live_ keys can never exist
    hash         TEXT NOT NULL UNIQUE,
    scopes       TEXT[] NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ,
    expires_at   TIMESTAMPTZ,
    UNIQUE (org_id, id)
);

-- ------------------------------------------------------------------------------------------------
-- Counterparties and destinations (decision layer inputs)

CREATE TABLE counterparties (
    id                  TEXT PRIMARY KEY CHECK (id LIKE 'cpt\_%'),
    org_id              TEXT NOT NULL REFERENCES organisations(id),
    name                TEXT NOT NULL,
    kyb_status          TEXT NOT NULL CHECK (kyb_status IN ('verified','pending','failed','unknown')),
    allowlisted         BOOLEAN NOT NULL DEFAULT false,
    jurisdiction        TEXT,
    payment_count       INTEGER NOT NULL DEFAULT 0,
    median_amount_minor BIGINT,
    median_currency     VARCHAR(8),
    created_at          TIMESTAMPTZ NOT NULL,
    UNIQUE (org_id, id)
);

CREATE TABLE destinations (
    id              TEXT PRIMARY KEY CHECK (id LIKE 'dst\_%'),
    org_id          TEXT NOT NULL,
    counterparty_id TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('evm_wallet','bank_account')),
    network         TEXT NOT NULL,
    address         TEXT,
    iban_masked     TEXT,
    verified        BOOLEAN NOT NULL DEFAULT true,
    first_seen_at   TIMESTAMPTZ NOT NULL,
    last_changed_at TIMESTAMPTZ NOT NULL,
    last_changed_by TEXT,
    UNIQUE (org_id, id),
    FOREIGN KEY (org_id, counterparty_id) REFERENCES counterparties(org_id, id),
    CHECK ((kind = 'evm_wallet') = (address IS NOT NULL))
);

-- ------------------------------------------------------------------------------------------------
-- Mandates and policy versions

CREATE TABLE mandates (
    id          TEXT PRIMARY KEY CHECK (id LIKE 'mnd\_%'),
    org_id      TEXT NOT NULL REFERENCES organisations(id),
    agent_id    TEXT NOT NULL,
    version     INTEGER NOT NULL,
    payload     JSONB NOT NULL,
    signature   TEXT NOT NULL,
    valid_from  TIMESTAMPTZ NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    revoked_by  TEXT,
    created_at  TIMESTAMPTZ NOT NULL,
    UNIQUE (org_id, id)
);

CREATE TABLE policy_versions (
    id            TEXT PRIMARY KEY CHECK (id LIKE 'pol\_%'),
    org_id        TEXT NOT NULL REFERENCES organisations(id),
    version       INTEGER NOT NULL,
    content_hash  TEXT NOT NULL,
    yaml          TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('draft','active','superseded')),
    proposed_by   TEXT NOT NULL,
    approved_by   TEXT[] NOT NULL DEFAULT '{}',
    loosening     BOOLEAN NOT NULL DEFAULT false,
    attestation   TEXT,
    created_at    TIMESTAMPTZ NOT NULL,
    activated_at  TIMESTAMPTZ,
    UNIQUE (org_id, id),
    UNIQUE (org_id, version)
);
-- At most one active rule version per organisation.
CREATE UNIQUE INDEX one_active_policy ON policy_versions (org_id) WHERE status = 'active';

-- ------------------------------------------------------------------------------------------------
-- Payment intents, decisions, attempts (the payment ID for life: invariant 1)

CREATE TABLE payment_intents (
    id                   TEXT PRIMARY KEY CHECK (id LIKE 'pay\_%'),
    org_id               TEXT NOT NULL REFERENCES organisations(id),
    kind                 TEXT NOT NULL DEFAULT 'payout' CHECK (kind IN ('payout')),
    source               TEXT NOT NULL CHECK (source IN ('platform','agent')),
    mandate_id           TEXT,
    counterparty_id      TEXT,
    destination_id       TEXT,
    user_account_ref     TEXT,   -- payouts to the platform's own end users (no counterparty)
    amount_minor         BIGINT NOT NULL CHECK (amount_minor > 0),
    currency             VARCHAR(8) NOT NULL CHECK (currency IN ('USDC','GBP','EUR')),
    network_constraint   TEXT,
    allow_network_switch BOOLEAN NOT NULL DEFAULT false,
    reference            TEXT,
    notes                TEXT,
    travel_rule          JSONB,
    status               TEXT NOT NULL CHECK (status IN ('RECEIVED','BLOCKED','ESCALATED','READY','SHADOWED','HELD','SUBMITTED','UNKNOWN','CONFIRMED','FAILED','FAILED_FINAL','REJECTED','CANCELLED')),
    idempotency_key      TEXT NOT NULL,
    request_hash         TEXT NOT NULL,
    awaiting_send_click  BOOLEAN NOT NULL DEFAULT false,
    initiated_by         TEXT,
    created_at           TIMESTAMPTZ NOT NULL,
    updated_at           TIMESTAMPTZ NOT NULL,
    UNIQUE (org_id, id),
    FOREIGN KEY (org_id, mandate_id) REFERENCES mandates(org_id, id),
    FOREIGN KEY (org_id, counterparty_id) REFERENCES counterparties(org_id, id),
    FOREIGN KEY (org_id, destination_id) REFERENCES destinations(org_id, id),
    CHECK (source <> 'agent' OR mandate_id IS NOT NULL),
    CHECK ((counterparty_id IS NULL) <> (user_account_ref IS NULL))
);
CREATE UNIQUE INDEX idem_payment ON payment_intents (org_id, idempotency_key);

CREATE TABLE decisions (
    id                TEXT PRIMARY KEY CHECK (id LIKE 'dec\_%'),
    org_id            TEXT NOT NULL,
    payment_id        TEXT NOT NULL,
    outcome           TEXT NOT NULL CHECK (outcome IN ('EXECUTE','ESCALATE','BLOCK')),
    policy_version_id TEXT NOT NULL,
    policy_hash       TEXT NOT NULL,
    inputs_snapshot   JSONB NOT NULL,
    checks            JSONB NOT NULL,
    route             JSONB,
    approved_reasons  TEXT[] NOT NULL DEFAULT '{}',   -- reasons a human approved before this re-run
    decided_at        TIMESTAMPTZ NOT NULL,
    actor             TEXT NOT NULL,
    UNIQUE (org_id, id),
    FOREIGN KEY (org_id, payment_id) REFERENCES payment_intents(org_id, id),
    FOREIGN KEY (org_id, policy_version_id) REFERENCES policy_versions(org_id, id)
);

CREATE TABLE rails (
    id                          TEXT NOT NULL,
    org_id                      TEXT NOT NULL REFERENCES organisations(id),
    kind                        TEXT NOT NULL CHECK (kind IN ('evm','banksim','simchain')),
    network                     TEXT NOT NULL,
    chain_id                    INTEGER CHECK (chain_id IS NULL OR chain_id IN (84532, 11155111, 31337)),
    currency                    VARCHAR(8) NOT NULL CHECK (currency IN ('USDC','GBP','EUR')),
    enabled                     BOOLEAN NOT NULL DEFAULT true,
    weights                     JSONB,
    prefunded_daily_limit_minor BIGINT,
    PRIMARY KEY (org_id, id),
    CHECK ((kind = 'evm') = (chain_id IS NOT NULL))
);

CREATE TABLE attempts (
    id              TEXT PRIMARY KEY CHECK (id LIKE 'att\_%'),
    org_id          TEXT NOT NULL,
    payment_id      TEXT NOT NULL,
    attempt_no      INTEGER NOT NULL CHECK (attempt_no >= 1),
    rail_id         TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('CREATED','SUBMITTED','UNKNOWN','CONFIRMED','FAILED')),
    failure_class   TEXT CHECK (failure_class IN ('TECHNICAL_RETRYABLE','TECHNICAL_FINAL','REJECTED_BY_RAIL','TIMEOUT')),
    idempotency_key TEXT NOT NULL,
    from_address    TEXT,
    nonce           BIGINT,
    raw_tx          TEXT,     -- signed raw transaction, so a re-broadcast sends the same transaction
    tx_hash         TEXT,
    rail_reference  TEXT,
    created_at      TIMESTAMPTZ NOT NULL,
    submitted_at    TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    evidence        JSONB,
    UNIQUE (org_id, id),
    UNIQUE (payment_id, attempt_no),
    FOREIGN KEY (org_id, payment_id) REFERENCES payment_intents(org_id, id),
    FOREIGN KEY (org_id, rail_id) REFERENCES rails(org_id, id),
    -- TIMEOUT only ever leads to UNKNOWN (invariant 3): a FAILED attempt never carries it.
    CHECK (NOT (status = 'FAILED' AND failure_class = 'TIMEOUT')),
    CHECK (status <> 'FAILED' OR failure_class IS NOT NULL)
);
-- Invariant 2: one in-flight attempt and one confirmed attempt per payment.
CREATE UNIQUE INDEX one_inflight_attempt ON attempts (payment_id)
    WHERE status IN ('CREATED','SUBMITTED','UNKNOWN');
CREATE UNIQUE INDEX one_confirmed_attempt ON attempts (payment_id)
    WHERE status = 'CONFIRMED';
-- One transaction per nonce per wallet per chain (cancel-replacements get their own table, M3).
CREATE UNIQUE INDEX one_tx_per_nonce ON attempts (rail_id, from_address, nonce)
    WHERE nonce IS NOT NULL;

CREATE TABLE kill_switch (
    org_id      TEXT PRIMARY KEY REFERENCES organisations(id),
    engaged     BOOLEAN NOT NULL DEFAULT false,
    engaged_by  TEXT,
    engaged_at  TIMESTAMPTZ,
    released_by TEXT,
    released_at TIMESTAMPTZ
);

-- Daily caps and mandate totals (spec/04). One row per (org, scope, period); concurrent decisions
-- serialise on it with UPDATE ... RETURNING inside the decision transaction.
CREATE TABLE counters (
    org_id       TEXT NOT NULL REFERENCES organisations(id),
    scope        TEXT NOT NULL,       -- e.g. 'platform:USDC', 'counterparty:cpt_x:USDC', 'mandate:mnd_x'
    period       TEXT NOT NULL,       -- 'YYYY-MM-DD' for daily caps, 'all' for mandate totals
    currency     VARCHAR(8) NOT NULL CHECK (currency IN ('USDC','GBP','EUR')),
    amount_minor BIGINT NOT NULL DEFAULT 0 CHECK (amount_minor >= 0),
    count        INTEGER NOT NULL DEFAULT 0 CHECK (count >= 0),
    PRIMARY KEY (org_id, scope, period)
);

CREATE TABLE mandate_usage (
    org_id      TEXT NOT NULL,
    mandate_id  TEXT NOT NULL,
    total_minor BIGINT NOT NULL DEFAULT 0 CHECK (total_minor >= 0),
    count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (org_id, mandate_id),
    FOREIGN KEY (org_id, mandate_id) REFERENCES mandates(org_id, id)
);

-- ------------------------------------------------------------------------------------------------
-- Exceptions (operations layer)

CREATE TABLE exception_cases (
    id              TEXT PRIMARY KEY CHECK (id LIKE 'exc\_%'),
    org_id          TEXT NOT NULL,
    payment_id      TEXT,
    deposit_id      TEXT,
    type            TEXT NOT NULL,
    tier            INTEGER NOT NULL DEFAULT 1,
    reasons         TEXT[] NOT NULL DEFAULT '{}',
    owner_id        TEXT,
    backup_owner_id TEXT,
    deadline_at     TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('OPEN','HELD_OVERDUE','RESOLVED')),
    resolution      TEXT CHECK (resolution IN ('approved','rejected','cancelled','superseded')),
    resolution_reason TEXT,
    resolved_by     TEXT,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL,
    UNIQUE (org_id, id),
    FOREIGN KEY (org_id, payment_id) REFERENCES payment_intents(org_id, id),
    FOREIGN KEY (org_id, owner_id) REFERENCES users(org_id, id),
    FOREIGN KEY (org_id, backup_owner_id) REFERENCES users(org_id, id),
    CHECK ((payment_id IS NULL) <> (deposit_id IS NULL)),
    CHECK ((status = 'RESOLVED') = (resolution IS NOT NULL))
);
CREATE UNIQUE INDEX one_open_case ON exception_cases (payment_id)
    WHERE status IN ('OPEN','HELD_OVERDUE');
CREATE UNIQUE INDEX one_open_deposit_case ON exception_cases (deposit_id)
    WHERE status IN ('OPEN','HELD_OVERDUE');

CREATE TABLE case_events (
    id         TEXT PRIMARY KEY CHECK (id LIKE 'cev\_%'),
    org_id     TEXT NOT NULL,
    case_id    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    actor      TEXT NOT NULL,
    payload    JSONB NOT NULL DEFAULT '{}',
    at         TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (org_id, case_id) REFERENCES exception_cases(org_id, id)
);

-- ------------------------------------------------------------------------------------------------
-- Deposits

CREATE TABLE deposit_intents (
    id                    TEXT PRIMARY KEY CHECK (id LIKE 'dep\_%'),
    org_id                TEXT NOT NULL REFERENCES organisations(id),
    account_ref           TEXT NOT NULL,
    currency              VARCHAR(8) NOT NULL CHECK (currency IN ('USDC','GBP','EUR')),
    network               TEXT NOT NULL,
    expected_amount_minor BIGINT CHECK (expected_amount_minor IS NULL OR expected_amount_minor > 0),
    deposit_address       TEXT,
    reference             TEXT,
    status                TEXT NOT NULL CHECK (status IN ('OPEN','RECEIVED','CREDITED','EXCEPTION','EXPIRED')),
    idempotency_key       TEXT NOT NULL,
    request_hash          TEXT NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL,
    UNIQUE (org_id, id)
);
CREATE UNIQUE INDEX idem_deposit ON deposit_intents (org_id, idempotency_key);

CREATE TABLE inbound_transfers (
    id            TEXT PRIMARY KEY CHECK (id LIKE 'inb\_%'),
    org_id        TEXT NOT NULL REFERENCES organisations(id),
    rail_id       TEXT NOT NULL,
    tx_hash       TEXT NOT NULL,
    log_index     INTEGER NOT NULL DEFAULT 0,
    from_address  TEXT,
    to_address    TEXT,
    amount_minor  BIGINT NOT NULL CHECK (amount_minor > 0),
    token         TEXT NOT NULL,
    confirmations INTEGER NOT NULL DEFAULT 0,
    seen_at       TIMESTAMPTZ NOT NULL,
    UNIQUE (org_id, id)
);
CREATE UNIQUE INDEX one_inbound ON inbound_transfers (rail_id, tx_hash, log_index);

-- ------------------------------------------------------------------------------------------------
-- Ledger (append-only, balanced double entry)

CREATE TABLE accounts (
    id       TEXT PRIMARY KEY CHECK (id LIKE 'acc\_%'),
    org_id   TEXT NOT NULL REFERENCES organisations(id),
    kind     TEXT NOT NULL CHECK (kind IN ('user_balance','platform_operating','rail_clearing','fees','suspense')),
    ref      TEXT NOT NULL,
    currency VARCHAR(8) NOT NULL CHECK (currency IN ('USDC','GBP','EUR')),
    UNIQUE (org_id, id),
    UNIQUE (org_id, kind, ref, currency)
);

CREATE TABLE journal_entries (
    id          TEXT PRIMARY KEY CHECK (id LIKE 'jrn\_%'),
    org_id      TEXT NOT NULL REFERENCES organisations(id),
    kind        TEXT NOT NULL,
    payment_id  TEXT,
    deposit_id  TEXT,
    adjustment_of TEXT,          -- corrections are new entries referencing the original
    memo        TEXT,
    created_at  TIMESTAMPTZ NOT NULL,
    UNIQUE (org_id, id)
);

CREATE TABLE postings (
    id           TEXT PRIMARY KEY CHECK (id LIKE 'pst\_%'),
    org_id       TEXT NOT NULL,
    journal_id   TEXT NOT NULL,
    account_id   TEXT NOT NULL,
    direction    TEXT NOT NULL CHECK (direction IN ('debit','credit')),
    amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
    currency     VARCHAR(8) NOT NULL CHECK (currency IN ('USDC','GBP','EUR')),
    FOREIGN KEY (org_id, journal_id) REFERENCES journal_entries(org_id, id),
    FOREIGN KEY (org_id, account_id) REFERENCES accounts(org_id, id)
);

CREATE TABLE credits (
    id                  TEXT PRIMARY KEY CHECK (id LIKE 'crd\_%'),
    org_id              TEXT NOT NULL,
    inbound_transfer_id TEXT NOT NULL,
    deposit_intent_id   TEXT,
    account_ref         TEXT NOT NULL,
    amount_minor        BIGINT NOT NULL CHECK (amount_minor > 0),
    currency            VARCHAR(8) NOT NULL CHECK (currency IN ('USDC','GBP','EUR')),
    journal_id          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (org_id, inbound_transfer_id) REFERENCES inbound_transfers(org_id, id),
    FOREIGN KEY (org_id, deposit_intent_id) REFERENCES deposit_intents(org_id, id),
    FOREIGN KEY (org_id, journal_id) REFERENCES journal_entries(org_id, id)
);
CREATE UNIQUE INDEX one_credit ON credits (inbound_transfer_id);

CREATE TABLE recon_runs (
    id          TEXT PRIMARY KEY CHECK (id LIKE 'rec\_%'),
    org_id      TEXT NOT NULL REFERENCES organisations(id),
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    stats       JSONB NOT NULL DEFAULT '{}',
    UNIQUE (org_id, id)
);

CREATE TABLE recon_breaks (
    id           TEXT PRIMARY KEY CHECK (id LIKE 'brk\_%'),
    org_id       TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    subject      JSONB NOT NULL,
    proposed_fix JSONB,
    rationale    JSONB,
    status       TEXT NOT NULL CHECK (status IN ('OPEN','APPROVED','REJECTED','APPLIED')),
    approved_by  TEXT,
    created_at   TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (org_id, run_id) REFERENCES recon_runs(org_id, id)
);

-- ------------------------------------------------------------------------------------------------
-- Agents, audit, outbox, webhooks, logs, jobs, incidents, onboarding

CREATE TABLE agent_calls (
    id             TEXT PRIMARY KEY CHECK (id LIKE 'agc\_%'),
    org_id         TEXT NOT NULL REFERENCES organisations(id),
    kind           TEXT NOT NULL,
    subject_id     TEXT,
    model          TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_hash     TEXT NOT NULL,
    raw_output     TEXT,
    parsed         JSONB,
    tokens_in      INTEGER,
    tokens_out     INTEGER,
    latency_ms     INTEGER,
    created_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE audit_events (
    id          TEXT PRIMARY KEY CHECK (id LIKE 'evt\_%'),
    org_id      TEXT NOT NULL REFERENCES organisations(id),
    seq         BIGINT NOT NULL CHECK (seq >= 1),
    at          TIMESTAMPTZ NOT NULL,
    actor       TEXT NOT NULL,
    actor_role  TEXT,
    kind        TEXT NOT NULL,
    subject_id  TEXT,
    payload     JSONB NOT NULL DEFAULT '{}',
    prev_hash   CHAR(64) NOT NULL,
    hash        CHAR(64) NOT NULL UNIQUE,
    UNIQUE (org_id, seq)
);

-- Head of each organisation's hash chain. Appending locks this row, which serialises writers.
CREATE TABLE audit_heads (
    org_id TEXT PRIMARY KEY REFERENCES organisations(id),
    seq    BIGINT NOT NULL,
    hash   CHAR(64) NOT NULL
);

CREATE TABLE outbox (
    id         TEXT PRIMARY KEY CHECK (id LIKE 'obx\_%'),
    org_id     TEXT NOT NULL REFERENCES organisations(id),
    channel    TEXT NOT NULL CHECK (channel IN ('email_mock','webhook')),
    recipient  TEXT NOT NULL,
    template   TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    sent_at    TIMESTAMPTZ
);

CREATE TABLE webhook_endpoints (
    id          TEXT PRIMARY KEY CHECK (id LIKE 'whe\_%'),
    org_id      TEXT NOT NULL REFERENCES organisations(id),
    url         TEXT NOT NULL,
    event_types TEXT[] NOT NULL,
    secret_hash TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    disabled_at TIMESTAMPTZ,
    UNIQUE (org_id, id)
);

CREATE TABLE webhook_events (
    id         TEXT PRIMARY KEY CHECK (id LIKE 'evt\_%'),
    org_id     TEXT NOT NULL REFERENCES organisations(id),
    type       TEXT NOT NULL,
    subject_id TEXT,
    sequence   BIGINT NOT NULL,
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (org_id, id)
);

CREATE TABLE webhook_deliveries (
    id          TEXT PRIMARY KEY CHECK (id LIKE 'whd\_%'),
    org_id      TEXT NOT NULL,
    endpoint_id TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    attempt     INTEGER NOT NULL DEFAULT 1,
    status_code INTEGER,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (org_id, endpoint_id) REFERENCES webhook_endpoints(org_id, id),
    FOREIGN KEY (org_id, event_id) REFERENCES webhook_events(org_id, id)
);

CREATE TABLE request_logs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    org_id          TEXT NOT NULL REFERENCES organisations(id),
    key_id          TEXT,
    method          TEXT NOT NULL,
    path            TEXT NOT NULL,
    status          INTEGER NOT NULL,
    latency_ms      INTEGER NOT NULL,
    idempotency_key TEXT,
    payment_id      TEXT,
    request_id      TEXT NOT NULL,
    at              TIMESTAMPTZ NOT NULL
);
CREATE INDEX request_logs_org_at ON request_logs (org_id, at DESC);

CREATE TABLE idempotency_records (
    org_id       TEXT NOT NULL REFERENCES organisations(id),
    key          TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response     JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (org_id, key)
);

CREATE TABLE jobs (
    id           TEXT PRIMARY KEY CHECK (id LIKE 'job\_%'),
    org_id       TEXT NOT NULL REFERENCES organisations(id),
    kind         TEXT NOT NULL,
    dedupe_key   TEXT,                -- enqueueing the same logical job twice is a no-op
    payment_id   TEXT,                -- for logs
    payload      JSONB NOT NULL DEFAULT '{}',
    run_at       TIMESTAMPTZ NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 8,
    locked_by    TEXT,
    locked_until TIMESTAMPTZ,
    last_error   TEXT,
    created_at   TIMESTAMPTZ NOT NULL,
    done_at      TIMESTAMPTZ,
    dead_at      TIMESTAMPTZ
);
CREATE UNIQUE INDEX jobs_dedupe ON jobs (org_id, kind, dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX jobs_due ON jobs (run_at) WHERE done_at IS NULL AND dead_at IS NULL;

CREATE TABLE incidents (
    id          TEXT PRIMARY KEY CHECK (id LIKE 'inc\_%'),
    org_id      TEXT NOT NULL REFERENCES organisations(id),
    severity    INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 4),
    trigger     TEXT NOT NULL,
    opened_at   TIMESTAMPTZ NOT NULL,
    notified_at TIMESTAMPTZ,
    root_cause  TEXT
);

CREATE TABLE invites (
    id          TEXT PRIMARY KEY CHECK (id LIKE 'inv\_%'),
    org_id      TEXT NOT NULL REFERENCES organisations(id),
    email       TEXT NOT NULL,
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL
);

-- Website access requests arrive before an organisation exists; they belong to the Dekernai
-- operator organisation (seeded as org_detent).
CREATE TABLE leads (
    id         TEXT PRIMARY KEY CHECK (id LIKE 'lead\_%'),
    org_id     TEXT NOT NULL REFERENCES organisations(id),
    email      TEXT NOT NULL,
    company    TEXT,
    message    TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

-- Demo-mode clock offset (FND-05). Only read when APP_ENV=demo.
CREATE TABLE demo_clock (
    org_id         TEXT PRIMARY KEY REFERENCES organisations(id),
    offset_seconds BIGINT NOT NULL DEFAULT 0 CHECK (offset_seconds >= 0)
);

-- ------------------------------------------------------------------------------------------------
-- Triggers

-- Invariant 4 (and spec/02): once a payment is terminal, its status never changes again.
-- Keep this list equal to detent.domain.states.TERMINAL (a test checks it).
CREATE FUNCTION forbid_terminal_status_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('CONFIRMED','BLOCKED','REJECTED','CANCELLED','FAILED_FINAL','SHADOWED')
       AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'payment % is terminal (%); status cannot change to %', OLD.id, OLD.status, NEW.status
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER payment_terminal_guard BEFORE UPDATE OF status ON payment_intents
    FOR EACH ROW EXECUTE FUNCTION forbid_terminal_status_change();

-- Attempts: CONFIRMED and FAILED are final for an attempt. A retry is a new attempt row.
CREATE FUNCTION forbid_terminal_attempt_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('CONFIRMED','FAILED') AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'attempt % is final (%)', OLD.id, OLD.status USING ERRCODE = 'check_violation';
    END IF;
    -- Invariant 3: an UNKNOWN attempt never becomes FAILED without evidence.
    IF OLD.status = 'UNKNOWN' AND NEW.status = 'FAILED' AND NEW.evidence IS NULL THEN
        RAISE EXCEPTION 'attempt % cannot go UNKNOWN -> FAILED without evidence', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER attempt_terminal_guard BEFORE UPDATE ON attempts
    FOR EACH ROW EXECUTE FUNCTION forbid_terminal_attempt_change();

-- Invariant 12 and "never edit or delete ledger entries": append-only tables.
CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER journal_entries_append_only BEFORE UPDATE OR DELETE ON journal_entries
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER journal_entries_no_truncate BEFORE TRUNCATE ON journal_entries
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER postings_append_only BEFORE UPDATE OR DELETE ON postings
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER postings_no_truncate BEFORE TRUNCATE ON postings
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();

-- Policy versions are immutable after activation, except for the status moving active -> superseded.
CREATE FUNCTION freeze_active_policy() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'policy version % is % and cannot be deleted', OLD.id, OLD.status;
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'superseded' THEN
        RAISE EXCEPTION 'policy version % is superseded and immutable', OLD.id;
    END IF;
    IF OLD.status = 'active' AND (
        NEW.status <> 'superseded' OR NEW.yaml IS DISTINCT FROM OLD.yaml
        OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR NEW.version <> OLD.version
        OR NEW.approved_by IS DISTINCT FROM OLD.approved_by OR NEW.attestation IS DISTINCT FROM OLD.attestation) THEN
        RAISE EXCEPTION 'policy version % is active; only active -> superseded is allowed', OLD.id;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER policy_versions_freeze BEFORE UPDATE OR DELETE ON policy_versions
    FOR EACH ROW EXECUTE FUNCTION freeze_active_policy();
