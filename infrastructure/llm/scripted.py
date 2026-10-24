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

    `stream` delivers the reply's reasoning and then its text word by word, `delay` seconds
    apart, and its tool calls at the end; if `abort` is set before the end, it returns what
    has been delivered, marked aborted and without tool calls, usage or finish reason."""

    def __init__(self, responder: Responder, *, delay: float = 0.0) -> None:
        self._responder = responder
        self._delay = delay

    async def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        return self._reply(request).model_copy(update={"latency": time.perf_counter() - started})

    async def stream(
        self, request: LLMRequest, *, abort: asyncio.Event | None = None
    ) -> LLMResponse:
        started = time.perf_counter()
        reply = self._reply(request)
        pieces = [("reasoning", p) for p in _PIECE.findall(reply.reasoning or "")]
        pieces += [("text", p) for p in _PIECE.findall(reply.text)]
        delivered = {"reasoning": "", "text": ""}
        for kind, piece in [*pieces, ("end", "")]:
            if await _aborted(abort, self._delay):
                return LLMResponse(
                    text=delivered["text"],
                    reasoning=delivered["reasoning"] or None,
                    max_tokens=reply.max_tokens,
                    aborted=True,
                    latency=time.perf_counter() - started,
                )
            if kind != "end":
                delivered[kind] += piece
        return reply.model_copy(update={"latency": time.perf_counter() - started})

    def _reply(self, request: LLMRequest) -> LLMResponse:
        reply = self._responder(request)
        if isinstance(reply, LLMResponse):
            return reply
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return LLMResponse(text=text, latency=0.0)


async def _aborted(abort: asyncio.Event | None, delay: float) -> bool:
    """Wait `delay` seconds, or less if `abort` is set meanwhile; whether it is set."""
    if abort is None:
        await asyncio.sleep(delay)
        return False
    if abort.is_set():
        return True
    try:
        await asyncio.wait_for(abort.wait(), delay)
    except TimeoutError:
        return False
    return True
