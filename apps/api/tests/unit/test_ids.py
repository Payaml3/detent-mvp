from datetime import UTC, datetime, timedelta

import pytest
from detent.domain.ids import Prefix, is_valid, new_id, prefix_of, to_uuid


def test_new_id_is_prefixed_uuid7() -> None:
    at = datetime(2026, 12, 3, 10, 0, tzinfo=UTC)
    pid = new_id(Prefix.PAY, at)
    assert pid.startswith("pay_") and len(pid) == 4 + 26
    u = to_uuid(pid)
    assert u.version == 7
    assert int.from_bytes(u.bytes[:6], "big") == int(at.timestamp() * 1000)


@pytest.mark.parametrize("p", list(Prefix))
def test_every_prefix(p: Prefix) -> None:
    v = new_id(p, datetime(2026, 1, 1, tzinfo=UTC))
    assert is_valid(v, p) and prefix_of(v) == p.value


def test_ids_sort_by_time() -> None:
    t = datetime(2026, 12, 3, tzinfo=UTC)
    ids = [new_id(Prefix.ATT, t + timedelta(milliseconds=i)) for i in range(50)]
    assert ids == sorted(ids)


def test_seeded_readable_ids_are_valid_but_not_uuids() -> None:
    assert is_valid("cpt_bluefin", Prefix.CPT)
    assert is_valid("org_demo", Prefix.ORG)
    assert not is_valid("org_demo", Prefix.PAY)
    with pytest.raises(ValueError, match="UUIDv7"):
        to_uuid("cpt_bluefin")


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        new_id(Prefix.PAY, datetime(2026, 1, 1))


def test_ids_made_in_the_same_millisecond_sort_in_the_order_they_were_made() -> None:
    at = datetime(2026, 12, 3, 10, 0, tzinfo=UTC)
    ids = [new_id(Prefix.DEC, at) for _ in range(200)]
    assert ids == sorted(ids) and len(set(ids)) == 200
