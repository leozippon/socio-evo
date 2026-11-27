"""A resident's life cut into moments, from its own trace and session alone.

One moment is one waking turn: what the resident perceived and was told of its situation, then
what it thought, said and did until it rested. The runtime traces each rest with the id of the
session's latest record (`agent.trace`), so the session's messages between two rests, and the
trace's records between them, are one stretch of its life. A stretch in which the resident made
no reply of its own (what it was told as it fell asleep, a request that lapsed) opens the next
moment. A moment belongs to the lived day whose span holds the rest that ends it: since every
resident rests at a checkpoint, the trace as a day's checkpoint committed it (tag `day-NN` of the
agent's repository) ends exactly where that day ends. A moment `acted` when the resident called
in it something that says something to someone or does something in the world: anything but
what the request that offered it named as quiet (its own files, and what only reads or ends the
day, `agent.port.ToolSpec.acts`), a call of something not offered counting as acting.

The moments of a life are numbered from 1 in the order they were lived; a life only grows, so a
number once given always names the same moment. Each has a digest of a line or two to browse by
and a rendering to read it by, both told in the second person, as the town tells the resident its
life, and cut to a length that a night's reading can hold.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from agent.directory import SESSION, TRACE
from agent.runtime import shorten
from agent.session import MessageRecord, read
from infrastructure.git import Repository
from infrastructure.llm import Message, ToolCall
from infrastructure.storage import day_tag
from learning import texts

TOLD_CHARS = 110
"""The most of a moment's first news its digest tells."""
DID_CHARS = 160
"""The most of what the resident did that its digest tells."""
ARGUMENT_CHARS = 40
"""The most of an argument's value a digest tells."""
RESULT_CHARS = 2_000
"""The most of one result a rendering tells, its middle left out."""
MOMENT_CHARS = 12_000
"""The most of one moment a rendering tells, its middle left out."""


@dataclass(frozen=True)
class Moment:
    """Moment `number` of a life, lived on day `day` from simulated time `start` to `end`:
    `messages`, every message it added to the resident's context, in order, and whether the
    resident said or did something in it (`acted`)."""

    number: int
    day: int
    start: int
    end: int
    messages: tuple[Message, ...]
    acted: bool


@dataclass(frozen=True)
class Life:
    """The moments of a life of `days` days, and the names of everything it was ever offered to
    do (the tools its requests declared)."""

    moments: tuple[Moment, ...]
    days: int
    actions: frozenset[str]

    def of(self, day: int) -> tuple[Moment, ...]:
        return tuple(moment for moment in self.moments if moment.day == day)

    def get(self, number: int) -> Moment | None:
        return self.moments[number - 1] if 1 <= number <= len(self.moments) else None


def life(root: Path, day: int) -> Life:
    """The life lived up to the checkpoint of day `day` by the resident whose agent directory is
    `root`, a repository tagged `day-00` to `day-NN`. Raises ValueError when the trace is not as
    those checkpoints committed it."""
    ends = _ends(root, day)
    moments: list[Moment] = []
    actions: set[str] = set()
    session = read(root / SESSION) if (root / SESSION).exists() else ()
    messages = {r.id: r.message for r in session if isinstance(r, MessageRecord)}
    pending: list[int] = []
    start: int | None = None
    since = 0
    quiet: frozenset[str] = frozenset()
    acted = False
    for lived, record in _records(root / TRACE, ends):
        if record["kind"] == "request":
            actions.update(record["tools"])
            quiet = frozenset(record["quiet"])
        if record["kind"] == "tool_call":
            acted = acted or record["name"] not in quiet
        if record["kind"] != "rest":
            start = record["sim_time"] if start is None else start
            continue
        stretch = [i for i in range(since + 1, record["session"] + 1) if i in messages]
        since = record["session"]
        pending += stretch
        if any(messages[i].role == "assistant" for i in stretch):
            if start is None:
                raise ValueError(f"{root / TRACE}: a reply between two rests with nothing traced")
            told = tuple(messages[i] for i in pending)
            end = record["sim_time"]
            moments.append(Moment(len(moments) + 1, lived, start, end, told, acted))
            pending, start, acted = [], None, False
    return Life(tuple(moments), day, frozenset(actions))


