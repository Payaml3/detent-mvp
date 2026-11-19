-- 0005 agents and mandates (slice S5). Forward-only.
SET search_path TO detent;

-- AGT-03 / spec/05: an agent's key is bound to one mandate. It can only create agent intents under it.
ALTER TABLE api_keys ADD COLUMN mandate_id TEXT;
ALTER TABLE api_keys ADD CONSTRAINT api_keys_mandate_fk FOREIGN KEY (org_id, mandate_id) REFERENCES mandates(org_id, id);

-- Mandate IDs from fixtures (mnd_demo_ap_agent) repeat per organisation, like counterparties.
ALTER TABLE mandates DROP CONSTRAINT mandates_pkey, ADD PRIMARY KEY (org_id, id);

-- AGT-01/02/05: a proposal is the instruction agent's call; a person resolves its flags before it can be
-- submitted, and the intent it became is linked back.
ALTER TABLE agent_calls ADD COLUMN status TEXT NOT NULL DEFAULT 'recorded'
    CHECK (status IN ('recorded','needs_human','submitted'));
ALTER TABLE agent_calls ADD COLUMN resolution JSONB;
ALTER TABLE agent_calls ADD COLUMN resolved_by TEXT;
ALTER TABLE agent_calls ADD COLUMN payment_id TEXT;
ALTER TABLE agent_calls ADD COLUMN served_model TEXT;
ALTER TABLE agent_calls ADD COLUMN source TEXT NOT NULL DEFAULT 'model'
    CHECK (source IN ('model','recording','replay'));
ALTER TABLE agent_calls ADD CONSTRAINT agent_calls_org_id_key UNIQUE (org_id, id);
CREATE INDEX agent_calls_by_day ON agent_calls (org_id, created_at);
