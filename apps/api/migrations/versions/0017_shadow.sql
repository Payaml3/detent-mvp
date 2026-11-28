-- 0017 (slice L group 2): shadow imports (SHD-01, SHD-04), the shadow-phase report (SHD-02), mode-gate
-- sign-offs (SHD-03) and production-mode requests (DSH-13).

-- SHD-01, SHD-04: one import of a platform's export. The per-import salt that hashes names and account
-- identifiers is never stored, so hashes match within one import and can't be linked across imports.
CREATE TABLE shadow_imports (
    id                TEXT PRIMARY KEY CHECK (id LIKE 'shi\_%'),
    org_id            TEXT NOT NULL REFERENCES organisations(id),
    label             TEXT NOT NULL,
    mapping           JSONB NOT NULL,
    policy_version_id TEXT NOT NULL,
    policy_version    INTEGER NOT NULL,
    rows_read         INTEGER NOT NULL CHECK (rows_read >= 0),
    rows_decided      INTEGER NOT NULL CHECK (rows_decided >= 0),
    rows_invalid      INTEGER NOT NULL CHECK (rows_invalid >= 0),
    period_from       TIMESTAMPTZ,
    period_to         TIMESTAMPTZ,
    created_by        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL,
    UNIQUE (org_id, id),
    FOREIGN KEY (org_id, policy_version_id) REFERENCES policy_versions(org_id, id)
);

-- One row of the export, as decided. No raw name, address or account number is ever stored: the
-- counterparty, destination and payee text are kept only as salted hashes (SHD-04), and checks keep their
-- result and reason but not their evidence. Nothing here is ever sent: there is no payment intent.
CREATE TABLE shadow_rows (
    id                 TEXT PRIMARY KEY CHECK (id LIKE 'shr\_%'),
    org_id             TEXT NOT NULL,
    import_id          TEXT NOT NULL,
    row_no             INTEGER NOT NULL CHECK (row_no >= 1),
    platform_ref       TEXT,
    occurred_at        TIMESTAMPTZ,
    direction          TEXT CHECK (direction IN ('payout','deposit')),
    amount_minor       BIGINT CHECK (amount_minor IS NULL OR amount_minor > 0),
    currency           VARCHAR(8) CHECK (currency IS NULL OR currency IN ('USDC','GBP','EUR')),
    counterparty_id    TEXT,          -- the registry's own ID when the export's reference matches one
    counterparty_hash  TEXT,
    destination_hash   TEXT,
    payee_hash         TEXT,
    network            TEXT,
    platform_decision  TEXT CHECK (platform_decision IN ('approved','held','rejected')),
    fee_minor          BIGINT CHECK (fee_minor IS NULL OR fee_minor >= 0),
    outcome            TEXT CHECK (outcome IN ('EXECUTE','ESCALATE','BLOCK')),
    reasons            TEXT[] NOT NULL DEFAULT '{}',
    checks             JSONB NOT NULL DEFAULT '[]',
    problems           TEXT[] NOT NULL DEFAULT '{}',
    simulated_rail     TEXT,
    simulated_fee_minor BIGINT,
    UNIQUE (org_id, id),
    UNIQUE (import_id, row_no),
    FOREIGN KEY (org_id, import_id) REFERENCES shadow_imports(org_id, id),
    CHECK ((outcome IS NULL) OR (direction = 'payout' AND cardinality(problems) = 0))
);
CREATE INDEX shadow_rows_by_import ON shadow_rows (org_id, import_id, row_no);

-- Imports and their rows are evidence for a mode gate: append-only.
CREATE FUNCTION shadow_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'check_violation';
END $$;
CREATE TRIGGER shadow_imports_no_change BEFORE UPDATE OR DELETE ON shadow_imports
    FOR EACH ROW EXECUTE FUNCTION shadow_append_only();
CREATE TRIGGER shadow_rows_no_change BEFORE UPDATE OR DELETE ON shadow_rows
    FOR EACH ROW EXECUTE FUNCTION shadow_append_only();

-- SHD-03: the gate threshold (agreement in basis points; unsafe approvals must be zero). Founder D-41:
-- 95.00% agreement over 30 days and zero unsafe approvals.
ALTER TABLE organisations ADD COLUMN gate_agreement_bp INTEGER NOT NULL DEFAULT 9500
    CHECK (gate_agreement_bp BETWEEN 0 AND 10000);
-- A production organisation (DSH-13) moves up only on a signed, passed gate. The prototype has none: a
-- production request is recorded and nothing is switched, so this stays false until production exists.
ALTER TABLE organisations ADD COLUMN production BOOLEAN NOT NULL DEFAULT false;

-- SHD-03: a mode-gate report, frozen when it is created, and the two sign-offs (payments lead, then or
-- before the compliance lead, two different people). A mode change upward names the gate it relies on.
CREATE TABLE mode_gates (
    id                 TEXT PRIMARY KEY CHECK (id LIKE 'mgt\_%'),
    org_id             TEXT NOT NULL REFERENCES organisations(id),
    from_mode          TEXT NOT NULL CHECK (from_mode IN ('shadow','assist')),
    to_mode            TEXT NOT NULL CHECK (to_mode IN ('assist','auto')),
    period_from        TIMESTAMPTZ NOT NULL,
    period_to          TIMESTAMPTZ NOT NULL,
    compared           INTEGER NOT NULL CHECK (compared >= 0),
    agreed             INTEGER NOT NULL CHECK (agreed >= 0 AND agreed <= compared),
    unsafe_approvals   INTEGER NOT NULL CHECK (unsafe_approvals >= 0),
    threshold_bp       INTEGER NOT NULL,
    passed             BOOLEAN NOT NULL,
    report             JSONB NOT NULL,
    created_by         TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL,
    payments_lead_id   TEXT,
    payments_lead_at   TIMESTAMPTZ,
    compliance_lead_id TEXT,
    compliance_lead_at TIMESTAMPTZ,
    mode_change_id     TEXT,
    UNIQUE (org_id, id),
    CHECK (payments_lead_id IS NULL OR compliance_lead_id IS NULL OR payments_lead_id <> compliance_lead_id),
    CHECK (passed OR (payments_lead_id IS NULL AND compliance_lead_id IS NULL))
);
ALTER TABLE mode_changes ADD COLUMN gate_id TEXT;

-- DSH-13: a request to switch to production. In the prototype it is recorded and nothing changes.
CREATE TABLE production_requests (
    id            TEXT PRIMARY KEY CHECK (id LIKE 'prq\_%'),
    org_id        TEXT NOT NULL REFERENCES organisations(id),
    requested_by  TEXT NOT NULL,
    requested_at  TIMESTAMPTZ NOT NULL,
    policy_version INTEGER NOT NULL,
    verification_id TEXT NOT NULL,
    note          TEXT
);
CREATE UNIQUE INDEX one_production_request ON production_requests (org_id);
