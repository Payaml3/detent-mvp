-- 0004 never paid twice (slice S4). Forward-only.
SET search_path TO detent;

-- EXE-06: when an attempt became UNKNOWN, so time-to-resolve can be reported (median and p95).
ALTER TABLE attempts ADD COLUMN unknown_at TIMESTAMPTZ;
-- A replacement transaction signed for the same nonce (cancel-by-replacement, EXE-06).
ALTER TABLE attempts ADD COLUMN replacement_tx_hash TEXT;

-- EXE-07: a transaction that failed TECHNICAL_RETRYABLE never reached the chain, so its nonce is free
-- again; the retry signs a new transaction with that same nonce. Every other nonce stays unique.
DROP INDEX one_tx_per_nonce;
CREATE UNIQUE INDEX one_tx_per_nonce ON attempts (rail_id, from_address, nonce)
    WHERE nonce IS NOT NULL AND NOT (status = 'FAILED' AND failure_class = 'TECHNICAL_RETRYABLE');

-- Bank rails (RAL-04) and routing (RAL-06): per-payment limits and the failure history used for scores.
ALTER TABLE rails ADD COLUMN per_payment_limit_minor BIGINT;
ALTER TABLE rails ADD COLUMN daily_limit_minor BIGINT;
ALTER TABLE rails ADD COLUMN base_url TEXT;
ALTER TABLE rails ADD COLUMN fee_flat_minor BIGINT NOT NULL DEFAULT 0;
ALTER TABLE rails ADD COLUMN fee_bps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE rails ADD COLUMN est_fee_minor BIGINT NOT NULL DEFAULT 0;
ALTER TABLE rails ADD COLUMN est_seconds INTEGER NOT NULL DEFAULT 1;

-- Invariant 3, tightened: UNKNOWN -> FAILED needs *new* evidence from the rail. The evidence recorded
-- when the attempt timed out (the timeout itself) is not evidence that it failed.
CREATE OR REPLACE FUNCTION forbid_terminal_attempt_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('CONFIRMED','FAILED') AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'attempt % is final (%)', OLD.id, OLD.status USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'UNKNOWN' AND NEW.status = 'FAILED'
       AND (NEW.evidence IS NULL OR NEW.evidence IS NOT DISTINCT FROM OLD.evidence) THEN
        RAISE EXCEPTION 'attempt % cannot go UNKNOWN -> FAILED without evidence', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

-- Counters (spec/04): the UTC day a payment's amount was counted against the caps, while it counts.
-- Set when the payment becomes in flight, cleared when it is released (BLOCKED, REJECTED, CANCELLED,
-- FAILED_FINAL). Counting and release therefore always pair up, whatever path the payment took.
ALTER TABLE payment_intents ADD COLUMN counted_on TEXT;
-- Why a payment is HELD (KILL_SWITCH_ENGAGED, INSUFFICIENT_BALANCE, ...), so release can find its own.
ALTER TABLE payment_intents ADD COLUMN held_reason TEXT;
