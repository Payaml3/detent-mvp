"""The evaluation world and one scenario's environment (EVL-01).

``World`` is shared by a run: a freshly migrated evaluation database, one local anvil chain with MockUSDC,
the bank simulator, and a fault-injection proxy in front of each rail. Nothing touches a public network.

``Env`` is one scenario: its own organisation (every query is scoped by org_id, so scenarios can't see
each other), the fixture rule set and counterparties, generated test wallets, API keys per role, a frozen
clock and a worker that only runs this organisation's jobs.

The USDC rails are named as in the fixtures (base-sepolia, eth-sepolia, local-evm) but all three run on
the local anvil chain (chain ID 31337), with a separate sending wallet each, as the S5 end-to-end test
does. Keys are generated at runtime and never written down.
"""

from __future__ import annotations

import contextlib
import json
import os
import random
import secrets
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx
from detent.clock import FrozenClock
from detent.settings import REPO_ROOT, Settings
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text

DEFAULT_DB = os.environ.get(
    "EVAL_DATABASE_URL", "postgresql+psycopg://detent:detent@localhost:5432/detent_eval"
)
PEPPER = "eval-pepper-0123456789abcdef"
MANDATE_KEY = SecretStr("eval-mandate-key-0123456789abcdef")
POLICY_TEXT = (REPO_ROOT / "fixtures" / "policy" / "default-policy.yaml").read_text()
START = datetime.fromisoformat("2026-12-03T10:00:00+00:00")
USDC_RAILS = ("local-evm", "base-sepolia", "eth-sepolia")
ALL_SCOPES = ["read", "intents:create", "exceptions:approve", "admin"]
ROLES = ("payments_lead", "compliance_lead", "reviewer", "backup_owner", "oncall", "admin")


