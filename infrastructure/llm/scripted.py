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
    nothing and reports no token usage. Exceptions raised by the responder propagate.

    `enforces_schema` says which structured-output mode it stands in for: by default guided
    decoding, as in every experiment."""

    def __init__(self, responder: Responder, *, enforces_schema: bool = True) -> None:
        self._responder = responder
        self.enforces_schema = enforces_schema

    async def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        reply = self._responder(request)
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return LLMResponse(text=text, latency=time.perf_counter() - started)
