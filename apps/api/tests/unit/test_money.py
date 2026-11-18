"""Invariant 15: integer minor units plus a currency; no floats."""

import pytest
from detent.domain.money import Currency, CurrencyMismatch, Money, MoneyError


def test_parse_usdc_exactly() -> None:
    m = Money.parse("18500.00", "USDC")
    assert m == Money(18_500_000_000, Currency.USDC)
    assert m.to_decimal_str() == "18500.00"
    assert m.to_api() == {"amount": "18500.00", "currency": "USDC"}


@pytest.mark.parametrize(
    ("amount", "cur", "minor"),
    [("0.01", "GBP", 1), ("75.42", "USDC", 75_420_000), ("0.000001", "USDC", 1), ("5", "EUR", 500)],
)
def test_parse_values(amount: str, cur: str, minor: int) -> None:
    assert Money.parse(amount, cur).amount_minor == minor


@pytest.mark.parametrize("bad", ["1.001", "abc", "1e3", "01.00", " ", "1.", ".5", "1,000.00"])
def test_parse_rejects_bad_strings(bad: str) -> None:
    with pytest.raises(MoneyError):
        Money.parse(bad, "GBP")


def test_floats_rejected_everywhere() -> None:
    with pytest.raises(TypeError):
        Money(1.5, Currency.GBP)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money.parse(18500.0, "USDC")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money(True, Currency.GBP)


def test_cross_currency_arithmetic_is_an_error() -> None:
    with pytest.raises(CurrencyMismatch):
        _ = Money(1, Currency.GBP) + Money(1, Currency.EUR)
    with pytest.raises(CurrencyMismatch):
        _ = Money(1, Currency.GBP) < Money(1, Currency.USDC)


def test_arithmetic_and_formatting() -> None:
    a, b = Money.parse("10.50", "GBP"), Money.parse("0.75", "GBP")
    assert (a + b).to_decimal_str() == "11.25"
    assert (b - a).to_decimal_str() == "-9.75"
    assert Money.parse("1.234567", "USDC").to_decimal_str() == "1.234567"
    assert Money.parse("1.2", "USDC").to_decimal_str() == "1.20"


def test_unknown_currency() -> None:
    with pytest.raises(ValueError, match="BTC"):
        Money.parse("1.00", "BTC")