def digest(moment: Moment, mark: str = "") -> str:
    """Moment `moment` in a line or two: its hour and the first thing it was told, `mark` after
    them, then what the resident did, or thought if it did nothing."""
    told = next((m.content for m in moment.messages if m.role == "user"), "")
    replies = [m for m in moment.messages if m.role == "assistant"]
    calls = [call for reply in replies for call in reply.tool_calls]
    thought = next((m.content.strip() for m in replies if m.content.strip()), "")
    if calls:
        did = texts.DID.format(actions=_cut("; ".join(_action(call) for call in calls), DID_CHARS))
    elif thought:
        did = texts.THOUGHT.format(text=_cut(_first_line(thought), DID_CHARS))
    else:
        did = texts.NOTHING_DONE
    return texts.LINE.format(
        number=moment.number,
        hour=hour(moment.start),
        told=_cut(_first_line(told), TOLD_CHARS),
        mark=mark,
        did=did,
    )


def rendering(moment: Moment, start_date: date) -> str:
    """Moment `moment` told in full, as the resident lived it: what it was told, its thoughts,
    and each thing it did followed by what that came to."""
    parts: list[str] = []
    calls: dict[str, ToolCall] = {}
    for message in moment.messages:
        text = message.content.strip()
        if message.role == "user":
            parts.append(text)
        elif message.role == "assistant":
            calls = {call.id: call for call in message.tool_calls}
            if text:
                parts.append(texts.THOUGHT.format(text=text))
        else:
            call = calls.get(message.tool_call_id or "")
            parts.append(
                texts.DONE.format(
                    call="" if call is None else _call(call),
                    result=shorten(text, RESULT_CHARS).replace("\n", "\n  "),
                )
            )
    told = texts.MOMENT.format(
        number=moment.number,
        date=told_date(start_date, moment.start),
        start=hour(moment.start),
        end=hour(moment.end),
        body="\n\n".join(part for part in parts if part),
    )
    return shorten(told, MOMENT_CHARS)


def day_date(start_date: date, day: int) -> date:
    """The date of lived day `day`, day 1 being `start_date`."""
    return start_date + timedelta(days=day - 1)


def told_date(start_date: date, t: int) -> str:
    """The date of simulated time `t` as the town tells it: "Monday 2 March"."""
    return tell(start_date + timedelta(days=t // 86_400))


def tell(day: date) -> str:
    return f"{day:%A} {day.day} {day:%B}"


def hour(t: int) -> str:
    return f"{t % 86_400 // 3600:02d}:{t % 3600 // 60:02d}"


def _ends(root: Path, day: int) -> list[int]:
    """The size of the trace, in bytes, as the checkpoint of each day from 0 to `day` committed
    it."""
    names = [f"{day_tag(d)}:{TRACE}" for d in range(day + 1)]
    sizes = Repository(root).sizes(names)
    ends = [sizes[names[0]] or 0]
    for d, name in enumerate(names[1:], start=1):
        size = sizes[name]
        if size is None or size < ends[-1]:
            raise ValueError(f"{root}: no trace committed at {day_tag(d)} after {day_tag(d - 1)}")
        ends.append(size)
    return ends


def _records(path: Path, ends: Sequence[int]) -> Iterator[tuple[int, dict[str, Any]]]:
    """Each record of the trace `path` up to `ends[-1]` bytes, with the day it belongs to: the
    first whose end lies beyond where the record begins."""
    offset, lived = 0, 1
    if ends[-1] > (path.stat().st_size if path.exists() else 0):
        raise ValueError(f"{path}: the trace is shorter than day {len(ends) - 1} left it")
    if ends[-1] > 0:
        with path.open("rb") as file:
            for line in file:
                if offset >= ends[-1]:
                    break
                while offset >= ends[lived]:
                    lived += 1
                offset += len(line)
                yield lived, json.loads(line)
    if offset != ends[-1]:
        raise ValueError(f"{path}: the trace does not end where day {len(ends) - 1} ended")


def _action(call: ToolCall) -> str:
    values = " ".join(_cut(_value(value), ARGUMENT_CHARS) for value in call.arguments.values())
    return f"{call.name} {values}".strip()


def _call(call: ToolCall) -> str:
    arguments = ", ".join(
        f"{key}: {shorten(json.dumps(value, ensure_ascii=False), RESULT_CHARS)}"
        for key, value in call.arguments.items()
    )
    return f"{call.name}({arguments})"


def _value(value: Any) -> str:
    return _first_line(value) if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _cut(text: str, limit: int) -> str:
    """`text`, or as many of its first words as `limit` characters hold, and an ellipsis."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    return (head.rsplit(" ", 1)[0] if " " in head else head).rstrip(" ,;:…") + "…"
