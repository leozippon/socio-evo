"""Client for any server that speaks the OpenAI chat-completions API."""

import asyncio
import os
import time
from typing import Any

import httpx2
import openai

from infrastructure.llm.base import LLMCallError, LLMConfigError, LLMRequest, LLMResponse, Usage
from infrastructure.llm.config import LLMConfig


class OpenAICompatibleClient:
    """Async chat-completions client with at most `max_concurrency` calls in flight.

    The SDK retries transient failures up to `max_retries` times. A remaining failure, or an
    empty reply that was not cut off, raises LLMCallError; a reply cut off by the token limit
    is returned marked `truncated`, for the caller to ask again. Separated reasoning text
    (`reasoning_content`, or `reasoning`) is captured when the server sends it.
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
            max_retries=config.max_retries,
            http_client=http_client,
        )
        self._slots = asyncio.Semaphore(config.max_concurrency)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        arguments: dict[str, Any] = {
            "model": request.model or self._config.model,
            "messages": [message.model_dump() for message in request.messages],
            **request.sampling.over(self._config.sampling).model_dump(exclude_none=True),
        }
        mode = self._config.structured_output
        if request.json_schema is not None and mode == "json_schema":
            schema = {"name": "response", "schema": request.json_schema}
            arguments["response_format"] = {"type": "json_schema", "json_schema": schema}
        elif request.json_schema is not None and mode == "json_object":
            arguments["response_format"] = {"type": "json_object"}
        async with self._slots:
            started = time.perf_counter()
            try:
                completion = await self._client.chat.completions.create(
                    **arguments, extra_body=self._config.extra_body
                )
            except openai.OpenAIError as exc:
                raise LLMCallError(f"{type(exc).__name__}: {exc}") from exc
            latency = time.perf_counter() - started
        choice = completion.choices[0]
        truncated = choice.finish_reason == "length"
        if not choice.message.content and not truncated:
            raise LLMCallError("reply has no content")
        extra = choice.message.model_extra or {}
        usage = completion.usage
        return LLMResponse(
            text=choice.message.content or "",
            truncated=truncated,
            reasoning=extra.get("reasoning_content") or extra.get("reasoning"),
            usage=None
            if usage is None
            else Usage(
                prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens
            ),
            latency=latency,
        )
