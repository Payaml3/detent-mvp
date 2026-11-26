"""Prefixed UUIDv7 identifiers (spec/02, FND-03).

Format: ``<prefix>_<26 Crockford base32 chars>``, the 128-bit UUIDv7 encoded so that IDs sort by
creation time, for example ``pay_01JDQ3...``.

Seeded fixture rows use readable IDs with the same prefix (``cpt_bluefin``, ``org_demo``).
``is_valid`` accepts both; ``new_id`` always generates UUIDv7.
"""

from __future__ import annotations

import re
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum


class Prefix(StrEnum):
    ORG = "org"
    USR = "usr"
    KEY = "key"
    CPT = "cpt"  # counterparty
    DST = "dst"  # destination
    MND = "mnd"
    POL = "pol"
    PAY = "pay"
    DEC = "dec"
    ATT = "att"
    EXC = "exc"
    DEP = "dep"
    INB = "inb"  # inbound transfer
    CRD = "crd"  # credit
    ACC = "acc"  # ledger account
    JRN = "jrn"
    PST = "pst"  # posting
    REC = "rec"
    BRK = "brk"
    AGC = "agc"  # agent call
    EVT = "evt"
    INC = "inc"
    JOB = "job"
    CEV = "cev"  # case event
    OBX = "obx"  # outbox message
    WHE = "whe"  # webhook endpoint
    WHD = "whd"  # webhook delivery
    REQ = "req"  # request log / request ID
    INV = "inv"  # invite
    LED = "lead"  # website access request
    MCH = "mch"  # mode change
    VER = "ver"  # integration verification request


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_VALID = re.compile(r"^(?P<prefix>[a-z]{3,4})_(?P<body>[A-Za-z0-9_]{1,64})$")
_UUID_BODY = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def _encode(n: int) -> str:
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[n & 31])
        n >>= 5
    return "".join(reversed(chars))


def _decode(s: str) -> int:
    n = 0
    for ch in s:
        n = (n << 5) | _CROCKFORD.index(ch)
    return n


def uuid7(at: datetime, rand: Callable[[int], bytes] = secrets.token_bytes) -> uuid.UUID:
    """RFC 9562 UUIDv7 from a timezone-aware datetime (from the Clock)."""
    if at.tzinfo is None:
        raise ValueError("uuid7 needs a timezone-aware datetime")
    ms = int(at.timestamp() * 1000)
    if ms < 0 or ms >= 1 << 48:
        raise ValueError("timestamp out of range for UUIDv7")
    rnd = int.from_bytes(rand(10), "big")  # 80 random bits; 74 are used
    rand_a = (rnd >> 62) & 0xFFF
    rand_b = rnd & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def new_id(prefix: Prefix, at: datetime, rand: Callable[[int], bytes] = secrets.token_bytes) -> str:
    return f"{prefix.value}_{_encode(uuid7(at, rand).int)}"


def is_valid(value: str, prefix: Prefix | None = None) -> bool:
    m = _VALID.match(value)
    if not m:
        return False
    return prefix is None or m.group("prefix") == prefix.value


def to_uuid(value: str) -> uuid.UUID:
    """Decode a generated ID back to its UUIDv7. Raises ValueError for seeded readable IDs."""
    m = _VALID.match(value)
    if not m or not _UUID_BODY.match(m.group("body")):
        raise ValueError(f"not a generated UUIDv7 ID: {value!r}")
    u = uuid.UUID(int=_decode(m.group("body")))
    if u.version != 7:
        raise ValueError(f"not a UUIDv7: {value!r}")
    return u


def prefix_of(value: str) -> str:
    m = _VALID.match(value)
    if not m:
        raise ValueError(f"not a DekernAI ID: {value!r}")
    return m.group("prefix")
