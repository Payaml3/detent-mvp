"""Display helpers shared by the console and the dashboard templates. Presentation only: no money maths.

``group_amount`` adds thousands separators to an amount as it is already written (a decimal string such as
"9000.00", or integer minor units). It works on the text, never through a float, so the digits shown are
exactly the digits stored (invariant 15).
"""

from __future__ import annotations

import re
from typing import Any

_NUMBER = re.compile(r"^(-?)(\d+)((?:\.\d+)?)(.*)$", re.S)


def group_amount(value: Any) -> str:
    """'9000.00' -> '9,000.00'; 18500 -> '18,500'; '1234.5 USDC' -> '1,234.5 USDC'; other text unchanged."""
    if value is None:
        return ""
    text = str(value)
    m = _NUMBER.match(text.strip())
    if not m:
        return text
    sign, whole, frac, rest = m.groups()
    grouped = re.sub(r"(?<=\d)(?=(\d{3})+$)", ",", whole)
    return f"{sign}{grouped}{frac}{rest}"


def install(env: Any) -> None:
    """Register the filters on a Jinja environment."""
    env.filters["amount"] = group_amount
