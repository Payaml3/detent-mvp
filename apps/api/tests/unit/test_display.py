"""Display filters: amounts get thousands separators from their text, never through a float."""

from detent.views.display import group_amount


def test_group_amount_keeps_every_digit() -> None:
    assert group_amount("9000.00") == "9,000.00"
    assert group_amount("18500.00 USDC") == "18,500.00 USDC"
    assert group_amount(1850000) == "1,850,000"
    assert group_amount("-1234567.891") == "-1,234,567.891"
    assert group_amount("999.99") == "999.99"
    assert group_amount("12345678901234567890.01") == "12,345,678,901,234,567,890.01"


def test_group_amount_leaves_other_text_alone() -> None:
    assert group_amount(None) == ""
    assert group_amount("") == ""
    assert group_amount("n/a") == "n/a"
    assert group_amount("pay_01ABC") == "pay_01ABC"
