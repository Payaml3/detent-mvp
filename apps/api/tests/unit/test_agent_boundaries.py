"""AGT-03 and AGT-06: the agent package can only propose, and every model call goes through LLMClient."""

from __future__ import annotations

import ast
from pathlib import Path

from detent.settings import REPO_ROOT

SRC = REPO_ROOT / "apps" / "api" / "src"
FORBIDDEN = ("detent.execution", "detent.rails", "detent.exceptions", "detent.intents.service")


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


def _module_file(name: str) -> Path | None:
    base = SRC / Path(*name.split("."))
    for p in (base.with_suffix(".py"), base / "__init__.py"):
        if p.exists():
            return p
    return None


def test_agents_never_reach_execution_approval_or_rails_even_indirectly() -> None:
    seen: set[str] = set()
    todo = [f"detent.agents.{p.stem}" for p in (SRC / "detent" / "agents").glob("*.py")]
    chains: dict[str, str] = {}
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        seen.add(mod)
        f = _module_file(mod)
        if f is None:
            continue
        for imp in _imports(f):
            if imp.startswith("detent"):
                chains.setdefault(imp, mod)
                todo.append(imp)
    bad = sorted(m for m in seen if m.startswith(FORBIDDEN))
    assert bad == [], {m: chains.get(m) for m in bad}


def test_only_llm_module_imports_the_model_sdk() -> None:
    users = [p.relative_to(SRC) for p in (SRC / "detent").rglob("*.py") if "anthropic" in _imports(p)]
    assert [str(u) for u in users] == ["detent/agents/llm.py"]


def test_agent_tools_are_read_only_except_propose() -> None:
    from detent.agents.tools import TOOLS, WRITE_TOOLS

    assert {"propose_payment_intent"} == WRITE_TOOLS
    assert {"find_counterparty", "get_destinations", "get_mandate"} <= set(TOOLS)
    for name, tool in TOOLS.items():
        # Not strict: strict tools plus the structured output exceed the API's grammar limit (live demo,
        # 400 "compiled grammar is too large"); AnthropicLLM keeps only string arguments instead.
        assert "strict" not in tool and tool["input_schema"]["additionalProperties"] is False, name


def test_models_come_from_settings() -> None:
    from conftest import make_settings

    s = make_settings("org_x")
    assert (s.model_agent, s.model_light, s.model_eval_judge) == (
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-opus-5-5",
    )
    hard = [
        p for p in (SRC / "detent").rglob("*.py") if p.name != "settings.py" and '"claude-' in p.read_text()
    ]
    assert hard == [], hard
