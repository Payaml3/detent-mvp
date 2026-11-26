"""Settings, loaded once via pydantic-settings (FND-02).

This is the only module that reads the process environment. A test enforces that.

Invariant 14: test networks only. The app and the worker refuse to start when any configured
chain ID is outside the hard-coded test-network set. ``ALLOWED_CHAIN_IDS`` can narrow that set but
never widen it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Base Sepolia, Ethereum Sepolia, local anvil. Never edit this to add a mainnet.
TESTNET_CHAIN_IDS: frozenset[int] = frozenset({84532, 11155111, 31337})

REPO_ROOT = Path(__file__).resolve().parents[4]

AppEnv = Literal["dev", "test", "demo", "sandbox"]


class TestNetworkGuardError(RuntimeError):
    """Raised when configuration would point the prototype at a non-test network."""

    __test__ = False  # not a pytest test class


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = "dev"
    brand_name: str = "DekernAI"  # brand name (B-01); change in one place
    database_url: str = "postgresql+psycopg://detent:detent@localhost:5432/detent"

    demo_org_id: str = "org_demo"
    demo_password: SecretStr = SecretStr("change-me")
    session_secret: SecretStr = SecretStr("dev-only-session-secret-change-me")
    api_key_pepper: SecretStr | None = None
    credentials_encryption_key: SecretStr | None = None
    mandate_signing_key_demo: SecretStr | None = None
    webhook_secret_pepper: SecretStr | None = None

    anthropic_api_key: SecretStr | None = None
    model_agent: str = "claude-sonnet-5-5"
    model_light: str = "claude-haiku-5-5"
    model_eval_judge: str = "claude-opus-5-5"
    ai_daily_token_budget: int = 2_000_000
    # "auto" uses the Claude API when ANTHROPIC_API_KEY is set, otherwise the recorded stand-in responses
    # in fixtures/agent-recordings (offline demos and tests; the console says which one answered).
    agent_llm: Literal["auto", "anthropic", "recorded"] = "auto"
    agent_api_key: SecretStr | None = None  # the instruction agent's own sk_test_ key, bound to its mandate

    rails_config: Path = REPO_ROOT / "fixtures" / "rails.yaml"
    allowed_chain_ids: Annotated[frozenset[int], NoDecode] = TESTNET_CHAIN_IDS
    base_sepolia_rpc_url: str | None = None
    eth_sepolia_rpc_url: str | None = None
    local_evm_rpc_url: str | None = None
    test_wallet_private_key_base: SecretStr | None = None
    test_wallet_private_key_eth: SecretStr | None = None
    test_wallet_private_key_local: SecretStr | None = None  # local anvil only (S2)
    # S9 demo: the fictional payer wallets that send the batch's deposits (test networks only; DEM-03).
    demo_payer_private_key_base: SecretStr | None = None
    demo_payer_private_key_eth: SecretStr | None = None
    demo_payer_private_key_local: SecretStr | None = None
    usdc_address_base_sepolia: str = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    usdc_address_eth_sepolia: str = "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238"

    banksim_url: str = "http://localhost:8100"
    rail_timeout_seconds: float = 10.0  # how long an adapter waits for a rail's answer before UNKNOWN
    faultproxy_url: str = "http://localhost:8200"
    email_provider: str = (
        "outbox"  # the production provider is an open founder decision; only "outbox" exists
    )
    # P2: where invite links point (the dashboard's public address once deployed; spec/08 dashboard.<domain>).
    dashboard_url: str = "http://localhost:8000"
    invite_days: int = 7  # DSH-01, DSH-11: invites are single-use and expire after 7 days
    evaluation_days: int = 60  # DSH-03: the default expiry of an evaluation organisation
    login_attempts_per_minute: int = 10  # per email and (times 3) per client address
    sales_inbox: str | None = None

    # FND-07: where this instance and its database run, as stated in the console footer and /healthz.
    hosting_region: str = "local machine (not deployed)"
    database_region: str = "local machine (not deployed)"

    log_level: str = "INFO"
    log_json: bool = True

    worker_id: str | None = None
    worker_poll_seconds: float = 1.0
    worker_lease_seconds: int = 60
    # EXC-06: how often the worker checks for overdue cases (domain time still comes from the Clock).
    deadline_sweep_seconds: float = 30.0
    # LED-04: how often the worker runs the deposit watchers.
    deposit_watch_seconds: float = 10.0
    # LED-06: how often the worker runs reconciliation for every organisation with a ledger.
    reconciliation_seconds: float = 3600.0
    worker_max_attempts: int = 8
    # API-04: requests per key per minute (the per-address ceiling is 10 times this).
    api_rate_limit_per_minute: int = 120
    # WHK-03: webhook delivery. Plain http:// and private or loopback addresses are refused unless this is
    # set, which is allowed only in dev and test (a local receiver); the public sandbox never reaches inside.
    webhook_allow_private_urls: bool = False
    webhook_timeout_seconds: float = 10.0  # G-20
    # Extra handler modules, for tests only (rejected outside APP_ENV=test).
    worker_extra_handler_modules: Annotated[tuple[str, ...], NoDecode] = ()

    @field_validator("allowed_chain_ids", mode="before")
    @classmethod
    def _parse_chain_ids(cls, v: Any) -> Any:
        if isinstance(v, str):
            return frozenset(int(p) for p in v.replace(" ", "").split(",") if p)
        return v

    @field_validator("worker_extra_handler_modules", mode="before")
    @classmethod
    def _parse_modules(cls, v: Any) -> Any:
        if isinstance(v, str):
            return tuple(p for p in v.replace(" ", "").split(",") if p)
        return v

    @model_validator(mode="after")
    def _guard(self) -> Settings:
        outside = self.allowed_chain_ids - TESTNET_CHAIN_IDS
        if outside:
            raise TestNetworkGuardError(
                f"ALLOWED_CHAIN_IDS contains non-test-network chain IDs {sorted(outside)}. "
                f"Only {sorted(TESTNET_CHAIN_IDS)} are permitted (invariant 14)."
            )
        for rail_id, chain_id in self.configured_chain_ids().items():
            if chain_id not in self.allowed_chain_ids:
                raise TestNetworkGuardError(
                    f"Rail {rail_id!r} is configured with chain ID {chain_id}, which is not an allowed "
                    f"test network {sorted(self.allowed_chain_ids)}. Refusing to start (invariant 14)."
                )
        if self.worker_extra_handler_modules and self.app_env != "test":
            raise ValueError("WORKER_EXTRA_HANDLER_MODULES is only allowed with APP_ENV=test")
        if self.webhook_allow_private_urls and self.app_env not in ("dev", "test"):
            raise ValueError("WEBHOOK_ALLOW_PRIVATE_URLS is only allowed with APP_ENV=dev or test")
        if self.email_provider != "outbox":
            raise ValueError(
                "EMAIL_PROVIDER: only 'outbox' exists; the transactional email provider is an open "
                "founder decision"
            )
        if not 1 <= self.invite_days <= 30 or not 1 <= self.evaluation_days <= 365:
            raise ValueError("INVITE_DAYS must be 1 to 30 and EVALUATION_DAYS 1 to 365")
        if self.app_env in ("demo", "sandbox"):
            for name in ("demo_password", "session_secret"):
                val: SecretStr = getattr(self, name)
                if "change-me" in val.get_secret_value():
                    raise ValueError(f"{name.upper()} must be set to a real secret in {self.app_env}")
        return self

    def configured_chain_ids(self) -> dict[str, int]:
        """Chain IDs of every EVM rail in the rails config file."""
        path = self.rails_config
        if not path.is_absolute():
            path = REPO_ROOT / path
        data = yaml.safe_load(path.read_text())
        out: dict[str, int] = {}
        for rail in data.get("rails", []):
            if rail.get("kind") == "evm":
                if "chain_id" not in rail:
                    raise TestNetworkGuardError(f"EVM rail {rail.get('id')!r} has no chain_id")
                out[str(rail["id"])] = int(rail["chain_id"])
        return out

    @property
    def is_demo(self) -> bool:
        return self.app_env == "demo"

    def secret_values(self) -> list[str]:
        """Every configured secret value, for log redaction."""
        out: list[str] = []
        for name in type(self).model_fields:
            v = getattr(self, name)
            if isinstance(v, SecretStr):
                s = v.get_secret_value()
                if len(s) >= 6:
                    out.append(s)
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


def environ_snapshot() -> dict[str, str]:
    """Process environment, for passing to child processes (tests, dev runner).

    Kept here so that no module outside settings.py touches os.environ.
    """
    import os

    return dict(os.environ)


__all__ = [
    "TESTNET_CHAIN_IDS",
    "Settings",
    "TestNetworkGuardError",
    "environ_snapshot",
    "get_settings",
    "reset_settings_cache",
]
