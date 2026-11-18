-- 0002 decision layer (slice S1). Forward-only.
SET search_path TO detent;

-- Travel-rule originator data comes from organisation settings, never from agents (D-03).
ALTER TABLE organisations ADD COLUMN registered_name    TEXT;
ALTER TABLE organisations ADD COLUMN registered_account TEXT;

-- Bank destinations keep a masked account (IBAN or sort code and account number), never the full one.
ALTER TABLE destinations ADD COLUMN account_masked TEXT;
CREATE INDEX destinations_by_address ON destinations (org_id, lower(address)) WHERE address IS NOT NULL;

-- G-08 (D-23): every API key is issued to a named user, who is the actor for audit and approvals.
ALTER TABLE api_keys ADD COLUMN user_id TEXT;
ALTER TABLE api_keys ADD CONSTRAINT api_keys_user_fk FOREIGN KEY (org_id, user_id) REFERENCES users(org_id, id);

-- Lookups the decision layer makes on every intent.
CREATE INDEX payment_intents_list ON payment_intents (org_id, created_at DESC, id DESC);
CREATE INDEX payment_intents_blocked ON payment_intents (org_id, counterparty_id, updated_at) WHERE status = 'BLOCKED';
CREATE INDEX decisions_by_payment ON decisions (org_id, payment_id, decided_at);
CREATE INDEX audit_events_by_subject ON audit_events (org_id, subject_id, seq);

-- Fixture rows use readable IDs (cpt_harbor, dst_quill_acct) in every organisation that is seeded with
-- them (demo, sandbox, tests), so these IDs are unique per organisation, not globally. Every foreign
-- key already references (org_id, id).
ALTER TABLE destinations   DROP CONSTRAINT destinations_pkey,   ADD PRIMARY KEY (org_id, id);
ALTER TABLE counterparties DROP CONSTRAINT counterparties_pkey, ADD PRIMARY KEY (org_id, id);
