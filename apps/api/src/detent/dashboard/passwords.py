"""DSH-02: dashboard passwords are hashed with argon2id (spec/10); never logged or stored in plain text."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 256

_HASHER = PasswordHasher()  # argon2id with the library's current recommended parameters
# Verified when no account matches, so a wrong email takes as long as a wrong password.
_DUMMY_HASH = _HASHER.hash("not-a-real-password-for-timing-only")


class WeakPassword(ValueError):
    pass


def check_new_password(password: str, *, email: str) -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise WeakPassword(f"Use at most {MAX_LENGTH} characters.")
    p, e = password.strip().lower(), email.strip().lower()
    if e and (e in p or p in e):
        raise WeakPassword("The password can't contain your email address.")
    if len(set(password)) < 5:
        raise WeakPassword("Use a less repetitive password.")


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        return _HASHER.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
