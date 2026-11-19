-- 0006 operations around escalations (slice S6).

-- G-02 (approved 2026-11-19): a fictional contact so "the counterparty is told" has a recipient.
-- Messages only ever go to the outbox; nothing is emailed.
ALTER TABLE counterparties ADD COLUMN contact_email TEXT;

-- EXC-06, G-04 (approved 2026-11-19): the deadline length is kept so the backup owner gets the same
-- length from takeover; overdue_count says how many deadlines have passed (2 = with the payments lead).
ALTER TABLE exception_cases ADD COLUMN deadline_seconds INTEGER;
ALTER TABLE exception_cases ADD COLUMN overdue_count INTEGER NOT NULL DEFAULT 0 CHECK (overdue_count >= 0);
UPDATE exception_cases SET deadline_seconds = EXTRACT(EPOCH FROM deadline_at - created_at)::int
    WHERE deadline_seconds IS NULL;
CREATE INDEX exception_cases_due ON exception_cases (deadline_at) WHERE status IN ('OPEN','HELD_OVERDUE');

-- POL-07 (C-06, C-08 approved 2026-11-19): what the draft was based on, why it counts as loosening,
-- and who approved it in which role.
ALTER TABLE policy_versions ADD COLUMN base_version INTEGER;
ALTER TABLE policy_versions ADD COLUMN loosening_reasons JSONB NOT NULL DEFAULT '[]';
ALTER TABLE policy_versions ADD COLUMN approver_roles TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE policy_versions ADD COLUMN attested_by TEXT;
-- A draft nobody approves is withdrawn, never deleted: every version is kept (POL-07 AC4).
ALTER TABLE policy_versions DROP CONSTRAINT policy_versions_status_check;
ALTER TABLE policy_versions ADD CONSTRAINT policy_versions_status_check
    CHECK (status IN ('draft','active','superseded','withdrawn'));
-- At most one open draft per organisation keeps the review simple.
CREATE UNIQUE INDEX one_draft_policy ON policy_versions (org_id) WHERE status = 'draft';

CREATE OR REPLACE FUNCTION freeze_active_policy() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'policy version % is % and cannot be deleted (versions are kept)', OLD.id, OLD.status;
    END IF;
    IF OLD.status IN ('superseded','withdrawn') THEN
        RAISE EXCEPTION 'policy version % is % and immutable', OLD.id, OLD.status;
    END IF;
    IF OLD.status = 'draft' AND (NEW.yaml IS DISTINCT FROM OLD.yaml
        OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR NEW.version <> OLD.version) THEN
        RAISE EXCEPTION 'policy version % is a draft under review; propose a new draft to change it', OLD.id;
    END IF;
    IF OLD.status = 'active' AND (
        NEW.status <> 'superseded' OR NEW.yaml IS DISTINCT FROM OLD.yaml
        OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR NEW.version <> OLD.version
        OR NEW.approved_by IS DISTINCT FROM OLD.approved_by OR NEW.attestation IS DISTINCT FROM OLD.attestation) THEN
        RAISE EXCEPTION 'policy version % is active; only active -> superseded is allowed', OLD.id;
    END IF;
    RETURN NEW;
END $$;

-- EXE-09 (C-09 approved 2026-11-19): a mode change is proposed by one lead and approved by the other.
CREATE TABLE mode_changes (
    id            TEXT PRIMARY KEY CHECK (id LIKE 'mch\_%'),
    org_id        TEXT NOT NULL REFERENCES organisations(id),
    from_mode     TEXT NOT NULL CHECK (from_mode IN ('shadow','assist','auto')),
    to_mode       TEXT NOT NULL CHECK (to_mode IN ('shadow','assist','auto')),
    reason        TEXT NOT NULL,
    proposed_by   TEXT NOT NULL,
    proposed_role TEXT NOT NULL,
    approved_by   TEXT,
    approved_role TEXT,
    status        TEXT NOT NULL CHECK (status IN ('proposed','applied','withdrawn')),
    created_at    TIMESTAMPTZ NOT NULL,
    decided_at    TIMESTAMPTZ,
    UNIQUE (org_id, id),
    CHECK (approved_by IS NULL OR approved_by <> proposed_by),
    CHECK ((status = 'applied') = (approved_by IS NOT NULL))
);
CREATE UNIQUE INDEX one_open_mode_change ON mode_changes (org_id) WHERE status = 'proposed';

-- EXC-03: the investigation agent's output is stored per case.
CREATE INDEX agent_calls_subject ON agent_calls (org_id, kind, subject_id);

-- EXE-09, G-09: who clicked Send in Assist mode. Once a person confirmed, a technical retry of the
-- same payment does not need a second click; a payment in Shadow mode is never sent.
ALTER TABLE payment_intents ADD COLUMN send_confirmed_by TEXT;
