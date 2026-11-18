"""Money as integer minor units plus a currency (invariant 15).

There are no floats anywhere in money paths: constructors reject them, and decimal strings are
parsed exactly. Arithmetic across currencies raises ``CurrencyMismatch``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Self


class Currency(StrEnum):
    USDC = "USDC"
    GBP = "GBP"
    EUR = "EUR"

    @property
    def decimals(self) -> int:
        return _DECIMALS[self]


_DECIMALS: dict[Currency, int] = {Currency.USDC: 6, Currency.GBP: 2, Currency.EUR: 2}
_DECIMAL_RE = re.compile(r"^(?P<sign>-)?(?P<int>0|[1-9][0-9]*)(?:\.(?P<frac>[0-9]+))?$")


class MoneyError(ValueError):
    pass


class CurrencyMismatch(MoneyError):
    pass


@dataclass(frozen=True, slots=True, order=False)
class Money:
    amount_minor: int
    currency: Currency

    def __post_init__(self) -> None:
        # bool is an int subclass; reject it along with floats and Decimals.
        if type(self.amount_minor) is not int:
            raise TypeError(f"amount_minor must be int, got {type(self.amount_minor).__name__}")
        if not isinstance(self.currency, Currency):
            raise TypeError("currency must be a Currency")

    # ------------------------------------------------------------------ parsing and formatting
    @classmethod
    def parse(cls, amount: str, currency: Currency | str) -> Self:
        """Parse an API decimal string such as ``"18500.00"`` exactly."""
        if not isinstance(amount, str):
            raise TypeError("amount must be a decimal string, never a float")
        cur = Currency(currency)
        m = _DECIMAL_RE.match(amount.strip())
        if not m:
            raise MoneyError(f"invalid amount {amount!r}")
        frac = m.group("frac") or ""
        if len(frac) > cur.decimals:
            raise MoneyError(f"{cur.value} allows at most {cur.decimals} decimal places, got {amount!r}")
        minor = int(m.group("int")) * 10**cur.decimals + int(frac.ljust(cur.decimals, "0") or "0")
        return cls(-minor if m.group("sign") else minor, cur)

    def to_decimal_str(self) -> str:
        d = self.currency.decimals
        sign = "-" if self.amount_minor < 0 else ""
        whole, frac = divmod(abs(self.amount_minor), 10**d)
        # Display at least 2 decimals, and all significant ones (USDC can have 6).
        frac_s = str(frac).rjust(d, "0").rstrip("0").ljust(min(2, d), "0")
        return f"{sign}{whole}.{frac_s}" if frac_s else f"{sign}{whole}"

    def to_api(self) -> dict[str, str]:
        return {"amount": self.to_decimal_str(), "currency": self.currency.value}

    @classmethod
    def zero(cls, currency: Currency | str) -> Self:
        return cls(0, Currency(currency))

    # ------------------------------------------------------------------ arithmetic
    def _same(self, other: object) -> Money:
        if not isinstance(other, Money):
            raise TypeError("can only combine Money with Money")
        if other.currency != self.currency:
            raise CurrencyMismatch(f"{self.currency.value} vs {other.currency.value}")
        return other

    def __add__(self, other: object) -> Money:
        o = self._same(other)
        return Money(self.amount_minor + o.amount_minor, self.currency)

    def __sub__(self, other: object) -> Money:
        o = self._same(other)
        return Money(self.amount_minor - o.amount_minor, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount_minor, self.currency)

    def __lt__(self, other: object) -> bool:
        return self.amount_minor < self._same(other).amount_minor

    def __le__(self, other: object) -> bool:
        return self.amount_minor <= self._same(other).amount_minor

    def __gt__(self, other: object) -> bool:
        return self.amount_minor > self._same(other).amount_minor

    def __ge__(self, other: object) -> bool:
        return self.amount_minor >= self._same(other).amount_minor

    def is_negative(self) -> bool:
        return self.amount_minor < 0

    def __str__(self) -> str:
        return f"{self.to_decimal_str()} {self.currency.value}"
