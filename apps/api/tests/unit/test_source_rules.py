"""Static rules over the detent package source.

- Invariant 17: no direct datetime.now()/utcnow()/today()/time.time() outside detent/clock.py.
- FND-02: no module reads os.environ or os.getenv except detent/settings.py.
- Invariant 15: no float literals or float() calls in money code (domain/money.py).
"""

from __future__ import annotations

import ast
from pathlib import Path

import detent
import pytest

PKG = Path(detent.__file__).parent
SOURCES = sorted(PKG.rglob("*.py"))
TIME_CALLS = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("date", "today"),
    ("time", "time"),
}


def _rel(p: Path) -> str:
    return p.relative_to(PKG).as_posix()


def _attr_chain(node: ast.AST) -> tuple[str, ...]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return tuple(reversed(parts))


def test_sources_found() -> None:
    assert len(SOURCES) > 10


@pytest.mark.parametrize("path", SOURCES, ids=_rel)
def test_no_direct_time(path: Path) -> None:
    if _rel(path) == "clock.py":
        return
    tree = ast.parse(path.read_text())
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            chain = _attr_chain(node.func)
            if len(chain) >= 2 and chain[-2:] in TIME_CALLS:
                bad.append(f"line {node.lineno}: {'.'.join(chain)}()")
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "time"
            and any(a.name == "time" for a in node.names)
        ):
            bad.append(f"line {node.lineno}: from time import time")
    assert not bad, f"{_rel(path)} reads time directly; use detent.clock.Clock: {bad}"


@pytest.mark.parametrize("path", SOURCES, ids=_rel)
def test_environment_only_read_in_settings(path: Path) -> None:
    if _rel(path) == "settings.py":
        return
    tree = ast.parse(path.read_text())
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _attr_chain(node) in {
            ("os", "environ"),
            ("os", "getenv"),
            ("os", "environb"),
        }:
            bad.append(node.lineno)
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "os"
            and any(a.name in {"environ", "getenv", "environb"} for a in node.names)
        ):
            bad.append(node.lineno)
    assert not bad, f"{_rel(path)} reads the environment at lines {bad}; use detent.settings"


def test_money_module_has_no_floats() -> None:
    tree = ast.parse((PKG / "domain" / "money.py").read_text())
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), node.lineno
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"float", "round"}, node.lineno


def test_domain_package_does_no_io() -> None:
    forbidden = {
        "sqlalchemy",
        "httpx",
        "fastapi",
        "web3",
        "detent.db",
        "detent.settings",
        "requests",
        "socket",
    }
    for path in (PKG / "domain").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not any(n == f or n.startswith(f + ".") for f in forbidden), f"{path.name} imports {n}"
