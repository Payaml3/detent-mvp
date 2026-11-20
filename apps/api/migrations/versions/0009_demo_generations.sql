-- 0009 (slice S9, CON-09): "reset demo data" starts a new data generation, as D-08 does for the sandbox.
-- Nothing is deleted: each generation is its own fictional organisation, seeded from the fixtures, and the
-- console shows the newest one. Earlier generations stay in the database with their audit log and ledger
-- intact (invariant 12), and their kill switch is engaged at reset so they can never send again.
CREATE TABLE demo_generations (
    base_org_id  TEXT NOT NULL,
    generation   INTEGER NOT NULL CHECK (generation >= 1),
    org_id       TEXT NOT NULL UNIQUE REFERENCES organisations(id),
    created_at   TIMESTAMPTZ NOT NULL,
    created_by   TEXT NOT NULL,
    PRIMARY KEY (base_org_id, generation)
);
-- Append-only, like the audit log: a generation is never edited or removed.
CREATE FUNCTION demo_generations_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'demo_generations is append-only' USING ERRCODE = 'check_violation';
END $$;
CREATE TRIGGER demo_generations_no_change BEFORE UPDATE OR DELETE ON demo_generations
    FOR EACH ROW EXECUTE FUNCTION demo_generations_append_only();
