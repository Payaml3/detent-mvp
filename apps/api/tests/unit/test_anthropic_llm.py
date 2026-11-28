"""AGT-01/AGT-06: AnthropicLLM's request shape and tool loop, against a fake SDK client (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS
from typing import Any

import pytest
from detent.agents.instruction import SCHEMA
from detent.agents.llm import AnthropicLLM
from detent.agents.tools import TOOLS


class FakeMessages:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.requests: list[dict[str, Any]] = []

    def create(self, **kw: Any) -> Any:
        self.requests.append(kw)
        return self.replies.pop(0)


def reply(stop: str, content: list[Any], model: str = "claude-sonnet-5-5") -> Any:
    return NS(stop_reason=stop, content=content, model=model, usage=NS(input_tokens=100, output_tokens=20))


def llm_with(replies: list[Any]) -> tuple[AnthropicLLM, FakeMessages]:
    fake = FakeMessages(replies)
    a = AnthropicLLM.__new__(AnthropicLLM)
    a._client = NS(beta=NS(messages=fake))  # type: ignore[attr-defined]
    return a, fake


def test_request_shape_and_tool_loop() -> None:
    answer = json.dumps({"ok": True})
    a, fake = llm_with(
        [
            reply(
                "tool_use",
                [NS(type="tool_use", id="tu_1", name="find_counterparty", input={"name": "Bluefin"})],
            ),
            reply("end_turn", [NS(type="text", text=answer)]),
        ]
    )
    seen: list[tuple[str, dict[str, Any]]] = []
    r = a.complete(
        model="claude-sonnet-5-5",
        system="sys",
        user="doc",
        schema=SCHEMA,
        tools=list(TOOLS.values()),
        tool_handler=lambda n, args: (seen.append((n, args)), "[]")[1],
    )
    assert r.raw_text == answer and r.tokens_in == 200 and r.tokens_out == 40 and r.source == "model"
    assert seen == [("find_counterparty", {"name": "Bluefin"})]
    req = fake.requests[0]
    assert req["model"] == "claude-sonnet-5-5" and req["output_config"]["format"]["type"] == "json_schema"
    assert not {"temperature", "top_p", "top_k", "tool_choice", "thinking"} & set(req)
    assert req["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in req["betas"]
    assert all(t["strict"] for t in req["tools"])
    second = fake.requests[1]["messages"]
    assert second[-1]["content"][0] == {"type": "tool_result", "tool_use_id": "tu_1", "content": "[]"}


def test_a_refusal_is_an_error_never_a_proposal() -> None:
    a, _ = llm_with([reply("refusal", [])])
    with pytest.raises(RuntimeError, match="declined"):
        a.complete(model="claude-sonnet-5-5", system="s", user="u", schema=SCHEMA)


def test_describe_error_gives_the_api_reason_without_secrets() -> None:
    from detent.agents.llm import describe_error

    class BadRequestError(Exception):
        status_code = 400

        def __init__(self, msg: str) -> None:
            super().__init__(msg)
            self.body = {
                "type": "error",
                "error": {"type": "invalid_request_error", "message": "tools.0: bad field"},
            }

    assert describe_error(BadRequestError("x")) == "BadRequestError (400): tools.0: bad field"
    leaked = RuntimeError("key sk-ant-api03-abcdefghijk rejected")
    assert "abcdefghijk" not in describe_error(leaked)
    assert describe_error(RuntimeError()) == "RuntimeError"
