-- D-45: a requester signs the NDA on our own page (founder, 2026-11-28). The confirmation email carries a
-- one-time link; only its SHA-256 is stored. A signature is a permanent record: append-only, one per lead.
ALTER TABLE leads ADD COLUMN nda_token_hash TEXT UNIQUE CHECK (nda_token_hash IS NULL OR length(nda_token_hash) = 64);

CREATE TABLE nda_signatures (
    lead_id        TEXT PRIMARY KEY REFERENCES leads(id),
    org_id         TEXT NOT NULL REFERENCES organisations(id),
    nda_version    TEXT NOT NULL,
    nda_sha256     TEXT NOT NULL CHECK (length(nda_sha256) = 64),   -- the exact text that was shown
    signer_name    TEXT NOT NULL CHECK (length(signer_name) BETWEEN 1 AND 120),
    signer_title   TEXT NOT NULL CHECK (length(signer_title) BETWEEN 1 AND 120),
    signer_company TEXT NOT NULL CHECK (length(signer_company) BETWEEN 1 AND 160),
    signer_email   TEXT NOT NULL,
    signature_png  BYTEA NOT NULL CHECK (octet_length(signature_png) BETWEEN 100 AND 200000),
    ip             TEXT NOT NULL,
    user_agent     TEXT NOT NULL,
    signed_at      TIMESTAMPTZ NOT NULL
);

CREATE TRIGGER nda_signatures_append_only BEFORE UPDATE OR DELETE ON nda_signatures
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER nda_signatures_no_truncate BEFORE TRUNCATE ON nda_signatures
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();
