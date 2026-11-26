-- P2 group 3: the simulated chain rail (RAL-11) and real test-network mode (SBX-03).

-- RAL-11, SBX-03: which rails a sandbox organisation's USDC payouts use. 'simulated' (the default for client
-- and evaluation organisations) runs base-sepolia and eth-sepolia on the in-database simulated chain;
-- 'testnet' sends real test-network transactions from the shared faucet wallet. Existing demo and test
-- organisations keep 'testnet', so the live demo and the chain tests are unchanged.
ALTER TABLE organisations
    ADD COLUMN sandbox_rails TEXT NOT NULL DEFAULT 'testnet' CHECK (sandbox_rails IN ('simulated', 'testnet'));

-- RAL-11: the simulated chain's own record of what it was sent, as a chain would keep it. Each row is a
-- transaction: a signed-transaction hash, the sender's nonce, and a block number (seq). Rows are only ever
-- added: a simulated chain never forgets a transaction.
CREATE TABLE simchain_transfers (
    org_id       TEXT NOT NULL REFERENCES organisations(id),
    rail_id      TEXT NOT NULL,
    tx_hash      TEXT NOT NULL CHECK (tx_hash ~ '^0x[0-9a-f]{64}$'),
    seq          BIGINT GENERATED ALWAYS AS IDENTITY,
    from_address TEXT NOT NULL,
    to_address   TEXT NOT NULL,
    nonce        BIGINT NOT NULL CHECK (nonce >= 0),
    amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
    outcome      TEXT NOT NULL CHECK (outcome IN ('confirmed', 'reverted')),
    test_value   TEXT,
    attempt_id   TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL,
    visible_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (org_id, rail_id, tx_hash),
    UNIQUE (org_id, rail_id, from_address, nonce)
);
CREATE INDEX simchain_transfers_seq ON simchain_transfers (org_id, rail_id, seq);
CREATE FUNCTION simchain_transfers_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'simchain_transfers is append-only' USING ERRCODE = 'check_violation';
END $$;
CREATE TRIGGER simchain_transfers_no_change BEFORE UPDATE OR DELETE ON simchain_transfers
    FOR EACH ROW EXECUTE FUNCTION simchain_transfers_append_only();
