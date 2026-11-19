"""Which model answers the agent steps in a run.

By default every agent answer is a recorded stand-in from ``fixtures/agent-recordings/`` (hand-written
until real runs are recorded), so a run is repeatable, costs nothing and needs no key. The report says
so on every agent figure. ``--live`` uses the Claude API with the model from settings; it needs
``ANTHROPIC_API_KEY`` and is meant for the nightly run.

A scenario can pin one recording (``recording: injection-followed``) to stand in for a model that did
the wrong thing, such as following an injected instruction: the code-side checks must still catch it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from detent.agents.llm import AnthropicLLM, LLMClient, RecordedLLM
from detent.settings import REPO_ROOT

RECORDINGS = REPO_ROOT / "fixtures" / "agent-recordings"
LIVE = {"on": False}


def live_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def source_label() -> str:
    return "Claude API (live)" if LIVE["on"] else "recorded stand-in (hand-written, not a live model call)"


def client_for(
    env: Any, placeholders: Mapping[str, str], recording: str | None = None, kind: str = "instruction"
) -> tuple[LLMClient, str]:
    model = str(env.settings.model_agent)
    if LIVE["on"] and recording is None:
        return AnthropicLLM(os.environ["ANTHROPIC_API_KEY"]), model
    if recording:
        rec = json.loads((RECORDINGS / kind / f"{recording}.json").read_text())
        rec = {**rec, "match": ""}  # pinned: answers whatever the document says
        return RecordedLLM([rec], placeholders), model
    return RecordedLLM.from_dir(RECORDINGS / kind, placeholders), model


def recording_for(document: str, kind: str = "instruction") -> dict[str, Any] | None:
    """The recording the stand-in client would choose for a document (longest match wins)."""
    recs = [json.loads(p.read_text()) for p in sorted((RECORDINGS / kind).glob("*.json"))]
    hits = [r for r in recs if r["match"] in document]
    return max(hits, key=lambda r: len(r["match"])) if hits else None
