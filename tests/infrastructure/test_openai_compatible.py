"""The OpenAI-compatible client against an in-process HTTP transport; no network is used."""

import asyncio
import json
from typing import Any

import httpx2
import pytest

from infrastructure.llm import (
    LLMCallError,
    LLMConfig,
    LLMConfigError,
    LLMRequest,
    Message,
    OpenAICompatibleClient,
    Sampling,
    Usage,
)

KEY_VARIABLE = "SOCIO_EVO_TEST_LLM_KEY"


def _completion(content: str | None, finish_reason: str = "stop", **message: Any) -> dict:
    return {
        "id": "completion-1",
        "object": "chat.completion",
        "created": 0,
        "model": "served",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content, **message},
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
    }


def _client(monkeypatch, handler, **settings: Any) -> OpenAICompatibleClient:
    monkeypatch.setenv(KEY_VARIABLE, "secret")
    config = LLMConfig(
        base_url="http://llm.test/v1",
        api_key_env=KEY_VARIABLE,
        model="served",
        max_retries=0,
        **settings,
    )
    transport = httpx2.MockTransport(handler)
    return OpenAICompatibleClient(config, http_client=httpx2.AsyncClient(transport=transport))


def _request(**fields: Any) -> LLMRequest:
    return LLMRequest(
        messages=(Message(role="user", content="Decide."),), metadata={"agent": "ana"}, **fields
    )


async def test_request_body_and_response_mapping(monkeypatch):
    bodies: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["authorization"] == "Bearer secret"
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=_completion('{"a": 1}', reasoning_content="Hmm."))

    client = _client(
        monkeypatch,
        handler,
        sampling=Sampling(temperature=0.6, max_tokens=512),
        extra_body={"chat_template_kwargs": {"enable_thinking": True}},
    )
    schema = {"type": "object"}
    response = await client.complete(
        _request(model="adapter-7", sampling=Sampling(temperature=0.0), json_schema=schema)
    )
    assert bodies[0] == {
        "model": "adapter-7",
        "messages": [{"role": "user", "content": "Decide."}],
        "temperature": 0.0,
        "max_tokens": 512,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": schema},
        },
        "chat_template_kwargs": {"enable_thinking": True},
    }
    assert response.text == '{"a": 1}' and response.reasoning == "Hmm."
    assert response.usage == Usage(prompt_tokens=11, completion_tokens=5)
    assert response.latency >= 0


@pytest.mark.parametrize(
    ("mode", "expected"), [("json_object", {"type": "json_object"}), ("none", None)]
)
async def test_structured_output_mode_controls_response_format(monkeypatch, mode, expected):
    bodies: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=_completion("{}"))

    client = _client(monkeypatch, handler, structured_output=mode)
    await client.complete(_request(json_schema={"type": "object"}))
    await client.complete(_request())
    assert [body.get("response_format") for body in bodies] == [expected, None]
    assert bodies[1]["model"] == "served" and "temperature" not in bodies[1]


@pytest.mark.parametrize(
    "reply",
    [
        httpx2.Response(500, json={"error": {"message": "overloaded"}}),
        httpx2.Response(200, json=_completion(None, reasoning_content="Thinking...")),
    ],
    ids=["server-error", "empty"],
)
async def test_unusable_replies_raise(monkeypatch, reply):
    client = _client(monkeypatch, lambda request: reply)
    with pytest.raises(LLMCallError):
        await client.complete(_request())


async def test_a_reply_cut_off_by_the_token_limit_is_returned_marked(monkeypatch):
    for text, finish_reason in (('{"a": ', "length"), (None, "length"), ("{}", "stop")):
        reply = httpx2.Response(200, json=_completion(text, finish_reason=finish_reason))
        response = await _client(monkeypatch, lambda request, reply=reply: reply).complete(
            _request()
        )
        assert (response.text, response.truncated) == (text or "", finish_reason == "length")


async def test_concurrency_is_bounded(monkeypatch):
    active = peak = 0

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx2.Response(200, json=_completion("ok"))

    client = _client(monkeypatch, handler, max_concurrency=2)
    await asyncio.gather(*(client.complete(_request()) for _ in range(5)))
    assert peak == 2


def test_missing_api_key_fails_at_construction(monkeypatch):
    monkeypatch.delenv(KEY_VARIABLE, raising=False)
    config = LLMConfig(base_url="http://llm.test/v1", api_key_env=KEY_VARIABLE, model="served")
    with pytest.raises(LLMConfigError, match=KEY_VARIABLE):
        OpenAICompatibleClient(config)
