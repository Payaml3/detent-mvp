-- 0003 send once (slice S2). Forward-only.
SET search_path TO detent;

-- EVM rail settings. A sending wallet belongs to exactly one organisation's rail.
ALTER TABLE rails ADD COLUMN token_address   TEXT;
ALTER TABLE rails ADD COLUMN from_address    TEXT;
ALTER TABLE rails ADD COLUMN confirmations   INTEGER NOT NULL DEFAULT 1 CHECK (confirmations >= 1);
ALTER TABLE rails ADD COLUMN explorer_tx_url TEXT;

ALTER TABLE attempts ADD COLUMN explorer_url TEXT;

-- EXE-04: the nonce manager. The next nonce for a wallet is assigned under a row lock and written on
-- the attempt before the transaction is broadcast. `refused_reason` is set when the stored nonce and
-- the chain's pending count disagree; sending from that wallet stops until someone looks.
CREATE TABLE wallet_nonces (
    org_id         TEXT NOT NULL REFERENCES organisations(id),
    rail_id        TEXT NOT NULL,
    address        TEXT NOT NULL CHECK (address = lower(address)),
    next_nonce     BIGINT NOT NULL CHECK (next_nonce >= 0),
    refused_reason TEXT,
    reconciled_at  TIMESTAMPTZ,
    PRIMARY KEY (org_id, rail_id, address),
    FOREIGN KEY (org_id, rail_id) REFERENCES rails(org_id, id)
);
