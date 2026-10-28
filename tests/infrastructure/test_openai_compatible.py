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
    LLMContextOverflowError,
    LLMRequest,
    Message,
    OpenAICompatibleClient,
    Sampling,
    ToolCall,
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
    assert not response.truncated and response.max_tokens == 512
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


async def test_a_prompt_longer_than_the_window_is_refused_at_once_as_an_overflow(monkeypatch):
    refusal = {  # what vLLM 0.32 answers a prompt longer than its --max-model-len
        "error": {
            "message": "This model's maximum context length is 262144 tokens. However, your "
            "prompt contains 270000 input tokens, which exceeds this limit even without any "
            "output tokens. Please reduce the length of the input prompt.",
            "type": "BadRequestError",
            "param": "input_tokens",
            "code": 400,
        }
    }
    received: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        received.append(request)
        return httpx2.Response(400, json=refusal)

    client = _client(monkeypatch, handler, max_retries=3)
    with pytest.raises(LLMContextOverflowError, match="maximum context length is 262144"):
        await client.stream(_request())
    assert len(received) == 1

    _, other = _refusing(400)  # any other refused request is no overflow
    with pytest.raises(LLMCallError) as refused:
        await _client(monkeypatch, other).complete(_request())
    assert not isinstance(refused.value, LLMContextOverflowError)


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


async def test_a_request_goes_to_the_replica_it_names(monkeypatch):
    ranks: list[str | None] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        ranks.append(request.headers.get("X-data-parallel-rank"))
        if json.loads(request.content).get("stream"):
            return _sse(STREAM)
        return httpx2.Response(200, json=_completion("ok"))

    two = _client(monkeypatch, handler, replicas=2)
    for replica in (0, 1, 2, 3, None):
        await two.complete(_request(replica=replica))
    await two.stream(_request(replica=5))
    await _client(monkeypatch, handler).complete(_request(replica=1))  # a server of one
    assert ranks == ["0", "1", "0", "1", None, "1", None]


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


TOOLS = (
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a file.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    },
)


async def test_tool_calls_are_sent_and_read_back(monkeypatch):
    bodies: list[dict] = []
    calls = [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "write_file", "arguments": '{"a": 1}'},
        },
        {"id": "c2", "type": "function", "function": {"name": "write_file", "arguments": '{"a": '}},
    ]
    completion = _completion(None, finish_reason="tool_calls", tool_calls=calls)
    completion["usage"] |= {
        "prompt_tokens_details": {"cached_tokens": 8},
        "completion_tokens_details": {"reasoning_tokens": 3},
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=completion)

    client = _client(monkeypatch, handler, extra_body={"top_k": 20, "chat_template_kwargs": {}})
    earlier = ToolCall(id="c0", name="write_file", arguments={"path": "a.md"})
    messages = (
        Message(role="user", content="Go."),
        Message(role="assistant", content="", tool_calls=(earlier,)),
        Message(role="tool", content="Wrote a.md.", tool_call_id="c0"),
    )
    response = await client.complete(
        LLMRequest(
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            reasoning_effort="low",
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    )
    body = bodies[0]
    assert body["messages"][1]["tool_calls"] == [
        {
            "id": "c0",
            "type": "function",
            "function": {"name": "write_file", "arguments": '{"path": "a.md"}'},
        }
    ]
    assert body["messages"][2] == {"role": "tool", "content": "Wrote a.md.", "tool_call_id": "c0"}
    assert body["tools"] == list(TOOLS) and body["tool_choice"] == "auto"
    assert body["reasoning_effort"] == "low" and body["top_k"] == 20
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    readable, unreadable = response.tool_calls
    assert readable == ToolCall(id="c1", name="write_file", arguments={"a": 1})
    assert unreadable.arguments == {} and unreadable.unreadable == '{"a": '
    assert response.finish_reason == "tool_calls" and not response.truncated
    assert response.usage == Usage(
        prompt_tokens=11, completion_tokens=5, cached_prompt_tokens=8, reasoning_tokens=3
    )


def _chunk(delta: dict | None = None, finish_reason: str | None = None, usage: dict | None = None):
    choices = (
        [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": finish_reason}]
    )
    chunk = {"id": "s", "object": "chat.completion.chunk", "created": 0, "model": "served"}
    return {**chunk, "choices": choices, "usage": usage}


def _sse(chunks: list[dict], *, delay: float = 0.0, done: bool = True):
    async def body():
        for chunk in chunks:
            await asyncio.sleep(delay)
            yield f"data: {json.dumps(chunk)}\n\n".encode()
        if done:
            yield b"data: [DONE]\n\n"

    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body())


STREAM = [
    _chunk({"role": "assistant", "reasoning_content": "I should "}),
    _chunk({"reasoning_content": "write it."}),
    _chunk({"content": "Writing "}),
    _chunk({"content": "now."}),
    _chunk(
        {
            "tool_calls": [
                {"index": 0, "id": "c9", "function": {"name": "write_file", "arguments": ""}}
            ]
        }
    ),
    _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"path": '}}]}),
    _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"a.md"}'}}]}),
    _chunk({}, finish_reason="tool_calls"),
    _chunk(
        usage={
            "prompt_tokens": 40,
            "completion_tokens": 9,
            "total_tokens": 49,
            "prompt_tokens_details": {"cached_tokens": 32},
        }
    ),
]


