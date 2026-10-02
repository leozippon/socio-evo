"""Deterministic scripted backend for tests and dry runs."""

import json
import time
from collections.abc import Callable
from typing import Any

from infrastructure.llm.base import LLMRequest, LLMResponse

Responder = Callable[[LLMRequest], str | dict[str, Any]]
"""Maps a request to a reply: text as-is, or a dict that is sent as its JSON encoding."""


class ScriptedClient:
    """Answers every request with `responder(request)`. This is not a model: it reasons about
    nothing and reports no token usage. Exceptions raised by the responder propagate."""

    def __init__(self, responder: Responder) -> None:
        self._responder = responder

    async def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        reply = self._responder(request)
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return LLMResponse(text=text, latency=time.perf_counter() - started)