# ------------------------------------------------------------------------------------------ servers
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextlib.contextmanager
def serve(app: Any) -> Iterator[str]:
    import uvicorn

    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level=os.environ.get("EVAL_SERVER_LOG", "critical"),
            lifespan="off",
        )
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            httpx.get(f"{url}/healthz", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    try:
        yield url
    finally:
        server.should_exit = True
        t.join(timeout=5)


def fresh_database(url: str) -> Engine:
    """Create the evaluation database if needed, drop its schemas and migrate from scratch."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    u = make_url(url)
    admin = create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        exists = c.execute(text("SELECT 1 FROM pg_database WHERE datname=:d"), {"d": u.database}).scalar()
        if not exists:
            c.execute(text(f'CREATE DATABASE "{u.database}"'))
    admin.dispose()
    raw = create_engine(url)
    with raw.begin() as conn:
        for schema in ("detent", "testsupport", "banksim"):
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
    raw.dispose()
    cfg = Config(str(REPO_ROOT / "apps" / "api" / "alembic.ini"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")
    from detent.db.engine import make_engine

    return make_engine(url, pool_size=20)


@dataclass
class Chain:
    rpc_url: str  # anvil itself (the evaluator reads the chain here, never through the proxy)
    proxy_url: str  # what DekernAI's adapters use
    usdc: str
    funder: str

    def w3(self) -> Any:
        from web3 import Web3

        return Web3(Web3.HTTPProvider(self.rpc_url))

    def token(self) -> Any:
        from detent import devchain

        return self.w3().eth.contract(address=self.usdc, abi=devchain.abi())

    def new_wallet(self, *, usdc_minor: int = 0, eth_wei: int = 10**18) -> tuple[str, SecretStr]:
        from eth_account import Account

        acct = Account.create()
        w3 = self.w3()
        if eth_wei:
            w3.provider.make_request("anvil_setBalance", [acct.address, hex(eth_wei)])
        if usdc_minor:
            h = self.token().functions.mint(acct.address, usdc_minor).transact({"from": self.funder})
            w3.eth.wait_for_transaction_receipt(h)
        return str(acct.address), SecretStr(acct.key.hex())

    def balance(self, address: str) -> int:
        return int(self.token().functions.balanceOf(address).call())

    def transfers_from(self, sender: str) -> list[dict[str, Any]]:
        """Every MockUSDC transfer the wallet made, read from the chain's own logs."""
        evs = self.token().events.Transfer().get_logs(from_block=0, argument_filters={"from": sender})
        return [
            {
                "tx_hash": e["transactionHash"].hex(),
                "to": str(e["args"]["to"]),
                "value": int(e["args"]["value"]),
            }
            for e in evs
        ]


class World:
    """Shared services for one run. Chain and bank start only when a suite needs them."""

    def __init__(self, database_url: str = DEFAULT_DB) -> None:
        self.database_url = database_url
        self.engine = fresh_database(database_url)
        self._stack = contextlib.ExitStack()
        self.chain: Chain | None = None
        self.bank_url: str | None = None  # banksim itself
        self.bank_proxy: str | None = None

    def start_chain(self) -> Chain:
        if self.chain is not None:
            return self.chain
        from detent import devchain
        from faultproxy.app import create_app as proxy_app

        port = free_port()
        proc = devchain.start_anvil(port)
        self._stack.callback(proc.terminate)
        lc = devchain.deploy(f"http://127.0.0.1:{port}")
        proxy = self._stack.enter_context(serve(proxy_app(lc.rpc_url, hold_seconds=2.0)))
        self.chain = Chain(lc.rpc_url, proxy, lc.usdc_address, lc.accounts[0])
        return self.chain

    def start_bank(self) -> str:
        if self.bank_proxy is not None:
            return self.bank_proxy
        from banksim.app import Config, SchemeConfig
        from banksim.app import create_app as bank_app
        from faultproxy.app import create_app as proxy_app

        s = SchemeConfig(
            per_payment_limit_minor=25_000_00, daily_limit_minor=10_000_000_00, fee_flat_minor=20
        )
        cfg = Config(schemes={"fps": s, "sepa_inst": s}, hold_seconds=2.0)
        self.bank_url = self._stack.enter_context(serve(bank_app(self.database_url, cfg)))
        self.bank_proxy = self._stack.enter_context(serve(proxy_app(self.bank_url, hold_seconds=2.0)))
        return self.bank_proxy

    def close(self) -> None:
        self._stack.close()
        self.engine.dispose()


# ------------------------------------------------------------------------------------------ one scenario
@dataclass
class Env:
    world: World
    org_id: str
    clock: FrozenClock
    rng: random.Random
    users: dict[str, str]
    keys: dict[str, str]
    settings: Settings
    senders: dict[str, str] = field(default_factory=dict)  # rail -> sending wallet
    payees: dict[str, str] = field(default_factory=dict)  # destination alias -> wallet
    saved: dict[str, Any] = field(default_factory=dict)  # names a scenario gives to IDs and answers
    other: Env | None = None  # a second organisation, for cross-organisation attacks
    client: Any = None
    log: list[dict[str, Any]] = field(default_factory=list)  # what each step did, for the results file

    @property
    def engine(self) -> Engine:
        return self.world.engine


def _insert_org(engine: Engine, clock: FrozenClock, org_id: str, mode: str, fail_safe: str) -> dict[str, str]:
    users: dict[str, str] = {}
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organisations (id, name, mode, fail_safe, kind, registered_name, "
                "registered_account, "
                "created_at) VALUES (:id, :name, :mode, :fs, 'test', 'Eval Platform Ltd (fictional)', "
                "'GB00 EVAL 0000 0000 0000 00 (fictional)', :now)"
            ),
            {
                "id": org_id,
                "name": f"Eval org {org_id} (fictional)",
                "mode": mode,
                "fs": fail_safe,
                "now": clock.now(),
            },
        )
        conn.execute(text("INSERT INTO kill_switch (org_id, engaged) VALUES (:o, false)"), {"o": org_id})
        conn.execute(text("INSERT INTO demo_clock (org_id, offset_seconds) VALUES (:o, 0)"), {"o": org_id})
        for role in ROLES:
            uid = f"usr_{org_id[4:]}_{role}"
            conn.execute(
                text(
                    "INSERT INTO users (id, org_id, email, display_name, role, created_at) "
                    "VALUES (:id, :org, :email, :name, :role, :now)"
                ),
                {
                    "id": uid,
                    "org": org_id,
                    "email": f"{uid}@eval.invalid",
                    "name": f"Eval {role}",
                    "role": role,
                    "now": clock.now(),
                },
            )
            users[role] = uid
    return users


