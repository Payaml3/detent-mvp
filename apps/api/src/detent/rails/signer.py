"""Signing behind an interface (spec/01 "Production custody boundary").

The prototype signs with test keys from settings. A custody-provider signer can replace
``LocalKeySigner`` without touching the execution layer. Keys never leave this object and never
appear in logs (the logging redactor also knows them).
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import SecretStr


class Signer(Protocol):
    @property
    def address(self) -> str: ...
    def sign(self, tx: dict[str, Any]) -> tuple[str, str]:
        """Returns (raw transaction hex, transaction hash hex)."""
        ...


class LocalKeySigner:
    def __init__(self, key: SecretStr) -> None:
        from eth_account import Account

        self._account = Account.from_key(key.get_secret_value())

    @property
    def address(self) -> str:
        return str(self._account.address)

    def sign(self, tx: dict[str, Any]) -> tuple[str, str]:
        signed = self._account.sign_transaction(tx)
        return "0x" + signed.raw_transaction.hex().removeprefix("0x"), "0x" + signed.hash.hex().removeprefix(
            "0x"
        )

    def __repr__(self) -> str:
        return f"LocalKeySigner({self.address})"
