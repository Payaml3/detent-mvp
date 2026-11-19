"""Shared fixtures.

Database tests run against ``TEST_DATABASE_URL`` (default: the ``detent_test`` database from
``make db``). The schema is dropped and migrated once per session. Tests isolate themselves by
creating a fresh organisation each: every query is scoped by org_id, so no cleanup is needed (and
the append-only tables couldn't be cleaned anyway).
"""

from __future__ import annotations

import os
import secrets
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from detent.api.app import create_app
from detent.clock import FrozenClock
from detent.db.engine import make_engine
from detent.domain.roles import Role
from detent.settings import REPO_ROOT, Settings
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://detent:detent@localhost:5432/detent_test"
)
TESTS_DIR = Path(__file__).parent
DEMO_PASSWORD = "test-demo-password-7"
# Key prefixes, assembled at runtime so secret scanners never see a key-shaped literal in tests.
FAKE_TEST = "sk_" + "test_"
FAKE_LIVE = "sk_" + "live_"


def _migrate(url: str) -> None:
    raw = create_engine(url)
    with raw.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS detent CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS testsupport CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS banksim CASCADE"))  # the bank simulator's own tables
    raw.dispose()
    cfg = Config(str(REPO_ROOT / "apps" / "api" / "alembic.ini"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")
    raw = create_engine(url)
    with raw.begin() as conn:
        conn.execute(text("CREATE SCHEMA testsupport"))
        conn.execute(
            text(
                "CREATE TABLE testsupport.side_effects ("
                " id BIGSERIAL PRIMARY KEY, org_id TEXT NOT NULL, job_id TEXT NOT NULL, attempt INT NOT NULL)"
            )
        )
    raw.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    try:
        _migrate(TEST_DB_URL)
    except Exception as exc:  # pragma: no cover - environment problem
        pytest.fail(
            f"test database unavailable at {TEST_DB_URL}: run `make db` ({type(exc).__name__}: {exc})"
        )
    eng = make_engine(TEST_DB_URL, pool_size=20)
    yield eng
    eng.dispose()


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@dataclass
class OrgFixture:
    id: str
    users: dict[Role, str]


def make_org(engine: Engine, clock: FrozenClock, kind: str = "test") -> OrgFixture:
    org_id = f"org_t{secrets.token_hex(6)}"
    users: dict[Role, str] = {}
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organisations (id, name, mode, fail_safe, kind, created_at) "
                "VALUES (:id, :name, 'auto', 'manual_queue', :kind, :now)"
            ),
            {"id": org_id, "name": f"Test org {org_id} (fictional)", "kind": kind, "now": clock.now()},
        )
        conn.execute(text("INSERT INTO kill_switch (org_id, engaged) VALUES (:o, false)"), {"o": org_id})
        conn.execute(text("INSERT INTO demo_clock (org_id, offset_seconds) VALUES (:o, 0)"), {"o": org_id})
        for role in Role:
            uid = f"usr_{org_id[4:]}_{role.value}"
            conn.execute(
                text(
                    "INSERT INTO users (id, org_id, email, display_name, role, created_at) "
                    "VALUES (:id, :org, :email, :name, :role, :now)"
                ),
                {
                    "id": uid,
                    "org": org_id,
                    "email": f"{uid}@test.invalid",
                    "name": f"Test {role.value}",
                    "role": role.value,
                    "now": clock.now(),
                },
            )
            users[role] = uid
    return OrgFixture(org_id, users)


@pytest.fixture
def org(engine: Engine, clock: FrozenClock) -> OrgFixture:
    return make_org(engine, clock)


def make_settings(org_id: str, **kw: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "test",
        "database_url": TEST_DB_URL,
        "demo_org_id": org_id,
        "demo_password": SecretStr(DEMO_PASSWORD),
        "session_secret": SecretStr("test-session-secret-0123456789"),
        "api_key_pepper": SecretStr("test-pepper-abcdef123456"),
        "log_json": True,
    }
    base.update(kw)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg, arg-type]


@pytest.fixture
def settings(org: OrgFixture) -> Settings:
    return make_settings(org.id)


@pytest.fixture
def client(settings: Settings, engine: Engine, clock: FrozenClock) -> Iterator[TestClient]:
    app = create_app(settings, engine=engine, clock=clock, configure_logging=False)
    with TestClient(app) as c:
        yield c


def login(client: TestClient, user_id: str | None = None) -> None:
    r = client.post("/console/login", data={"password": DEMO_PASSWORD}, follow_redirects=False)
    assert r.status_code == 303, r.text
    if user_id:
        r = client.post("/console/act-as", data={"user_id": user_id}, follow_redirects=False)
        assert r.status_code == 303, r.text


def have_foundry() -> bool:
    return bool(shutil.which("anvil") or (Path.home() / ".foundry" / "bin" / "anvil").exists())


def child_env(**extra: str) -> dict[str, str]:
    """Environment for subprocesses (worker, CLI) pointed at the test database."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DATABASE_URL", "RAILS_CONFIG"))}
    env.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": TEST_DB_URL,
            "PYTHONPATH": str(TESTS_DIR),
            "LOG_JSON": "true",
            "PATH": f"{Path.home() / '.foundry' / 'bin'}:{env.get('PATH', '')}",
        }
    )
    env.update(extra)
    return env


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """In CI (REQUIRE_CHAIN=1) the local-chain tests must run; a missing anvil is an error, not a skip."""
    if os.environ.get("REQUIRE_CHAIN") == "1" and not have_foundry():
        raise pytest.UsageError("REQUIRE_CHAIN=1 but anvil is not installed")


@pytest.fixture(scope="module")
def chain() -> Iterator[Any]:
    """A local anvil chain with MockUSDC, one per test module (S2 onwards)."""
    import socket

    from detent import devchain

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    proc = devchain.start_anvil(port)
    try:
        yield devchain.deploy(f"http://127.0.0.1:{port}")
    finally:
        proc.terminate()


@pytest.fixture(scope="module")
def chain_b() -> Iterator[Any]:
    """A second local chain, for failover between two rails (S4)."""
    import socket

    from detent import devchain

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    proc = devchain.start_anvil(port)
    try:
        yield devchain.deploy(f"http://127.0.0.1:{port}")
    finally:
        proc.terminate()
