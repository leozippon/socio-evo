"""Deterministic scripted backend for tests and dry runs."""

import asyncio
import json
import re
import time
from collections.abc import Callable
from typing import Any

from infrastructure.llm.base import LLMRequest, LLMResponse

Responder = Callable[[LLMRequest], str | dict[str, Any] | LLMResponse]
"""Maps a request to a reply: text as-is, a dict that is sent as its JSON encoding, or a whole
response (with tool calls, a finish reason, usage, ...) returned as it is."""

_PIECE = re.compile(r"\S+\s*|\s+")


class ScriptedClient:
    """Answers every request with `responder(request)`. This is not a model: it reasons about
    nothing and reports no token usage or limit unless the responder returns a response that
    does. Exceptions raised by the responder propagate.

    `stream` takes `delay` seconds for each word of the reply's reasoning and text, as a
    stream would, and returns the reply whole."""

    def __init__(self, responder: Responder, *, delay: float = 0.0) -> None:
        self._responder = responder
        self._delay = delay

    async def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        return self._reply(request).model_copy(update={"latency": time.perf_counter() - started})

    async def stream(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        reply = self._reply(request)
        words = len(_PIECE.findall(reply.reasoning or "")) + len(_PIECE.findall(reply.text))
        for _ in range(words + 1):
            await asyncio.sleep(self._delay)
        return reply.model_copy(update={"latency": time.perf_counter() - started})

    def _reply(self, request: LLMRequest) -> LLMResponse:
        reply = self._responder(request)
        if isinstance(reply, LLMResponse):
            return reply
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return LLMResponse(text=text, latency=0.0)