async def test_a_stream_is_accumulated_into_one_reply(monkeypatch):
    bodies: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return _sse(STREAM)

    response = await _client(monkeypatch, handler).stream(_request(tools=TOOLS))
    assert bodies[0]["stream"] is True and bodies[0]["stream_options"] == {"include_usage": True}
    assert response.text == "Writing now." and response.reasoning == "I should write it."
    assert response.tool_calls == (
        ToolCall(id="c9", name="write_file", arguments={"path": "a.md"}),
    )
    assert response.finish_reason == "tool_calls"
    assert response.usage == Usage(prompt_tokens=40, completion_tokens=9, cached_prompt_tokens=32)


async def test_a_stream_that_breaks_off_is_retried_from_its_start(monkeypatch):
    async def wait(seconds: float) -> None:
        pass

    def broken() -> httpx2.Response:
        async def body():
            for chunk in STREAM[:4]:
                yield f"data: {json.dumps(chunk)}\n\n".encode()
            raise httpx2.RemoteProtocolError("peer closed connection")

        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body())

    responses = [broken(), _sse(STREAM)]
    monkeypatch.setattr(asyncio, "sleep", wait)
    response = await _client(monkeypatch, lambda request: responses.pop(0)).stream(_request())
    assert not responses
    assert response.text == "Writing now." and response.reasoning == "I should write it."


@pytest.mark.parametrize("done", [True, False], ids=["closed", "cut"])
async def test_a_stream_that_ends_without_a_finish_reason_is_a_failed_call(monkeypatch, done):
    async def wait(seconds: float) -> None:
        pass

    monkeypatch.setattr(asyncio, "sleep", wait)
    received: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        received.append(request)
        return _sse(STREAM[:4], done=done)  # text, then the end, with no finish reason

    with pytest.raises(LLMCallError, match="without a finish reason"):
        await _client(monkeypatch, handler).stream(_request())
    assert len(received) == 3


@pytest.mark.parametrize("streamed", [False, True], ids=["complete", "stream"])
async def test_a_reply_the_server_aborted_is_retried_like_a_dropped_connection(
    monkeypatch, streamed
):
    async def wait(seconds: float) -> None:
        pass

    def answer(finish_reason: str) -> httpx2.Response:
        if streamed:
            return _sse([_chunk({"content": "Writing "}), _chunk({}, finish_reason=finish_reason)])
        return httpx2.Response(200, json=_completion("", finish_reason=finish_reason))

    monkeypatch.setattr(asyncio, "sleep", wait)
    received: list[httpx2.Request] = []
    finishes = ["abort", "abort", "stop"]

    def handler(request: httpx2.Request) -> httpx2.Response:
        received.append(request)
        return answer(finishes.pop(0) if finishes else "abort")

    client = _client(monkeypatch, handler)
    call = client.stream if streamed else client.complete
    response = await call(_request())
    assert response.finish_reason == "stop" and len(received) == 3

    received.clear()
    with pytest.raises(LLMCallError, match="aborted"):
        await call(_request())
    assert len(received) == 3