def make_env(  # noqa: PLR0912, PLR0915 - one block per setup option, in reading order
    world: World, scenario: dict[str, Any], *, seed: int, second: bool = False
) -> Env:
    """Build the organisation a scenario runs in, from its ``setup`` block."""
    from detent.api.auth import issue_key
    from detent.domain.money import Money
    from detent.intents.registry import seed_registry
    from detent.mandates.store import fixture_mandate, issue_mandate
    from detent.policy.schema import load_ruleset
    from detent.policy.store import install_ruleset
    from detent.rails.registry import install_rail

    setup = dict(scenario.get("setup") or {})
    rng = random.Random(seed)  # noqa: S311 - repeatable test data, not secrets
    clock = FrozenClock(START)
    org_id = f"org_e{secrets.token_hex(6)}"
    users = _insert_org(
        world.engine, clock, org_id, setup.get("mode", "auto"), setup.get("fail_safe", "manual_queue")
    )
    chain = world.start_chain() if setup.get("chain", True) else None
    bank = world.start_bank() if setup.get("bank", True) else None
    senders: dict[str, str] = {}
    sender_keys: dict[str, SecretStr] = {}
    payees: dict[str, str] = {}
    keys: dict[str, str] = {}
    policy_text = POLICY_TEXT
    if setup.get("policy_changes"):
        import yaml

        doc = yaml.safe_load(POLICY_TEXT)
        for path, value in setup["policy_changes"].items():
            cur = doc
            parts = path.split(".")
            for part in parts[:-1]:
                cur = cur[part]
            cur[parts[-1]] = value
        policy_text = yaml.safe_dump(doc, sort_keys=False)
    with world.engine.begin() as conn:
        install_ruleset(conn, clock, org_id, load_ruleset(policy_text), proposed_by="system:seed")
        seed_registry(conn, clock, org_id)
        now = clock.now()
        local_median = Money.parse(str(setup.get("local_median", "2000.00")), "USDC")
        conn.execute(
            text(
                "INSERT INTO counterparties (id, org_id, name, kyb_status, allowlisted, payment_count, "
                "median_amount_minor, median_currency, created_at) VALUES ('cpt_local', :o, "
                "'Local Supplier Ltd (fictional)', 'verified', true, 10, :m, 'USDC', :t)"
            ),
            {"o": org_id, "t": now, "m": local_median.amount_minor},
        )
        if chain is not None:
            for rail in USDC_RAILS:
                addr, key = chain.new_wallet(usdc_minor=1_000_000 * 10**6)
                senders[rail], sender_keys[rail] = addr, key
                install_rail(
                    conn,
                    org_id,
                    rail_id=rail,
                    kind="evm",
                    network=rail,
                    chain_id=31337,
                    currency="USDC",
                    token_address=chain.usdc,
                    from_address=addr,
                    confirmations=1,
                    prefunded_daily_limit=Money.parse(
                        str(setup.get("prefunded_daily_limit", "100000.00")), "USDC"
                    ),
                    est_fee_minor={"local-evm": 0, "base-sepolia": 2000, "eth-sepolia": 150000}[rail],
                    est_seconds={"local-evm": 1, "base-sepolia": 10, "eth-sepolia": 40}[rail],
                )
            for alias, dst in (
                ("local", None),
                ("bluefin", "dst_bluefin_base"),
                ("nova", "dst_nova_eth"),
                ("spare", None),
            ):
                payees[alias], _ = chain.new_wallet(eth_wei=0)
                if dst:
                    conn.execute(
                        text("UPDATE destinations SET address=:a WHERE org_id=:o AND id=:d"),
                        {"a": payees[alias], "o": org_id, "d": dst},
                    )
        else:
            payees["local"] = "0x" + rng.randbytes(20).hex()
        conn.execute(
            text(
                "INSERT INTO destinations (id, org_id, counterparty_id, kind, network, address, "
                "verified, "
                "first_seen_at, last_changed_at) VALUES ('dst_local', :o, 'cpt_local', 'evm_wallet', "
                "'local-evm', :a, true, :f, :f)"
            ),
            {"o": org_id, "a": payees["local"], "f": now - timedelta(days=100)},
        )
        for i, xd in enumerate(
            setup.get("extra_destinations", [])
        ):  # a payee's verified wallet on another network
            conn.execute(
                text(
                    "INSERT INTO destinations (id, org_id, counterparty_id, kind, network, address, "
                    "verified, "
                    "first_seen_at, last_changed_at) VALUES (:d, :o, :c, 'evm_wallet', :n, :a, true, :f, :f)"
                ),
                {
                    "d": f"dst_extra_{i}",
                    "o": org_id,
                    "c": xd["cpt"],
                    "n": xd["network"],
                    "a": payees[xd["alias"]],
                    "f": now - timedelta(days=100),
                },
            )
        if not second:  # a counterparty only this organisation has (cross-organisation attacks name it)
            conn.execute(
                text(
                    "INSERT INTO counterparties (id, org_id, name, kyb_status, allowlisted, payment_count, "
                    "created_at) VALUES ('cpt_primary_only', :o, 'Primary-only Supplier Ltd (fictional)', "
                    "'verified', true, 5, :t)"
                ),
                {"o": org_id, "t": now},
            )
            conn.execute(
                text(
                    "INSERT INTO destinations (id, org_id, counterparty_id, kind, network, address, "
                    "verified, "
                    "first_seen_at, last_changed_at) VALUES ('dst_primary_only', :o, 'cpt_primary_only', "
                    "'evm_wallet', 'local-evm', :a, true, :f, :f)"
                ),
                {"o": org_id, "a": payees["local"], "f": now - timedelta(days=100)},
            )
        if bank is not None:
            for rail, cur in (("banksim-fps", "GBP"), ("banksim-sepa-inst", "EUR")):
                install_rail(
                    conn,
                    org_id,
                    rail_id=rail,
                    kind="banksim",
                    network=rail,
                    currency=cur,
                    fee_flat_minor=20,
                    fee_bps=0,
                    per_payment_limit=Money.parse("25000.00", cur),
                    daily_limit=Money.parse("100000.00", cur),
                    base_url=bank,
                )
        for upd in setup.get("counterparties", []):
            cols = {k: v for k, v in upd.items() if k in ("kyb_status", "allowlisted", "payment_count")}
            for col, val in cols.items():
                conn.execute(
                    text(f"UPDATE counterparties SET {col}=:v WHERE org_id=:o AND id=:c"),  # noqa: S608 - fixed names
                    {"v": val, "o": org_id, "c": upd["id"]},
                )
        lead = users["payments_lead"]
        keys["lead"] = issue_key(conn, clock, org_id, lead, ALL_SCOPES, PEPPER)
        for role in ROLES:
            keys[role] = issue_key(conn, clock, org_id, users[role], ALL_SCOPES, PEPPER)
        for alias, spec in (setup.get("keys") or {}).items():
            keys[alias] = issue_key(
                conn,
                clock,
                org_id,
                users[spec.get("role", "payments_lead")],
                list(spec.get("scopes", ALL_SCOPES)),
                PEPPER,
                mandate_id=spec.get("mandate_id"),
            )
            if spec.get("revoked"):
                conn.execute(
                    text("UPDATE api_keys SET revoked_at=:t WHERE org_id=:o AND prefix=:p"),
                    {"t": now, "o": org_id, "p": keys[alias][:12]},
                )
            if spec.get("expired"):
                conn.execute(
                    text("UPDATE api_keys SET expires_at=:t WHERE org_id=:o AND prefix=:p"),
                    {"t": now - timedelta(minutes=1), "o": org_id, "p": keys[alias][:12]},
                )
        if setup.get("mandate", True):
            doc = fixture_mandate(clock, org_id)
            for k, v in (setup.get("mandate_scope") or {}).items():
                doc["scope"][k] = v
            issue_mandate(conn, clock, org_id, doc, MANDATE_KEY, actor=_seed_actor())
            keys["agent"] = issue_key(
                conn, clock, org_id, lead, ["intents:create", "read"], PEPPER, mandate_id=doc["mandate_id"]
            )
        if setup.get("org_expired"):
            conn.execute(
                text("UPDATE organisations SET expires_at=:t WHERE id=:o"),
                {"t": now - timedelta(days=1), "o": org_id},
                execution_options={"cross_org": "the organisations row is the org itself (evaluation setup)"},
            )
        if setup.get("kill_switch_engaged"):
            conn.execute(
                text("UPDATE kill_switch SET engaged=true, engaged_by=:u, engaged_at=:t WHERE org_id=:o"),
                {"u": users["oncall"], "t": now, "o": org_id},
            )
    extra: dict[str, Any] = {}
    if chain is not None:
        extra.update(
            local_evm_rpc_url=chain.proxy_url,
            base_sepolia_rpc_url=chain.proxy_url,
            eth_sepolia_rpc_url=chain.proxy_url,
            test_wallet_private_key_local=sender_keys["local-evm"],
            test_wallet_private_key_base=sender_keys["base-sepolia"],
            test_wallet_private_key_eth=sender_keys["eth-sepolia"],
        )
    if bank is not None:
        extra["banksim_url"] = bank
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=world.database_url,
        demo_org_id=org_id,
        demo_password=SecretStr("eval-demo-password-7"),
        session_secret=SecretStr("eval-session-secret-0123456789"),
        api_key_pepper=SecretStr(PEPPER),
        mandate_signing_key_demo=MANDATE_KEY,
        agent_llm="recorded",
        rail_timeout_seconds=1.0,
        log_json=True,
        # The suites drive hundreds of calls a minute through one key to measure DekernAI's checks; the
        # rate limiter (API-04) has its own tests and would only turn those calls into 429s here.
        api_rate_limit_per_minute=1_000_000,
        **extra,
    )
    env = Env(world, org_id, clock, rng, users, keys, settings, senders, payees)
    if setup.get("second_org") and not second:
        env.other = make_env(
            world, {"setup": {"chain": False, "bank": False, "mandate": False}}, seed=seed + 1, second=True
        )
    return env


def _seed_actor() -> Any:
    from detent.audit.log import Actor

    return Actor.system("seed")


def open_client(env: Env) -> Any:
    from detent.api.app import create_app
    from fastapi.testclient import TestClient

    app = create_app(env.settings, engine=env.engine, clock=env.clock, configure_logging=False)
    client = TestClient(app)
    client.__enter__()
    env.client = client
    return client


def close_env(env: Env) -> None:
    if env.client is not None:
        env.client.__exit__(None, None, None)
        env.client = None
    if env.other is not None:
        close_env(env.other)


def dumps(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True)
