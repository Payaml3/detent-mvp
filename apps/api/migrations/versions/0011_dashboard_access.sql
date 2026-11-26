-- P2 group 1: KYB-gated organisations, invites, sign-up, team roles, expiry and suspension
-- (DSH-01, DSH-02, DSH-03, DSH-11; spec/08 "Dashboard").

-- Organisations: a client organisation exists only after KYB and never expires; an evaluation
-- organisation (sandbox only, no KYB) always has an expiry. Either can be suspended, with a reason.
ALTER TABLE organisations DROP CONSTRAINT organisations_kind_check;
ALTER TABLE organisations ADD CONSTRAINT organisations_kind_check
    CHECK (kind IN ('demo', 'sandbox', 'test', 'client', 'evaluation'));
ALTER TABLE organisations
    ADD COLUMN kyb_reference    TEXT CHECK (kyb_reference IS NULL OR length(kyb_reference) BETWEEN 1 AND 100),
    ADD COLUMN kyb_approved_on  DATE,
    ADD COLUMN suspended_at     TIMESTAMPTZ,
    ADD COLUMN suspended_reason TEXT CHECK (suspended_reason IS NULL OR length(suspended_reason) BETWEEN 1 AND 500),
    ADD COLUMN created_by       TEXT;
ALTER TABLE organisations ADD CONSTRAINT organisations_client_needs_kyb
    CHECK (kind <> 'client' OR (kyb_reference IS NOT NULL AND kyb_approved_on IS NOT NULL AND expires_at IS NULL));
ALTER TABLE organisations ADD CONSTRAINT organisations_evaluation_expires
    CHECK (kind <> 'evaluation' OR expires_at IS NOT NULL);
ALTER TABLE organisations ADD CONSTRAINT organisations_suspension_has_reason
    CHECK ((suspended_at IS NULL) = (suspended_reason IS NULL));

-- Users: the spec/02 role list (C-14 adds auditor). A dashboard login is an email with a password;
-- one email signs in to one organisation.
ALTER TABLE users DROP CONSTRAINT users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN (
    'account_owner', 'admin', 'developer', 'payments_lead', 'compliance_lead', 'reviewer', 'backup_owner',
    'auditor', 'oncall'));
ALTER TABLE users
    ADD COLUMN email_verified_at   TIMESTAMPTZ,
    ADD COLUMN password_changed_at TIMESTAMPTZ,
    ADD COLUMN removed_at          TIMESTAMPTZ,
    ADD COLUMN removed_by          TEXT;
CREATE UNIQUE INDEX users_login_email ON users (lower(email))
    WHERE password_hash IS NOT NULL AND removed_at IS NULL;

-- Invites: single use, 7 days, one open invite per address and organisation.
ALTER TABLE invites
    ADD COLUMN role             TEXT NOT NULL CHECK (role IN (
        'account_owner', 'admin', 'developer', 'payments_lead', 'compliance_lead', 'reviewer', 'backup_owner',
        'auditor')),
    ADD COLUMN invited_by       TEXT NOT NULL,
    ADD COLUMN revoked_at       TIMESTAMPTZ,
    ADD COLUMN accepted_user_id TEXT;
ALTER TABLE invites ADD CONSTRAINT invites_expiry_after_creation CHECK (expires_at > created_at);
ALTER TABLE invites ADD CONSTRAINT invites_used_or_revoked CHECK (used_at IS NULL OR revoked_at IS NULL);
CREATE UNIQUE INDEX invites_one_open ON invites (org_id, lower(email)) WHERE used_at IS NULL AND revoked_at IS NULL;
CREATE INDEX invites_by_org ON invites (org_id, created_at DESC);

-- DSH-11: an organisation that has an account owner always keeps at least one. The service also locks
-- the organisation row first, so two owners can't demote each other at the same moment.
CREATE FUNCTION keep_an_account_owner() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.role = 'account_owner' AND OLD.removed_at IS NULL
       AND (NEW.role <> 'account_owner' OR NEW.removed_at IS NOT NULL)
       AND NOT EXISTS (SELECT 1 FROM users u WHERE u.org_id = OLD.org_id AND u.id <> OLD.id
                       AND u.role = 'account_owner' AND u.removed_at IS NULL) THEN
        RAISE EXCEPTION 'organisation % must keep at least one account owner', OLD.org_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER users_keep_an_account_owner BEFORE UPDATE OF role, removed_at ON users
    FOR EACH ROW EXECUTE FUNCTION keep_an_account_owner();

CREATE FUNCTION users_never_deleted() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'users are never deleted; set removed_at instead' USING ERRCODE = 'restrict_violation';
END $$;
CREATE TRIGGER users_no_delete BEFORE DELETE ON users FOR EACH ROW EXECUTE FUNCTION users_never_deleted();
