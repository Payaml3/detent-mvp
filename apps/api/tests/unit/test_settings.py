"""FND-02 / invariant 14: settings refuse anything but test networks."""

from pathlib import Path

import pytest
from detent.settings import TESTNET_CHAIN_IDS, Settings, TestNetworkGuardError
from pydantic import SecretStr, ValidationError


def _rails(tmp_path: Path, chain_id: int) -> Path:
    p = tmp_path / "rails.yaml"
    p.write_text(f"rails:\n  - {{id: some-chain, kind: evm, chain_id: {chain_id}, currency: USDC}}\n")
    return p


def make(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg, arg-type]


def test_default_config_is_test_networks_only() -> None:
    s = make()
    assert set(s.configured_chain_ids().values()) <= TESTNET_CHAIN_IDS
    assert s.allowed_chain_ids == TESTNET_CHAIN_IDS


@pytest.mark.parametrize("chain_id", [1, 8453, 10, 137, 42161, 56])
def test_mainnet_chain_in_rails_config_refuses(tmp_path: Path, chain_id: int) -> None:
    with pytest.raises((TestNetworkGuardError, ValidationError), match="Refusing to start"):
        make(rails_config=_rails(tmp_path, chain_id))


def test_allowed_chain_ids_cannot_be_widened() -> None:
    with pytest.raises((TestNetworkGuardError, ValidationError), match="non-test-network"):
        make(allowed_chain_ids="84532,1")


def test_allowed_chain_ids_can_be_narrowed(tmp_path: Path) -> None:
    with pytest.raises((TestNetworkGuardError, ValidationError)):
        make(allowed_chain_ids="31337", rails_config=_rails(tmp_path, 84532))
    s = make(allowed_chain_ids="31337,84532,11155111")
    assert s.allowed_chain_ids == TESTNET_CHAIN_IDS


def test_evm_rail_without_chain_id_refuses(tmp_path: Path) -> None:
    p = tmp_path / "rails.yaml"
    p.write_text("rails:\n  - {id: x, kind: evm, currency: USDC}\n")
    with pytest.raises((TestNetworkGuardError, ValidationError), match="no chain_id"):
        make(rails_config=p)


def test_extra_worker_handlers_only_in_test_env() -> None:
    with pytest.raises(ValidationError, match="only allowed"):
        make(app_env="dev", worker_extra_handler_modules="support.handlers")
    assert make(app_env="test", worker_extra_handler_modules="a,b").worker_extra_handler_modules == ("a", "b")


def test_demo_needs_real_secrets() -> None:
    with pytest.raises(ValidationError, match="DEMO_PASSWORD"):
        make(app_env="demo")
    s = make(app_env="demo", demo_password=SecretStr("a-real-one-123"), session_secret=SecretStr("x" * 32))
    assert s.is_demo


def test_secret_values_listed_for_redaction() -> None:
    s = make(api_key_pepper=SecretStr("pepper-123456"))
    assert "pepper-123456" in s.secret_values()


def test_empty_environment_variables_count_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """FND-07: the Hetzner deploy passes optional secrets as empty strings until the founder sets them."""
    monkeypatch.setenv("TEST_WALLET_PRIVATE_KEY_BASE", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    s = make()
    assert s.test_wallet_private_key_base is None
    assert s.anthropic_api_key is None
