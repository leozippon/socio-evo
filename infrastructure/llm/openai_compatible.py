"""Client for any server that speaks the OpenAI chat-completions API."""

import asyncio
import json
import os
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx2
import openai

from infrastructure.llm.base import (
    LLMBusyError,
    LLMCallError,
    LLMConfigError,
    LLMRequest,
    LLMResponse,
    Message,
    ToolCall,
    Usage,
)
from infrastructure.llm.config import LLMConfig

MAX_BACKOFF = 60.0
"""The longest wait, in seconds, before a call is retried."""
TRANSPORT_RETRIES = 2
"""Retries of a call that could not connect, met a server error or got an aborted reply, as
the SDK makes them by default, so that a dropped connection is not taken for a server that went
away."""

T = TypeVar("T")


class OpenAICompatibleClient:
    """Async chat-completions client with at most `max_concurrency` calls in flight.

    A request's JSON schema is enforced as the configuration says, by `structured_retry` for
    a reply asked for again after an invalid one, if it is set.

    A call the server rejects as rate-limited (HTTP 429), or that times out, is retried with
    exponential backoff as the configuration says, waiting outside the concurrency limit;
    when the retries run out, LLMBusyError says that no reply came in time. A call that
    cannot connect, meets a server error or gets a reply that did not finish (finish reason
    `abort`, as vLLM sends when it shuts down mid-request, or none at all, as when a stream is
    closed early) is retried TRANSPORT_RETRIES times, after the same waits, and then raises
    LLMCallError, as does at once any other failure (the credentials or the request refused).
    A reply cut off by the token limit is returned marked `truncated`, and an empty one as
    empty, for the caller to judge, each with the token limit it was given.
    Separated reasoning text (`reasoning_content`, or `reasoning`) is captured when the server
    sends it, and so are cached prompt tokens and reasoning tokens when it reports them.

    `stream` makes the same call as a stream, retried in the same way from its start (a stream
    that breaks off is a call that failed), with usage asked for in the last chunk. Setting its
    `abort` event cancels the call wherever it is, waiting for a retry included, closes the
    connection and returns what had arrived, marked `aborted`.
    """

    def __init__(self, config: LLMConfig, *, http_client: httpx2.AsyncClient | None = None) -> None:
        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise LLMConfigError(f"API key variable {config.api_key_env} is not set")
        self._config = config
        self._client = openai.AsyncOpenAI(
            base_url=config.base_url,
            api_key=api_key,
            timeout=config.timeout,
            max_retries=0,
            http_client=http_client,
        )
        self._slots = asyncio.Semaphore(config.max_concurrency)
        self._jitter = random.Random()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        arguments = self._arguments(request)

        async def call() -> tuple[Any, float]:
            started = time.perf_counter()
            completion = await self._client.chat.completions.create(**arguments)
            _refuse_unfinished(completion.choices[0].finish_reason)
            return completion, time.perf_counter() - started

        completion, latency = await self._retrying(call)
        choice = completion.choices[0]
        message = choice.message
        extra = message.model_extra or {}
        return LLMResponse(
            text=message.content or "",
            truncated=choice.finish_reason == "length",
            max_tokens=arguments.get("max_tokens"),
            reasoning=extra.get("reasoning_content") or extra.get("reasoning"),
            tool_calls=tuple(
                ToolCall.read(call.id, call.function.name, call.function.arguments)
                for call in message.tool_calls or ()
            ),
            finish_reason=choice.finish_reason,
            usage=_usage(completion.usage),
            latency=latency,
        )

    async def stream(
        self, request: LLMRequest, *, abort: asyncio.Event | None = None
    ) -> LLMResponse:
        arguments = {
            **self._arguments(request),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        received = [_Received()]

        async def call() -> None:
            received[0] = _Received()
            stream = await self._client.chat.completions.create(**arguments)
            try:
                async for chunk in stream:
                    received[0].add(chunk)
            finally:
                await stream.close()
            _refuse_unfinished(received[0].finish_reason)

        started = time.perf_counter()
        finished = await _unless_aborted(self._retrying(call), abort)
        return received[0].reply(
            aborted=not finished,
            max_tokens=arguments.get("max_tokens"),
            latency=time.perf_counter() - started,
        )

    def _arguments(self, request: LLMRequest) -> dict[str, Any]:
        """The keyword arguments of the SDK call for `request`."""
        config = self._config
        arguments: dict[str, Any] = {
            "model": request.model or config.model,
            "messages": [_wire(message) for message in request.messages],
            **request.sampling.over(config.sampling).model_dump(exclude_none=True),
        }
        mode = config.structured_output
        if request.after_invalid and config.structured_retry is not None:
            mode = config.structured_retry
        if request.json_schema is not None and mode == "json_schema":
            schema = {"name": "response", "schema": request.json_schema}
            arguments["response_format"] = {"type": "json_schema", "json_schema": schema}
        elif request.json_schema is not None and mode == "json_object":
            arguments["response_format"] = {"type": "json_object"}
        if request.tools:
            arguments["tools"] = list(request.tools)
        if request.tool_choice is not None:
            arguments["tool_choice"] = request.tool_choice
        if request.reasoning_effort is not None:
            arguments["reasoning_effort"] = request.reasoning_effort
        arguments["extra_body"] = {**config.extra_body, **request.extra_body}
        return arguments

    async def _retrying(self, call: Callable[[], Awaitable[T]]) -> T:
        """The result of `call`, made within the concurrency limit and retried as the class
        says."""
        config = self._config
        busy = broken = 0
        while True:
            try:
                async with self._slots:
                    return await call()
            except (openai.RateLimitError, openai.APITimeoutError) as exc:
                if busy == config.max_retries:
                    raise LLMBusyError(
                        f"no reply in time after {busy + 1} call(s); last: {_name(exc)}"
                    ) from exc
                await asyncio.sleep(self._wait(busy))
                busy += 1
            except (openai.APIConnectionError, openai.InternalServerError, _ServerAborted) as exc:
                if broken == TRANSPORT_RETRIES:
                    raise LLMCallError(f"{type(exc).__name__}: {exc}") from exc
                await asyncio.sleep(self._wait(broken))
                broken += 1
            except openai.OpenAIError as exc:
                raise LLMCallError(f"{type(exc).__name__}: {exc}") from exc

    def _wait(self, retry: int) -> float:
        """Seconds before retry `retry` + 1: the backoff doubled `retry` times, at most
        MAX_BACKOFF, between half and all of it at random, so that calls rejected together
        do not return together."""
        return min(self._config.backoff * 2**retry, MAX_BACKOFF) * self._jitter.uniform(0.5, 1)


class _ServerAborted(Exception):
    """A reply the server aborted, or ended without finishing it."""


def _refuse_unfinished(finish_reason: str | None) -> None:
    if finish_reason == "abort":
        raise _ServerAborted("the server aborted the reply")
    if finish_reason is None:
        raise _ServerAborted("the reply ended without a finish reason")


class _Received:
    """What has arrived of a streamed reply: content, reasoning and tool call fragments (by
    index), the finish reason and the usage."""

    def __init__(self) -> None:
        self.text: list[str] = []
        self.reasoning: list[str] = []
        self.calls: dict[int, dict[str, str]] = {}
        self.finish_reason: str | None = None
        self.usage: Any = None

    def add(self, chunk: Any) -> None:
        if chunk.usage is not None:
            self.usage = chunk.usage
        for choice in chunk.choices:
            delta = choice.delta
            if delta.content:
                self.text.append(delta.content)
            extra = delta.model_extra or {}
            if reasoning := extra.get("reasoning_content") or extra.get("reasoning"):
                self.reasoning.append(reasoning)
            for fragment in delta.tool_calls or ():
                call = self.calls.setdefault(fragment.index, {"id": "", "name": "", "args": ""})
                call["id"] = fragment.id or call["id"]
                if fragment.function is not None:
                    call["name"] = fragment.function.name or call["name"]
                    call["args"] += fragment.function.arguments or ""
            if choice.finish_reason is not None:
                self.finish_reason = choice.finish_reason

    def reply(self, *, aborted: bool, max_tokens: int | None, latency: float) -> LLMResponse:
        return LLMResponse(
            text="".join(self.text),
            truncated=self.finish_reason == "length",
            max_tokens=max_tokens,
            reasoning="".join(self.reasoning) or None,
            tool_calls=tuple(
                ToolCall.read(call["id"], call["name"], call["args"])
                for _, call in sorted(self.calls.items())
            ),
            finish_reason=self.finish_reason,
            aborted=aborted,
            usage=_usage(self.usage),
            latency=latency,
        )


async def _unless_aborted(work: Awaitable[Any], abort: asyncio.Event | None) -> bool:
    """Await `work` and return True, or, as soon as `abort` is set, cancel it, let it close
    what it holds and return False. Errors of `work` propagate."""
    if abort is None:
        await work
        return True
    task = asyncio.ensure_future(work)
    waiter = asyncio.ensure_future(abort.wait())
    try:
        await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()
        if not task.done():
            task.cancel()
            await asyncio.wait({task})
    if task.cancelled():
        return False
    task.result()
    return True


def _wire(message: Message) -> dict[str, Any]:
    """`message` as the chat-completions API takes it."""
    wire: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id is not None:
        wire["tool_call_id"] = message.tool_call_id
    return wire


def _usage(usage: Any) -> Usage | None:
    if usage is None:
        return None
    prompt, completion = usage.prompt_tokens_details, usage.completion_tokens_details
    return Usage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cached_prompt_tokens=None if prompt is None else prompt.cached_tokens,
        reasoning_tokens=None if completion is None else completion.reasoning_tokens,
    )


def _name(error: openai.OpenAIError) -> str:
    return "timed out" if isinstance(error, openai.APITimeoutError) else "rate-limited"
