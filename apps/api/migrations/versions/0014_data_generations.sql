-- 0014 SBX-04 (C-04, D-08): a sandbox reset starts a new data generation. Nothing is deleted.
--
-- organisations.data_generation counts the resets. Each root row the API and dashboard list is stamped with
-- the organisation's generation as it is inserted (a trigger, so no insert can choose its own), and those
-- reads filter on the current one. Children (attempts, decisions, postings, case events, deliveries) are
-- reached through their root, so they follow it. Rows of earlier generations stay, and the append-only
-- triggers on ledger, audit and logs still apply.

ALTER TABLE organisations ADD COLUMN data_generation INTEGER NOT NULL DEFAULT 0
    CHECK (data_generation >= 0);

CREATE FUNCTION stamp_data_generation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.generation := COALESCE(
        (SELECT o.data_generation FROM organisations o WHERE o.id = NEW.org_id), 0);
    RETURN NEW;
END $$;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['payment_intents', 'deposit_intents', 'exception_cases', 'journal_entries',
                             'request_logs', 'webhook_events', 'recon_runs', 'recon_breaks'] LOOP
        EXECUTE format('ALTER TABLE %I ADD COLUMN generation INTEGER NOT NULL DEFAULT 0', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE INSERT ON %I FOR EACH ROW '
                       'EXECUTE FUNCTION stamp_data_generation()', t || '_stamp_generation', t);
    END LOOP;
END $$;

CREATE INDEX payment_intents_org_generation ON payment_intents (org_id, generation, created_at DESC, id DESC);
CREATE INDEX request_logs_org_generation ON request_logs (org_id, generation, id DESC);
