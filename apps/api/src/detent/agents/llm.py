"""One interface for model calls (AGT-06, spec/05 "Wrap all calls in LLMClient").

``AnthropicLLM`` calls the Claude API through the official SDK. ``RecordedLLM`` serves stored responses
for tests, offline demos and replay; it never calls a model. A second provider would be another class
with the same ``complete`` method.

Model IDs always come from settings (``model_agent``, ``model_light``, ``model_eval_judge``).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

_log = logging.getLogger("detent.agents")
_KEYISH = re.compile(r"\bsk[-_][A-Za-z0-9_-]{6,}")


def describe_error(exc: BaseException) -> str:
    """A short, secret-free reason for a failed model call, for the MODEL_UNAVAILABLE flag and the log.

    An API error carries the API's own message (for example which request field it rejected or that the
    credit balance is too low); without it a person cannot tell why the agent handed over.
    """
    name = type(exc).__name__
    message = ""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            message = err["message"]
    if not message:
        message = str(exc)
    message = _KEYISH.sub("[REDACTED]", " ".join(message.split()))[:300]
    status = getattr(exc, "status_code", None)
    reason = f"{name} ({status}): {message}" if status else (f"{name}: {message}" if message else name)
    _log.warning("model call failed: %s", reason)
    return reason


def _string_args(raw: Any) -> dict[str, str]:
    """Tool inputs, keeping only string values. The tools are not sent as strict (with the structured
    output that made the API's compiled grammar too large), so their input is checked here instead:
    every tool takes string arguments, and a tool that misses one returns an error, not data."""
    return {k: v for k, v in dict(raw or {}).items() if isinstance(k, str) and isinstance(v, str)}


# Read-only tools the model may call while extracting; the handler runs them and returns JSON text.
ToolHandler = Callable[[str, dict[str, Any]], str]


@dataclass(frozen=True, slots=True)
class LLMResult:
    raw_text: str
    model: str
    served_model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    source: str = "model"  # model | recording


class LLMClient(Protocol):
    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
        tool_handler: ToolHandler | None = None,
    ) -> LLMResult: ...


class AnthropicLLM:
    """Claude through the Anthropic SDK: structured output (a JSON schema), read-only tools (not
    strict; inputs are checked here), and the server-side refusal fallback. No sampling parameters are sent."""

    MAX_TOOL_TURNS = 6

    def __init__(self, api_key: str | None = None, *, timeout_seconds: float = 120.0) -> None:
        import anthropic

        self._anthropic = anthropic
        self._client = (
            anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)
            if api_key
            else anthropic.Anthropic(timeout=timeout_seconds)
        )

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
        tool_handler: ToolHandler | None = None,
    ) -> LLMResult:
        started = time.perf_counter()  # duration only; domain time comes from the Clock
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        tokens_in = tokens_out = 0
        served = model
        for _ in range(self.MAX_TOOL_TURNS + 1):
            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": 16000,
                "system": system,
                "messages": messages,
                "output_config": {"format": {"type": "json_schema", "schema": schema}},
                # On a safety decline, the API re-runs the request on a fallback model in the same call.
                "betas": ["server-side-fallback-2026-07-01"],
                "fallbacks": "default",
            }
            if tools:
                kwargs["tools"] = tools
            resp = self._client.beta.messages.create(**kwargs)
            tokens_in += int(resp.usage.input_tokens)
            tokens_out += int(resp.usage.output_tokens)
            served = str(resp.model)
            if resp.stop_reason == "refusal":
                raise RuntimeError("the model declined the request")
            if resp.stop_reason == "tool_use" and tool_handler is not None:
                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": tool_handler(block.name, _string_args(block.input)),
                            }
                        )
                messages.append({"role": "user", "content": results})
                continue
            text = next((b.text for b in resp.content if b.type == "text"), "")
            return LLMResult(
                text, model, served, tokens_in, tokens_out, int((time.perf_counter() - started) * 1000)
            )
        raise RuntimeError("too many tool turns")


class RecordedLLM:
    """Serves stored model outputs. A recording applies when its ``match`` text appears in the prompt
    (the longest match wins); ``{{PLACEHOLDER}}`` values are filled from ``placeholders``."""

    def __init__(
        self, recordings: list[dict[str, Any]], placeholders: Mapping[str, str] | None = None
    ) -> None:
        self.recordings = recordings
        self.placeholders = dict(placeholders or {})

    @classmethod
    def from_dir(cls, path: Path, placeholders: Mapping[str, str] | None = None) -> RecordedLLM:
        recs = [json.loads(p.read_text()) for p in sorted(path.glob("*.json"))]
        return cls(recs, placeholders)

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
        tool_handler: ToolHandler | None = None,
    ) -> LLMResult:
        hits = [r for r in self.recordings if r["match"] in user]
        if not hits:
            raise LookupError("no recording matches this document")
        rec = max(hits, key=lambda r: len(r["match"]))
        raw = json.dumps(rec["output"])
        for k, v in self.placeholders.items():
            raw = raw.replace("{{" + k + "}}", v)
        usage = rec.get("usage", {})
        return LLMResult(
            raw,
            model,
            model,
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
            0,
            source="recording",
        )


def llm_for(
    settings: Any, placeholders: Mapping[str, str] | None = None, kind: str = "instruction"
) -> tuple[LLMClient, str]:
    """The client the product uses, and a label the console shows ("Claude API" or "Recorded response")."""
    from detent.settings import REPO_ROOT

    mode = settings.agent_llm
    if mode == "anthropic" or (mode == "auto" and settings.anthropic_api_key is not None):
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        return AnthropicLLM(key), "Claude API"
    return (
        RecordedLLM.from_dir(REPO_ROOT / "fixtures" / "agent-recordings" / kind, placeholders),
        "Recorded response (offline stand-in, not a live model call)",
    )
