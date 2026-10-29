"""The contract between the agent runtime and the world.

The world implements `WorldPort` once per resident. The runtime declares, in each request, the
tool specs the port offers at that moment, opens a step with the port's situation and the
percepts pending, forwards every tool call the model makes that is not one of its own file
tools and that names one of the world's tools, declared or not (the world refuses, naming the
condition, what cannot be done by the time it is carried out), and blocks on `wait` when the
resident has nothing more to do; it takes no step while the resident is asleep. The port owns the
resident's inbox: the world delivers percepts into it, and sets `interrupt` when a delivered
percept must reach the resident at once, which makes the runtime leave a reply's calls undone
and tell the percept. Which percepts interrupt is the world's to decide; one that does not
waits in the inbox, and the runtime takes it before it carries out its next call and tells it
ahead of that call's result, or takes it with `wait`. A work-only port for evaluation
implements the same protocol with a single Work event and no town.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    """A tool as declared to the model: its name, what it does, and the JSON schema of its
    arguments (an object schema)."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """What a tool call came to: the text the resident reads, and whether the call ends the
    resident's turn (going somewhere, going to sleep, waiting), after which the runtime yields
    until the world has something to tell."""

    text: str
    ends_turn: bool = False


@dataclass(frozen=True)
class Percept:
    """Something the world tells one resident, in the resident's words: the text, the kind of
    world event it comes from, that event's sequence number in the world log, and both times."""

    text: str
    kind: str
    event_id: int
    sim_time: int
    real_time: float


class WorldPort(Protocol):
    """The world as one resident reaches it."""

    def rules(self) -> str:
        """The standing rules of the town, told to this resident, as they stand: part of the
        system prompt, they change only when someone moves house."""
        ...

    def tool_specs(self) -> list[ToolSpec]:
        """The world tools the resident can use at this moment, in a fixed order: what the
        next request declares."""
        ...

    def situation(self) -> str:
        """The moment as this resident sees it: time, place, people, what it is doing, its
        purse and its task."""
        ...

    def sim_time(self) -> int:
        """Simulated seconds since 00:00 of day 1."""
        ...

    def set_busy(self, busy: bool) -> None:
        """Tell the world whether this resident is in a model request or a tool execution; the
        clock runs at its active speed while any resident is busy."""
        ...

    def knows(self, name: str) -> bool:
        """Whether `name` is one of the world's tools for this resident, whether or not it can
        use it at this moment."""
        ...

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Carry out a world tool. A tool that does not apply now returns a refusal naming the
        condition; an unknown name raises `KeyError`."""
        ...

    def pending(self) -> list[Percept]:
        """Return and clear the percepts delivered since the last take, and clear `interrupt`."""
        ...

    async def wait(self) -> list[Percept]:
        """Block until at least one percept is pending, then return and clear them as `pending`
        does. While the resident is awake, the world guarantees a percept within its idle
        interval of simulated time; a sleeping resident hears nothing until it wakes."""
        ...

    @property
    def interrupt(self) -> asyncio.Event:
        """Set while an interrupting percept is pending; cleared by `pending` and `wait`."""
        ...

    @property
    def asleep(self) -> bool:
        """Whether the resident is asleep: what it is told is kept, and it takes no step until it
        wakes."""
        ...
