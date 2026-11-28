-- Slice U (D-40): payouts to the platform's own end users (USR-01, G-10).
-- One destination per user account. The platform supplies a typed user_verified flag, stored with who set it
-- and when. A destination belongs to exactly one owner: a counterparty or a user account.

CREATE TABLE user_accounts (
    org_id          TEXT NOT NULL REFERENCES organisations(id),
    ref             TEXT NOT NULL CHECK (length(ref) BETWEEN 1 AND 128),
    holder_name     TEXT,                 -- the platform's own name for the user, for screening and travel rule
    user_verified   BOOLEAN NOT NULL,     -- the platform's KYC result; false escalates USER_NOT_VERIFIED
    verified_set_by TEXT NOT NULL,
    verified_set_at TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (org_id, ref)
);

ALTER TABLE destinations ALTER COLUMN counterparty_id DROP NOT NULL;
ALTER TABLE destinations ADD COLUMN user_account_ref TEXT;
ALTER TABLE destinations ADD CONSTRAINT destinations_one_owner
    CHECK ((counterparty_id IS NULL) <> (user_account_ref IS NULL));
ALTER TABLE destinations ADD CONSTRAINT destinations_user_account
    FOREIGN KEY (org_id, user_account_ref) REFERENCES user_accounts(org_id, ref);
-- G-10: one destination per user account. Registering a different one replaces it in place.
CREATE UNIQUE INDEX one_destination_per_user ON destinations (org_id, user_account_ref)
    WHERE user_account_ref IS NOT NULL;

ALTER TABLE payment_intents ADD CONSTRAINT payment_intents_user_account
    FOREIGN KEY (org_id, user_account_ref) REFERENCES user_accounts(org_id, ref);
CREATE INDEX payment_intents_blocked_user ON payment_intents (org_id, user_account_ref, updated_at)
    WHERE status = 'BLOCKED' AND user_account_ref IS NOT NULL;
