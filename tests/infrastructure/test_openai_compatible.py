"""The OpenAI-compatible client against an in-process HTTP transport; no network is used."""

import asyncio
import json
from typing import Any

import httpx2
import pytest

from infrastructure.llm import (
    LLMBusyError,
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
        **{"max_retries": 0, **settings},
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
        structured_output="json_schema",
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
    await client.complete(_request(json_schema={"type": "object"}, after_invalid=True))
    assert [body.get("response_format") for body in bodies] == [expected, None, expected]
    assert bodies[1]["model"] == "served" and "temperature" not in bodies[1]

    bodies.clear()
    client = _client(monkeypatch, handler, structured_output=mode, structured_retry="json_schema")
    await client.complete(_request(json_schema={"type": "object"}))
    await client.complete(_request(json_schema={"type": "object"}, after_invalid=True))
    assert [body.get("response_format", {}).get("type") for body in bodies] == [
        expected and expected["type"],
        "json_schema",
    ]


def _refusing(*failures: Any) -> tuple[list[httpx2.Request], Any]:
    """A handler that fails as `failures` say, one per call (an HTTP status, or an exception
    to raise), and then answers; and the requests it received."""
    received: list[httpx2.Request] = []
    pending = list(failures)

    def handler(request: httpx2.Request) -> httpx2.Response:
        received.append(request)
        if not pending:
            return httpx2.Response(200, json=_completion("{}"))
        failure = pending.pop(0)
        if isinstance(failure, Exception):
            raise failure
        return httpx2.Response(failure, json={"error": {"message": "no"}})

    return received, handler


async def test_rate_limits_and_timeouts_are_retried_with_backoff_until_they_run_out(monkeypatch):
    waits: list[float] = []

    async def wait(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", wait)
    timeout = httpx2.ReadTimeout("slow")
    received, handler = _refusing(429, timeout, 429)
    client = _client(monkeypatch, handler, max_retries=3, backoff=4.0)
    assert (await client.complete(_request())).text == "{}"
    assert len(received) == 4
    assert len(waits) == 3 and 2 <= waits[0] <= 4 <= waits[1] <= 8 <= waits[2] <= 16

    received, handler = _refusing(429, 429, 429)
    with pytest.raises(LLMBusyError, match="3 call"):
        await _client(monkeypatch, handler, max_retries=2, backoff=0.5).complete(_request())
    assert len(received) == 3


@pytest.mark.parametrize(
    ("failure", "calls"),
    [(401, 1), (400, 1), (500, 3), (httpx2.ConnectError("refused"), 3)],
    ids=["authentication", "bad-request", "server-error", "unreachable"],
)
async def test_any_other_failure_is_final_after_at_most_two_quick_retries(
    monkeypatch, failure, calls
):
    async def wait(seconds: float) -> None:
        pass

    monkeypatch.setattr(asyncio, "sleep", wait)
    received, handler = _refusing(*[failure] * 9)
    with pytest.raises(LLMCallError):
        await _client(monkeypatch, handler, max_retries=8).complete(_request())
    assert len(received) == calls

    received, handler = _refusing(failure, failure)
    if calls > 1:  # a dropped connection or a passing server error is not the server gone
        assert (await _client(monkeypatch, handler).complete(_request())).text == "{}"


async def test_replies_cut_off_or_empty_are_returned_for_the_caller_to_judge(monkeypatch):
    empty = httpx2.Response(200, json=_completion(None, reasoning_content="Thinking..."))
    response = await _client(monkeypatch, lambda request: empty).complete(_request())
    assert (response.text, response.truncated, response.reasoning) == ("", False, "Thinking...")
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
