"""Sanctions screening behind an interface (POL-03), so a real vendor can replace the mock later.

The mock reads ``fixtures/screening-list.yaml``. Matching is exact (G-07, D-23): addresses compare
case-insensitively; names compare case-folded with whitespace collapsed. No fuzzy matching.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import yaml

from detent.policy.facts import ScreeningResult
from detent.settings import REPO_ROOT

DEFAULT_LIST = REPO_ROOT / "fixtures" / "screening-list.yaml"


class Screening(Protocol):
    def check(self, *, address: str | None, name: str | None) -> ScreeningResult: ...


def _norm_name(name: str) -> str:
    return " ".join(name.casefold().split())


class MockScreening:
    def __init__(self, addresses: list[str], names: list[str]) -> None:
        self._addresses = {a.lower(): a for a in addresses}
        self._names = {_norm_name(n): n for n in names}

    @classmethod
    def from_fixture(cls, path: Path = DEFAULT_LIST) -> MockScreening:
        data = yaml.safe_load(path.read_text()) or {}
        return cls(list(data.get("addresses") or []), list(data.get("names") or []))

    def check(self, *, address: str | None, name: str | None) -> ScreeningResult:
        if address and address.lower() in self._addresses:
            return ScreeningResult(hit=True, matched=self._addresses[address.lower()], field="address")
        if name and _norm_name(name) in self._names:
            return ScreeningResult(hit=True, matched=self._names[_norm_name(name)], field="name")
        return ScreeningResult(hit=False)
