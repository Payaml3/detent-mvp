-- 0007 one ledger, deposits credited once, reconciliation, replay (slice S7).

-- LED-01: every entry references a payment, a deposit or an adjustment, and is balanced per
-- currency at commit (deferred constraint trigger). Entries are already append-only (0001).
ALTER TABLE journal_entries ADD CONSTRAINT journal_has_reference
    CHECK (payment_id IS NOT NULL OR deposit_id IS NOT NULL OR adjustment_of IS NOT NULL);

CREATE FUNCTION journal_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bad RECORD;
BEGIN
    SELECT currency, sum(CASE WHEN direction='debit' THEN amount_minor ELSE -amount_minor END) AS net,
           count(*) AS n
      INTO bad
      FROM postings WHERE org_id = NEW.org_id AND journal_id = NEW.journal_id
     GROUP BY currency HAVING sum(CASE WHEN direction='debit' THEN amount_minor ELSE -amount_minor END) <> 0
     LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'journal % is unbalanced in % by %', NEW.journal_id, bad.currency, bad.net
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER postings_balanced AFTER INSERT ON postings
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION journal_balanced();

-- LED-03, G-11, G-21 (approved 2026-11-19): per-organisation deposit settings.
ALTER TABLE organisations ADD COLUMN deposit_tolerance_minor BIGINT NOT NULL DEFAULT 0
    CHECK (deposit_tolerance_minor >= 0);
ALTER TABLE organisations ADD COLUMN deposit_intent_days INTEGER NOT NULL DEFAULT 7
    CHECK (deposit_intent_days BETWEEN 1 AND 365);
ALTER TABLE deposit_intents ADD COLUMN expires_at TIMESTAMPTZ;
ALTER TABLE deposit_intents ADD COLUMN rail_id TEXT;
CREATE INDEX deposit_intents_address ON deposit_intents (org_id, lower(deposit_address)) WHERE deposit_address IS NOT NULL;
CREATE UNIQUE INDEX deposit_intents_reference ON deposit_intents (org_id, reference) WHERE reference IS NOT NULL;

-- LED-04, LED-05: what the watchers saw and what was decided about it.
ALTER TABLE inbound_transfers ADD COLUMN currency VARCHAR(8) CHECK (currency IN ('USDC','GBP','EUR'));
ALTER TABLE inbound_transfers ADD COLUMN network TEXT;
ALTER TABLE inbound_transfers ADD COLUMN block_number BIGINT;
ALTER TABLE inbound_transfers ADD COLUMN status TEXT NOT NULL DEFAULT 'RECEIVED'
    CHECK (status IN ('RECEIVED','CREDITED','SUSPENSE'));
ALTER TABLE inbound_transfers ADD COLUMN deposit_intent_id TEXT;
ALTER TABLE inbound_transfers ADD COLUMN decision JSONB;
ALTER TABLE inbound_transfers ADD COLUMN decided_at TIMESTAMPTZ;

CREATE TABLE watch_cursors (
    org_id     TEXT NOT NULL REFERENCES organisations(id),
    rail_id    TEXT NOT NULL,
    position   TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (org_id, rail_id)
);

-- LED-06, LED-07: external records (chain transfers and bank statement lines), one row each.
CREATE TABLE rail_records (
    id           TEXT NOT NULL,
    org_id       TEXT NOT NULL REFERENCES organisations(id),
    rail_id      TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    direction    TEXT NOT NULL CHECK (direction IN ('in','out')),
    amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
    currency     VARCHAR(8) NOT NULL CHECK (currency IN ('USDC','GBP','EUR')),
    party        TEXT,
    reference    TEXT,
    source       TEXT NOT NULL CHECK (source IN ('chain','statement')),
    occurred_at  TIMESTAMPTZ NOT NULL,
    statement_date DATE,
    PRIMARY KEY (org_id, id),
    UNIQUE (org_id, rail_id, external_id)
);

CREATE TABLE bank_statements (
    org_id         TEXT NOT NULL REFERENCES organisations(id),
    rail_id        TEXT NOT NULL,
    statement_date DATE NOT NULL,
    format         TEXT NOT NULL CHECK (format IN ('json','csv')),
    lines          INTEGER NOT NULL,
    imported_at    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (org_id, rail_id, statement_date)
);

ALTER TABLE recon_breaks ADD COLUMN kind TEXT;
ALTER TABLE recon_breaks ADD COLUMN subject_key TEXT;
ALTER TABLE recon_breaks ADD COLUMN case_id TEXT;
ALTER TABLE recon_breaks ADD COLUMN agent_call_id TEXT;
ALTER TABLE recon_breaks ADD COLUMN applied_journal_id TEXT;
ALTER TABLE recon_breaks ADD COLUMN decided_at TIMESTAMPTZ;
ALTER TABLE recon_breaks ADD COLUMN decision_reason TEXT;
-- A break stays one row across runs until it is resolved.
CREATE UNIQUE INDEX one_open_break ON recon_breaks (org_id, subject_key) WHERE status IN ('OPEN','APPROVED');

-- AUD-02: a replay mismatch raises an incident.
ALTER TABLE incidents ADD COLUMN subject_id TEXT;
ALTER TABLE incidents ADD COLUMN detail JSONB NOT NULL DEFAULT '{}';

-- AUD-02: replay compares against recorded decisions, so a decision's outcome, checks, inputs and rule
-- version can never change after it is written. Only the route (stored after routing) may be filled in.
CREATE FUNCTION freeze_decision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'decision % cannot be deleted', OLD.id;
    END IF;
    IF NEW.outcome IS DISTINCT FROM OLD.outcome OR NEW.checks IS DISTINCT FROM OLD.checks
       OR NEW.inputs_snapshot IS DISTINCT FROM OLD.inputs_snapshot
       OR NEW.policy_version_id IS DISTINCT FROM OLD.policy_version_id OR NEW.policy_hash IS DISTINCT FROM OLD.policy_hash
       OR NEW.approved_reasons IS DISTINCT FROM OLD.approved_reasons OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
       OR NEW.payment_id IS DISTINCT FROM OLD.payment_id OR NEW.org_id IS DISTINCT FROM OLD.org_id THEN
        RAISE EXCEPTION 'decision % is a record: only its route may be added', OLD.id;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER decisions_frozen BEFORE UPDATE OR DELETE ON decisions
    FOR EACH ROW EXECUTE FUNCTION freeze_decision();
