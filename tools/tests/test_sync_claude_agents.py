"""Tests for tools/sync_claude_agents.py: Codex role definitions become valid Claude Code agents."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import sync_claude_agents as sca  # noqa: E402


def frontmatter(text: str) -> dict:
    """Parse the flat frontmatter; a value with ': ' in it must be a JSON (YAML double-quoted) string."""
    assert text.startswith("---\n")
    out = {}
    for line in text.split("---\n")[1].splitlines():
        key, _, value = line.partition(": ")
        if value.startswith('"'):
            value = json.loads(value)
        else:
            assert ": " not in value and not value.startswith(("'", "[", "{")), line
        out[key] = value
    return out


def test_every_codex_role_has_a_current_claude_agent():
    wanted = sca.build()
    assert {p.stem for p in wanted} == {p.stem for p in sca.SRC.glob("*.toml")}
    for path, text in wanted.items():
        assert path.read_text(encoding="utf-8") == text, f"{path.name} is stale; run sync_claude_agents.py"


def test_frontmatter_is_valid_and_maps_models_and_tools():
    agents = {p.stem: frontmatter(t) for p, t in sca.build().items()}
    for name, fm in agents.items():
        assert fm["name"] == name
        assert fm["description"]
        assert fm["model"] in {"opus", "sonnet", "inherit"}
    # Board advisors and research are read-only in Codex, so they get read-only tools here.
    for name in ("risk-advisor", "owner-advisor", "growth-advisor", "customer-advisor", "research"):
        assert "Edit" not in agents[name]["tools"] and "Bash" not in agents[name]["tools"]
    # Builders keep every tool; the engineer runs on the session's model (strongest for money paths).
    assert "tools" not in agents["engineer"] and agents["engineer"]["model"] == "inherit"


def test_render_quotes_descriptions_with_colons():
    text = sca.render(
        {"name": "x", "description": "lens: a, b", "model": "gpt-6.2-sol", "developer_instructions": "Body"}
    )
    fm = frontmatter(text)
    assert fm["description"] == "lens: a, b" and fm["model"] == "sonnet"
    assert text.rstrip().endswith("Body")
