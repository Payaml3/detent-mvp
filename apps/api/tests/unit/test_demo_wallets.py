"""DEM-04: ``detent demo check`` reports each demo wallet per chain and says what to top up."""

from __future__ import annotations

from detent.demo.wallets import check_wallets, needed_usdc, render
from detent.settings import Settings
from pydantic import SecretStr

KEY_A = SecretStr("0x" + "11" * 32)
KEY_B = SecretStr("0x" + "22" * 32)


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, app_env="test", **kw)  # type: ignore[call-arg, arg-type]


def test_needs_come_from_the_demo_fixtures() -> None:
    base, eth = needed_usdc("base-sepolia"), needed_usdc("eth-sepolia")
    assert base["sender"] == 1_850_000 + 12000 + 7542 + 4000 + 9500 + 3300 + 1800  # $18,500 + Base payouts
    assert eth["sender"] == 7542 + 21000 + 5200  # p08 after its failover, p15, p20
    assert base["payer"] == 50000 + 12000 + 8000 + 6000 + 20000  # dep-07 lands on Base Sepolia
    assert eth["payer"] == 25000


def test_unconfigured_wallets_say_what_to_set() -> None:
    lines = check_wallets(_settings())
    assert {(w.role, w.network, w.status) for w in lines} == {
        (r, n, "not_configured") for r in ("sender", "payer") for n in ("base-sepolia", "eth-sepolia")
    }
    out = render(lines)
    assert "TEST_WALLET_PRIVATE_KEY_BASE" in out and "DEMO_PAYER_PRIVATE_KEY_ETH" in out


def test_low_balances_ask_for_a_top_up_with_faucets() -> None:
    s = _settings(
        base_sepolia_rpc_url="http://base.invalid",
        eth_sepolia_rpc_url="http://eth.invalid",
        test_wallet_private_key_base=KEY_A,
        test_wallet_private_key_eth=KEY_A,
        demo_payer_private_key_base=KEY_B,
        demo_payer_private_key_eth=KEY_B,
    )
    chain_ids = {"http://base.invalid": 84532, "http://eth.invalid": 11155111}

    def fake(url: str, token: str, address: str) -> tuple[int, int, int]:
        return chain_ids[url], 100_00, 10**18  # $100 and 1 test ETH everywhere

    lines = check_wallets(s, balances=fake)
    status = {(w.role, w.network): w.status for w in lines}
    assert status == {
        ("sender", "base-sepolia"): "top_up",
        ("payer", "base-sepolia"): "top_up",
        ("sender", "eth-sepolia"): "top_up",
        ("payer", "eth-sepolia"): "top_up",
    }
    out = render(lines)
    assert "detent demo token fund --network base-sepolia" in out and "top up 18,781.42 test USDC" in out


def test_a_wrong_chain_is_reported_not_trusted() -> None:
    s = _settings(base_sepolia_rpc_url="http://x.invalid", test_wallet_private_key_base=KEY_A)
    lines = check_wallets(s, balances=lambda url, token, addr: (1, 10**12, 10**20))  # chain 1: a mainnet
    assert (
        next(w for w in lines if w.role == "sender" and w.network == "base-sepolia").status == "wrong_chain"
    )


def test_enough_everywhere_is_ok() -> None:
    s = _settings(
        base_sepolia_rpc_url="http://b.invalid",
        eth_sepolia_rpc_url="http://e.invalid",
        test_wallet_private_key_base=KEY_A,
        test_wallet_private_key_eth=KEY_A,
        demo_payer_private_key_base=KEY_B,
        demo_payer_private_key_eth=KEY_B,
    )
    ids = {"http://b.invalid": 84532, "http://e.invalid": 11155111}
    lines = check_wallets(s, balances=lambda url, token, addr: (ids[url], 10**9, 10**18))
    assert all(w.ok for w in lines)
    assert "All demo wallets hold enough" in render(lines)


def test_demo_script_matches_the_runner_and_ends_with_the_ask() -> None:
    """DEM-05: spec/11 names the runner's scenarios by their button titles and ends with the onboarding ask (B-04)."""
    from detent.demo.scenarios import SCENARIOS
    from detent.settings import REPO_ROOT

    script = (REPO_ROOT / "spec" / "11-demo-script.md").read_text()
    for sc in SCENARIOS.values():
        assert f"**{sc.title}**" in script, sc.title
    rows = [line for line in script.splitlines() if line.startswith("| 9 to 10")]
    assert rows and "start onboarding?" in rows[0]
    assert "shadow report" not in script.lower(), "no free shadow report (B-04)"
