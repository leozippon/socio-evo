"""Stand-ins for the model and the world, for tests and dry runs of the whole pipeline."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import itertools
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Any

from agent.port import Percept, ToolResult, ToolSpec
from agent.runtime import Runtime
from infrastructure.llm import LLMRequest, LLMResponse, ScriptedClient, ToolCall, Usage

Reply = LLMResponse | str | BaseException | Callable[[LLMRequest], LLMResponse | str]
"""A scripted reply: a response, plain text, an exception to raise, or a function of the
request giving a response or text."""

_ids = itertools.count(1)


def tool_call(name: str, **arguments: Any) -> ToolCall:
    """A call of tool `name` with `arguments`, under a fresh id."""
    return ToolCall(id=f"call-{next(_ids)}", name=name, arguments=arguments)


def reply(
    text: str = "",
    *calls: ToolCall,
    reasoning: str | None = None,
    cut_off: bool = False,
    prompt_tokens: int | None = None,
) -> LLMResponse:
    """A model's reply with `text` and tool `calls`; `cut_off` marks it cut off by the token
    limit, and `prompt_tokens`, when given, is the usage the server reports."""
    return LLMResponse(
        text=text,
        reasoning=reasoning,
        tool_calls=calls,
        truncated=cut_off,
        finish_reason="length" if cut_off else "tool_calls" if calls else "stop",
        usage=None
        if prompt_tokens is None
        else Usage(prompt_tokens=prompt_tokens, completion_tokens=len(text) // 4 + 1),
        latency=0.0,
    )


class ScriptedModel(ScriptedClient):
    """A tool-calling model that answers with `replies` in order and keeps every request it
    receives; with no reply left it raises LookupError. Streams take `delay` seconds a word,
    so that something can happen while a reply is in flight."""

    def __init__(self, *replies: Reply, delay: float = 0.0) -> None:
        self.requests: list[LLMRequest] = []
        self._replies = list(replies)
        super().__init__(self._next, delay=delay)

    def _next(self, request: LLMRequest) -> LLMResponse | str:
        self.requests.append(request)
        if not self._replies:
            raise LookupError("the script has no reply left")
        scripted = self._replies.pop(0)
        if isinstance(scripted, BaseException):
            raise scripted
        return scripted(request) if callable(scripted) else scripted


Handler = ToolResult | Callable[[dict[str, Any]], ToolResult | Awaitable[ToolResult]]


class FakePort:
    """A world of one resident that tests drive by hand: it offers `tools` (a list a test may
    change between steps), answers a call with its entry in `results` (a result, or a function
    of the arguments giving one), tells `situation`, and delivers what `deliver` is given. It
    keeps every call made and every busy signal; `waiting` is set while `wait` blocks on an
    empty inbox (and cleared by a delivery), and `clock` is the simulated time it reports."""

    def __init__(
        self,
        *,
        rules: str = "## The town\n\nThe workshop opens at 09:00 and closes at 18:00.",
        situation: str = "It is 08:00 on Monday. You are at home.",
        tools: Sequence[ToolSpec] = (),
        results: Mapping[str, Handler] | None = None,
    ) -> None:
        self.situation_text = situation
        self.clock = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.busy: list[bool] = []
        self.waiting = asyncio.Event()
        self._rules = rules
        self.tools = list(tools)
        self._results = dict(results or {})
        self._inbox: list[Percept] = []
        self._arrived = asyncio.Event()
        self._interrupt = asyncio.Event()
        self._events = itertools.count(1)

    def deliver(self, text: str, *, interrupt: bool = False, kind: str = "speech") -> Percept:
        percept = Percept(text, kind, next(self._events), self.clock, time.time())
        self._inbox.append(percept)
        self._arrived.set()
        self.waiting.clear()
        if interrupt:
            self._interrupt.set()
        return percept

    def rules(self) -> str:
        return self._rules

    def tool_specs(self) -> list[ToolSpec]:
        return list(self.tools)

    def situation(self) -> str:
        return self.situation_text

    def sim_time(self) -> int:
        return self.clock

    def set_busy(self, busy: bool) -> None:
        self.busy.append(busy)

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        self.calls.append((name, args))
        handler = self._results[name]
        if isinstance(handler, ToolResult):
            return handler
        result = handler(args)
        return await result if inspect.isawaitable(result) else result

    def pending(self) -> list[Percept]:
        taken, self._inbox = self._inbox, []
        self._arrived.clear()
        self._interrupt.clear()
        return taken

    async def wait(self) -> list[Percept]:
        while not self._inbox:
            self.waiting.set()
            await self._arrived.wait()
        self.waiting.clear()
        return self.pending()

    @property
    def interrupt(self) -> asyncio.Event:
        return self._interrupt


@contextlib.asynccontextmanager
async def running(runtime: Runtime) -> AsyncIterator[asyncio.Task[None]]:
    """`runtime` living as a task for the duration of the block, then cancelled; an error that
    ended it is raised on leaving."""
    task = asyncio.create_task(runtime.run())
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
