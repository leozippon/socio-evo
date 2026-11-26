"""The choice: in bed at night, a resident goes back over its life and keeps the moments it wants
to carry into tomorrow.

The choice is a bounded session of its own on the resident's current adapter. Its account of
itself heads it as it heads the resident's day (`agent.texts.ABOUT_ME`, background.md), then the
night's words (`texts.TONIGHT`), and it opens on the resident's number night by night and the days
it has lived. The resident may go over any day and read any moment, keep up to `keep` of them, or
none, with its reason if it gives one, and put back what it kept tonight; a moment it kept on an
earlier night it carries already. The session ends when a reply does nothing (`done`), after
`steps` replies (`steps`), when a reply is cut off by its token limit again after being asked once
more at a lower effort as the runtime asks (`cut off`), or when the context outgrows the model's
window (`window`). A model error is asked again as the runtime asks (`model_attempts`, waiting
`retry_wait` and twice as long each time); one that outlasts the attempts raises.

Its trace records every message as it enters the session, every request and every reply in full.

In the Random arm the session runs as in any other and its count is used: what is learnt from is as
many moments as the resident kept, drawn uniformly at random (`draw`), by a seed of the run, the
resident and the night, from the moments of its life not drawn on an earlier night.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Collection, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from agent import texts as runtime_texts
from agent.runtime import Effort, RuntimeConfig, again, shorten
from infrastructure.config import StrictModel
from infrastructure.llm import (
    LLMContextOverflowError,
    LLMError,
    LLMRequest,
    LLMResponse,
    Message,
    Sampling,
    StreamingClient,
    ToolCall,
)
from infrastructure.storage import append_jsonl
from learning import texts
from learning.moments import Life, Moment, day_date, digest, rendering, tell

Ended = Literal["done", "steps", "cut off", "window"]

NAMES = frozenset(spec.name for spec in texts.SPECS)
TOOLS = tuple(
    {
        "type": "function",
        "function": {"name": s.name, "description": s.description, "parameters": s.parameters},
    }
    for s in texts.SPECS
)


class Kept(StrictModel):
    """A moment kept, with the day it was lived and the reason given, if one was."""

    moment: int = Field(ge=1)
    day: int = Field(ge=1)
    why: str | None = None


class Choice(StrictModel):
    """A night's choice: how the session `ended` after how many `replies`, what the resident
    `marked` to keep, and what is `kept` to learn from: what it marked, or in the Random arm as
    many drawn by the seed `drawn`."""

    ended: Ended
    replies: int
    marked: tuple[Kept, ...]
    kept: tuple[Kept, ...]
    drawn: str | None = None


async def choose(
    life: Life,
    *,
    background: str,
    numbers: Sequence[tuple[int, int]],
    earlier: Collection[int],
    start_date: date,
    keep: int,
    steps: int,
    client: StreamingClient,
    model: str | None,
    replica: int | None,
    runtime: RuntimeConfig,
    trace: Path,
) -> tuple[tuple[Kept, ...], Ended, int]:
    """The resident's choice over `life`: what it marked, how the session ended and after how many
    replies. `numbers` is its number on each night so far, `earlier` the moments it kept on
    earlier nights; the session runs on `model` and is traced to `trace`, begun afresh."""
    trace.unlink(missing_ok=True)
    session = _Session(life, start_date, keep, frozenset(earlier))
    system = (
        f"{runtime_texts.ABOUT_ME}\n\n{background.strip()}\n\n{texts.TONIGHT.format(keep=keep)}\n"
    )
    messages: list[Message] = []

    def add(message: Message) -> None:
        messages.append(message)
        _record(trace, "message", **message.model_dump(mode="json"))

    add(Message(role="system", content=system))
    add(Message(role="user", content=opening(life, numbers, start_date)))
    asking = _Asking(client, model, replica, runtime, trace)
    ended: Ended = "steps"
    replies = 0
    while replies < steps:
        try:
            reply = await asking.reply(messages)
        except LLMContextOverflowError:
            ended = "window"
            break
        replies += 1
        if reply.truncated:
            ended = "cut off"
            break
        add(Message(role="assistant", content=reply.text, tool_calls=reply.tool_calls))
        if not reply.tool_calls:
            ended = "done"
            break
        for call in reply.tool_calls:
            answer = shorten(session.answer(call), runtime.tool_result_chars)
            add(Message(role="tool", content=answer, tool_call_id=call.id))
    marked = tuple(session.marked.values())
    _record(trace, "end", ended=ended, replies=replies, marked=[k.moment for k in marked])
    return marked, ended, replies


def draw(life: Life, count: int, before: Collection[int], seed: str) -> tuple[Kept, ...]:
    """`count` moments of `life` drawn uniformly at random by `seed` from those not in `before`
    (all of them, when fewer are left), in the order they were lived."""
    pool = [moment for moment in life.moments if moment.number not in before]
    drawn = random.Random(seed).sample(pool, min(count, len(pool)))
    return tuple(Kept(moment=m.number, day=m.day) for m in sorted(drawn, key=lambda m: m.number))


def opening(life: Life, numbers: Sequence[tuple[int, int]], start_date: date) -> str:
    """What opens the choice: the resident's number night by night, and the days it has lived
    here with their moments."""
    counts = "\n".join(
        texts.NUMBER.format(date=tell(day_date(start_date, night)), count=count)
        for night, count in numbers
    )
    days = []
    for lived in range(1, life.days + 1):
        moments = life.of(lived)
        when = day_date(start_date, lived)
        line = (
            texts.DAY.format(
                day=when.isoformat(),
                date=tell(when),
                first=moments[0].number,
                last=moments[-1].number,
            )
            if moments
            else texts.DAY_WITHOUT.format(day=when.isoformat(), date=tell(when))
        )
        days.append(line)
    return texts.OPENING.format(
        numbers=texts.NUMBERS.format(lines=counts), days=texts.DAYS.format(lines="\n".join(days))
    )


class _Session:
    """What the resident's calls in the choice come to, and what it keeps."""

    def __init__(self, life: Life, start_date: date, keep: int, earlier: frozenset[int]) -> None:
        self._life, self._start, self._most, self._earlier = life, start_date, keep, earlier
        self.marked: dict[int, Kept] = {}

    def answer(self, call: ToolCall) -> str:
        if call.unreadable is not None:
            return runtime_texts.UNREADABLE
        if call.name not in NAMES:
            return runtime_texts.UNKNOWN_TOOL.format(name=call.name)
        try:
            return getattr(self, f"_{call.name}")(call.arguments)
        except _Refusal as refusal:
            return str(refusal)

    def _look_back(self, args: dict[str, Any]) -> str:
        written = args.get("day")
        try:
            when = date.fromisoformat(written) if isinstance(written, str) else None
        except ValueError:
            when = None
        if when is None:
            raise _Refusal(_needs("look_back", "day", texts.A_DAY))
        lived = (when - self._start).days + 1
        if not 1 <= lived <= self._life.days:
            raise _Refusal(
                texts.NO_DAY.format(
                    day=written,
                    first=day_date(self._start, 1).isoformat(),
                    last=day_date(self._start, self._life.days).isoformat(),
                )
            )
        moments = self._life.of(lived)
        if not moments:
            return texts.NO_MOMENTS.format(date=tell(when))
        lines = "\n".join(digest(moment, self._mark(moment.number)) for moment in moments)
        return texts.THE_DAY.format(date=tell(when), moments=lines)

    def _read_moment(self, args: dict[str, Any]) -> str:
        return rendering(self._moment(args, "read_moment"), self._start)

    def _keep(self, args: dict[str, Any]) -> str:
        moment = self._moment(args, "keep")
        number, why = moment.number, args.get("why")
        if why is not None and not isinstance(why, str):
            raise _Refusal(_needs("keep", "why", runtime_texts.TEXT))
        if number in self._earlier:
            return texts.CARRIED.format(number=number)
        if number in self.marked:
            return texts.KEEPING.format(number=number)
        if len(self.marked) >= self._most:
            return texts.FULL.format(limit=self._most)
        self.marked[number] = Kept(moment=number, day=moment.day, why=(why or "").strip() or None)
        return texts.KEPT.format(number=number, count=len(self.marked), limit=self._most)

    def _let_go(self, args: dict[str, Any]) -> str:
        number = self._moment(args, "let_go").number
        if self.marked.pop(number, None) is None:
            return texts.NOT_KEPT.format(number=number)
        return texts.LET_GO.format(number=number, count=len(self.marked))

    def _moment(self, args: dict[str, Any], tool: str) -> Moment:
        """The moment `args` name, by a whole number written as one or in digits."""
        value = args.get("moment")
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise _Refusal(_needs(tool, "moment", runtime_texts.NUMBER))
        moment = self._life.get(value)
        if moment is None:
            raise _Refusal(texts.NO_MOMENT.format(number=value, last=len(self._life.moments)))
        return moment

    def _mark(self, number: int) -> str:
        if number in self._earlier:
            return texts.KEPT_EARLIER
        return texts.KEPT_TONIGHT if number in self.marked else ""


