-- 0008 (slice S8): found by the attack suite (atk-bb-03). A payment the rules did not authorise to send
-- (BLOCKED or REJECTED, which are terminal under invariant 4, or ESCALATED or HELD, which wait for a
-- person) can never get an attempt, whatever code or person inserts the row. The application path is
-- stricter still: create_attempt requires READY under the payment's row lock. A missing payment is left
-- to the foreign key.
CREATE FUNCTION attempt_needs_ready_payment() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE st TEXT;
BEGIN
    SELECT status INTO st FROM payment_intents WHERE org_id = NEW.org_id AND id = NEW.payment_id;
    IF st IN ('BLOCKED', 'REJECTED', 'ESCALATED', 'HELD') THEN
        RAISE EXCEPTION 'payment % is %; an attempt needs a payment authorised to send', NEW.payment_id, st
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER attempt_ready_guard BEFORE INSERT ON attempts
    FOR EACH ROW EXECUTE FUNCTION attempt_needs_ready_payment();
