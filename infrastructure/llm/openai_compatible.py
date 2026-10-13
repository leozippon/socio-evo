"""Client for any server that speaks the OpenAI chat-completions API."""

import asyncio
import os
import random
import time
from typing import Any

import httpx2
import openai

from infrastructure.llm.base import (
    LLMBusyError,
    LLMCallError,
    LLMConfigError,
    LLMRequest,
    LLMResponse,
    Usage,
)
from infrastructure.llm.config import LLMConfig

MAX_BACKOFF = 60.0
"""The longest wait, in seconds, before a call is retried."""
TRANSPORT_RETRIES = 2
"""Retries of a call that could not connect or met a server error, as the SDK makes them by
default, so that a dropped connection is not taken for a server that went away."""


class OpenAICompatibleClient:
    """Async chat-completions client with at most `max_concurrency` calls in flight.

    A request's JSON schema is enforced as the configuration says, by `structured_retry` for
    a reply asked for again after an invalid one, if it is set.

    A call the server rejects as rate-limited (HTTP 429), or that times out, is retried with
    exponential backoff as the configuration says, waiting outside the concurrency limit;
    when the retries run out, LLMBusyError says that no reply came in time. A call that
    cannot connect or meets a server error is retried TRANSPORT_RETRIES times, after the same
    waits, and then raises LLMCallError, as does at once any other failure (the credentials
    or the request refused). A reply cut off by the token limit is returned marked `truncated`,
    and an empty one as empty, for the caller to judge, each with the token limit it was given.
    Separated reasoning text (`reasoning_content`, or `reasoning`) is captured when the server
    sends it.
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
        arguments: dict[str, Any] = {
            "model": request.model or self._config.model,
            "messages": [message.model_dump() for message in request.messages],
            **request.sampling.over(self._config.sampling).model_dump(exclude_none=True),
        }
        config = self._config
        mode = config.structured_output
        if request.after_invalid and config.structured_retry is not None:
            mode = config.structured_retry
        if request.json_schema is not None and mode == "json_schema":
            schema = {"name": "response", "schema": request.json_schema}
            arguments["response_format"] = {"type": "json_schema", "json_schema": schema}
        elif request.json_schema is not None and mode == "json_object":
            arguments["response_format"] = {"type": "json_object"}
        busy = broken = 0
        while True:
            try:
                async with self._slots:
                    started = time.perf_counter()
                    completion = await self._client.chat.completions.create(
                        **arguments, extra_body=config.extra_body
                    )
                    latency = time.perf_counter() - started
                break
            except (openai.RateLimitError, openai.APITimeoutError) as exc:
                if busy == config.max_retries:
                    raise LLMBusyError(
                        f"no reply in time after {busy + 1} call(s); last: {_name(exc)}"
                    ) from exc
                await asyncio.sleep(self._wait(busy))
                busy += 1
            except (openai.APIConnectionError, openai.InternalServerError) as exc:
                if broken == TRANSPORT_RETRIES:
                    raise LLMCallError(f"{type(exc).__name__}: {exc}") from exc
                await asyncio.sleep(self._wait(broken))
                broken += 1
            except openai.OpenAIError as exc:
                raise LLMCallError(f"{type(exc).__name__}: {exc}") from exc
        choice = completion.choices[0]
        extra = choice.message.model_extra or {}
        usage = completion.usage
        return LLMResponse(
            text=choice.message.content or "",
            truncated=choice.finish_reason == "length",
            max_tokens=arguments.get("max_tokens"),
            reasoning=extra.get("reasoning_content") or extra.get("reasoning"),
            usage=None
            if usage is None
            else Usage(
                prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens
            ),
            latency=latency,
        )

    def _wait(self, retry: int) -> float:
        """Seconds before retry `retry` + 1: the backoff doubled `retry` times, at most
        MAX_BACKOFF, between half and all of it at random, so that calls rejected together
        do not return together."""
        return min(self._config.backoff * 2**retry, MAX_BACKOFF) * self._jitter.uniform(0.5, 1)


def _name(error: openai.OpenAIError) -> str:
    return "timed out" if isinstance(error, openai.APITimeoutError) else "rate-limited"
