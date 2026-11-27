"""Verify a DekernAI webhook delivery. Run: python verify_webhook.py ../webhook-vectors.txt"""

# docs:start
import hashlib
import hmac
import time


def verify_webhook(
    secret: str, header: str, body: bytes, now: int | None = None, tolerance: int = 300
) -> bool:
    """True if the DekernAI-Signature header matches the raw body and is within the time window."""
    timestamp, signatures = None, []
    for part in header.split(","):
        key, sep, value = part.strip().partition("=")
        if not sep:
            return False
        if key == "t":
            if timestamp is not None or not value.isdigit():
                return False
            timestamp = int(value)
        elif key == "v1":
            signatures.append(value)
    if timestamp is None or not signatures:
        return False
    if abs((int(time.time()) if now is None else now) - timestamp) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in signatures)


# docs:end


if __name__ == "__main__":
    import sys

    failures = 0
    with open(sys.argv[1], encoding="utf-8") as f:
        lines = f.read().splitlines()
    for line in lines:
        if not line or line.startswith("#"):
            continue
        name, expect, secret, now, header, body = line.split("|", 5)
        got = verify_webhook(secret, header, body.encode(), int(now))
        if got != (expect == "ok"):
            print(f"FAIL {name}: expected {expect}")
            failures += 1
    print("python: all vectors pass" if not failures else f"python: {failures} vector(s) failed")
    sys.exit(1 if failures else 0)
