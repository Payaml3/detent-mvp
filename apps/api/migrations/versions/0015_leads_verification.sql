-- 0015 DSH-10 access requests and DSH-12 integration verification.

-- DSH-10: a website access request is a lead of the operator organisation. The text fields are untrusted
-- (they come from a public form): they are shown escaped and never go to a model.
ALTER TABLE leads ADD COLUMN name        TEXT;
ALTER TABLE leads ADD COLUMN role        TEXT;
ALTER TABLE leads ADD COLUMN use_case    TEXT;
ALTER TABLE leads ADD COLUMN status      TEXT NOT NULL DEFAULT 'new'
    CHECK (status IN ('new', 'contacted', 'approved', 'declined'));
ALTER TABLE leads ADD COLUMN status_note TEXT;
ALTER TABLE leads ADD COLUMN status_by   TEXT;
ALTER TABLE leads ADD COLUMN status_at   TIMESTAMPTZ;
ALTER TABLE leads ADD COLUMN outbox_id   TEXT;  -- the email to the sales inbox, when one is configured
CREATE INDEX leads_org_created ON leads (org_id, created_at DESC, id DESC);
CREATE INDEX leads_org_email ON leads (org_id, lower(email), created_at DESC);

-- DSH-12: an owner's request to verify the integration, and a DekernAI admin's answer. Rows only grow: a
-- returned request stays, and the owner opens a new one.
CREATE TABLE verification_requests (
    id            TEXT PRIMARY KEY CHECK (id LIKE 'ver\_%'),
    org_id        TEXT NOT NULL REFERENCES organisations(id),
    requested_by  TEXT NOT NULL,
    requested_at  TIMESTAMPTZ NOT NULL,
    checklist     JSONB NOT NULL,
    status        TEXT NOT NULL DEFAULT 'requested' CHECK (status IN ('requested', 'verified', 'returned')),
    decided_by    TEXT,
    decided_at    TIMESTAMPTZ,
    note          TEXT,
    CHECK ((status = 'requested') = (decided_at IS NULL)),
    CHECK (status <> 'returned' OR length(coalesce(note, '')) >= 3)
);
-- At most one open request per organisation.
CREATE UNIQUE INDEX verification_requests_one_open ON verification_requests (org_id) WHERE status = 'requested';

CREATE FUNCTION verification_requests_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'verification_requests rows are never deleted' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status <> 'requested' THEN
        RAISE EXCEPTION 'a decided verification request is final' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.requested_by <> OLD.requested_by
       OR NEW.requested_at <> OLD.requested_at OR NEW.checklist <> OLD.checklist THEN
        RAISE EXCEPTION 'only the decision of a verification request can change' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER verification_requests_final BEFORE UPDATE OR DELETE ON verification_requests
    FOR EACH ROW EXECUTE FUNCTION verification_requests_guard();
