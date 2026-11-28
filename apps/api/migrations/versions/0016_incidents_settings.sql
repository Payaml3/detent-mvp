-- 0016 (slice L group 1): incident records (OPS-01), the invariant monitor (EXE-10) and the
-- two-person fail-safe change on the Settings screen (CON-10).

-- OPS-01: an incident has a title, a status, who opened it, and when it was resolved. The timeline is
-- incident_events, append-only like the audit log; notified_at and root_cause stay on the incident row.
ALTER TABLE incidents ADD COLUMN title TEXT NOT NULL DEFAULT '';
ALTER TABLE incidents ADD COLUMN status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved'));
ALTER TABLE incidents ADD COLUMN opened_by TEXT NOT NULL DEFAULT 'system';
ALTER TABLE incidents ADD COLUMN resolved_at TIMESTAMPTZ;
ALTER TABLE incidents ADD COLUMN resolved_by TEXT;
ALTER TABLE incidents ADD CONSTRAINT incidents_org_id_key UNIQUE (org_id, id);
ALTER TABLE incidents ADD CONSTRAINT incidents_resolved CHECK ((status = 'resolved') = (resolved_at IS NOT NULL));
-- EXE-10: one open incident per invariant finding, so a check every minute never opens a second one.
CREATE UNIQUE INDEX one_open_incident ON incidents (org_id, trigger, subject_id) WHERE status = 'open';

CREATE TABLE incident_events (
    id          TEXT PRIMARY KEY CHECK (id LIKE 'ine\_%'),
    org_id      TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('opened','notified','note','root_cause','replay_linked',
                                              'kill_switch_engaged','resolved')),
    actor       TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    at          TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (org_id, incident_id) REFERENCES incidents(org_id, id)
);
CREATE INDEX incident_events_by_incident ON incident_events (org_id, incident_id, at);
CREATE FUNCTION incident_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'incident_events is append-only' USING ERRCODE = 'check_violation';
END $$;
CREATE TRIGGER incident_events_no_change BEFORE UPDATE OR DELETE ON incident_events
    FOR EACH ROW EXECUTE FUNCTION incident_events_append_only();

-- CON-10: the fail-safe is changed the way the mode is (EXE-09, C-09): proposed by one lead and
-- approved by the other. mode_changes now names the setting it changes.
ALTER TABLE mode_changes ADD COLUMN setting TEXT NOT NULL DEFAULT 'mode' CHECK (setting IN ('mode','fail_safe'));
ALTER TABLE mode_changes DROP CONSTRAINT mode_changes_from_mode_check;
ALTER TABLE mode_changes DROP CONSTRAINT mode_changes_to_mode_check;
ALTER TABLE mode_changes ADD CONSTRAINT mode_changes_values CHECK (
    (setting = 'mode' AND from_mode IN ('shadow','assist','auto') AND to_mode IN ('shadow','assist','auto'))
    OR (setting = 'fail_safe' AND from_mode IN ('hold','manual_queue') AND to_mode IN ('hold','manual_queue'))
);
DROP INDEX one_open_mode_change;
CREATE UNIQUE INDEX one_open_mode_change ON mode_changes (org_id, setting) WHERE status = 'proposed';
