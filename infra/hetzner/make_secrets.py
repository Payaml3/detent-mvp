"""Print fresh production secrets for the Hetzner demo, ready to paste into Coolify's environment variables.

  python3 infra/hetzner/make_secrets.py            # app secrets (standard library only: run it on the server)
  python3 infra/hetzner/make_secrets.py --wallets  # four new TEST-NETWORK wallets (in the app container)

The output is shown once, on your screen only. Paste it straight into Coolify and never into a chat, a ticket
or the repository. Wallets are for Base Sepolia and Ethereum Sepolia test networks only (invariant 14).
"""

from __future__ import annotations

import base64
import secrets
import sys


def app_secrets() -> list[str]:
    return [
        f"DEMO_PASSWORD={secrets.token_urlsafe(18)}",
        f"SESSION_SECRET={secrets.token_hex(32)}",
        f"API_KEY_PEPPER={secrets.token_hex(32)}",
        # A Fernet key is 32 random bytes, URL-safe base64 encoded.
        f"CREDENTIALS_ENCRYPTION_KEY={base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}",
        f"MANDATE_SIGNING_KEY_DEMO={secrets.token_hex(32)}",
        f"WEBHOOK_SECRET_PEPPER={secrets.token_hex(32)}",
    ]


def wallets() -> list[str]:
    from eth_account import Account  # in the app image; not on the bare server

    lines = ["# TEST NETWORKS ONLY. Fund the addresses from faucets; never send real funds to them."]
    for name in (
        "TEST_WALLET_PRIVATE_KEY_BASE",
        "TEST_WALLET_PRIVATE_KEY_ETH",
        "DEMO_PAYER_PRIVATE_KEY_BASE",
        "DEMO_PAYER_PRIVATE_KEY_ETH",
    ):
        acct = Account.create()
        lines.append(f"# {name} address (safe to share): {acct.address}")
        lines.append(f"{name}=0x{acct.key.hex().removeprefix('0x')}")
    return lines


if __name__ == "__main__":
    print("\n".join(wallets() if "--wallets" in sys.argv[1:] else app_secrets()))