class _Refusal(Exception):
    """A call that cannot be carried out; its message is what the resident reads."""


def _needs(name: str, argument: str, kind: str) -> str:
    return runtime_texts.NEEDS.format(name=name, argument=argument, kind=kind)


class _Asking:
    """The replies of one choice: each asked at the runtime's effort and token limit, once more
    at a lower effort when cut off, and again after a model error as the runtime asks."""

    def __init__(
        self,
        client: StreamingClient,
        model: str | None,
        replica: int | None,
        runtime: RuntimeConfig,
        trace: Path,
    ) -> None:
        self._client, self._model, self._replica = client, model, replica
        self._runtime, self._trace = runtime, trace

    async def reply(self, messages: Sequence[Message]) -> LLMResponse:
        effort: Effort = self._runtime.reasoning_effort
        limit = self._runtime.reply_max_tokens
        reply = await self._ask(messages, effort, limit)
        if reply.truncated:
            effort, limit = again(effort, limit)
            reply = await self._ask(messages, effort, limit)
        return reply

    async def _ask(self, messages: Sequence[Message], effort: Effort, limit: int) -> LLMResponse:
        request = LLMRequest(
            messages=tuple(messages),
            model=self._model,
            tools=TOOLS,
            reasoning_effort=effort,
            sampling=Sampling(max_tokens=limit),
            replica=self._replica,
        )
        tried = 0
        while True:
            tried += 1
            _record(
                self._trace,
                "request",
                messages=len(messages),
                model=self._model,
                reasoning_effort=effort,
                max_tokens=limit,
                attempt=tried,
            )
            try:
                reply = await self._client.stream(request)
            except LLMContextOverflowError as error:
                _record(self._trace, "overflow", error=f"{type(error).__name__}: {error}")
                raise
            except LLMError as error:
                _record(self._trace, "error", error=f"{type(error).__name__}: {error}")
                if tried == self._runtime.model_attempts:
                    raise
                await asyncio.sleep(self._runtime.retry_wait * 2 ** (tried - 1))
                continue
            _record(self._trace, "reply", **reply.model_dump(mode="json"))
            return reply


def _record(path: Path, kind: str, **fields: Any) -> None:
    append_jsonl(path, {"kind": kind, "real_time": time.time(), **fields})
