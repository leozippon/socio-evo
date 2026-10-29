"""The events a resident lives in, the tools each offers, and the refusal of the others.

A resident is always in exactly one event. Its base event is Idle, Movement, Work, Sleep or
Bedridden; a Conversation covers the Idle, Work or Bedridden it found the resident in while it
lasts, and when it ends, by leaving, by everyone else leaving or by the silence rule, the base
event is back as it was: one spoken to at work is at work again without sitting down anew, and
its stretch of work runs on through the talk. In a conversation one can do what the conversation
offers of its own (`CONVERSATION_TOOLS`: talking, and what one does with things while talking)
and what the base event offers besides: doing any of the latter, one's work for one, leaves the
conversation first, so that one does one thing at a time. Work is entered at one's own workplace
by `start_work` or by doing the work of one's occupation there, except by one exhausted, and ends
when the body is found exhausted (`EXHAUSTED`); the doctor also examines and treats at the
bedside of one too ill to get up, without sitting down to work there. `go` leaves a conversation
on its own; waiting in a conversation is listening, and leaves it standing.
A Conversation is shared by its members: the residents at one place who have spoken or been
drawn in by speech. Sleep has two stages: in bed, where the resident may still look around,
review its day, go to bed again to add to its journal entry and see to its files, and suspended,
once its runtime has nothing more to do (or at the forced hour), from which only the wake-up
brings it back. Bedridden is where health at its floor puts a resident, at its home, until it is
treated: it can only ask, look around, take stock of itself and of what it has, speak to whoever
comes and sleep.

Each event's tools are the architecture's table. What everyone can do is in them all; each
occupation adds its own work (`world.occupations`), done at its workplace. The resident's request
declares the tools of its event at its place now that are its own, less the ones of no use there
(`World.usable`); a call of a world tool that the event does not offer by the time it is carried
out, declared or not, returns the refusal below, naming the condition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from world.occupations import WORK_DONE

EVERYDAY = frozenset(
    {
        "help",
        "look_around",
        "how_am_i",
        "inventory",
        "go",
        "wait",
        "say",
        "message",
        "get",
        "pass",
        "put",
        "eat",
        "buy",
    }
)
"""What one up and about can do, at rest or at work, besides the work of the occupations."""
IDLE_TOOLS = EVERYDAY | WORK_DONE | {"start_work", "move_in", "sleep"}
WORK_TOOLS = EVERYDAY | WORK_DONE | {"leave_work"}
CONVERSATION_TOOLS = frozenset(
    {
        "help",
        "look_around",
        "how_am_i",
        "inventory",
        "go",
        "wait",
        "say",
        "get",
        "pass",
        "put",
        "eat",
        "buy",
        "leave_conversation",
    }
)
"""What a conversation offers of its own, done without leaving it: talking, and what one does
with things while talking. What else the event underneath offers is offered too, and leaves the
conversation first."""
TALK = frozenset({"say", "wait", "leave_conversation"})
"""What a conversation adds to whatever event it covers."""
SLEEP_TOOLS = frozenset({"help", "look_around", "how_am_i", "review_day", "sleep"})
BEDRIDDEN_TOOLS = frozenset({"help", "look_around", "how_am_i", "inventory", "say", "sleep"})


@dataclass
class Idle:
    kind: ClassVar[str] = "idle"
    tools: ClassVar[frozenset[str]] = IDLE_TOOLS


@dataclass
class Movement:
    """`working`: the resident is on its way at work, its duty running wherever it goes (the
    mayor's, `Occupation.duty`), and is at work again on arrival."""

    destination: str
    arrival: int
    working: bool = False
    kind: ClassVar[str] = "movement"
    tools: ClassVar[frozenset[str]] = frozenset()


@dataclass
class Work:
    kind: ClassVar[str] = "work"
    tools: ClassVar[frozenset[str]] = WORK_TOOLS


@dataclass
class Sleep:
    """`longest`: the body wakes the resident at `wake`, before the hour it gave, since one sleep
    lasts no longer."""

    wake: int
    suspended: bool = False
    longest: bool = False
    kind: ClassVar[str] = "sleep"
    tools: ClassVar[frozenset[str]] = SLEEP_TOOLS


@dataclass
class Bedridden:
    kind: ClassVar[str] = "bedridden"
    tools: ClassVar[frozenset[str]] = BEDRIDDEN_TOOLS


@dataclass(eq=False)
class Conversation:
    """The conversation held at `place`; `silence` is the world's timer that ends it."""

    place: str
    members: set[str]
    last_speech: int
    silence: Any = None
    kind: ClassVar[str] = "conversation"
    tools: ClassVar[frozenset[str]] = CONVERSATION_TOOLS


Base = Idle | Movement | Work | Sleep | Bedridden
EXHAUSTED = "You are exhausted and cannot work until you have slept."
"""Why one in the lowest band of energy cannot claim a task or act in its workspace, and what
it is told when its work stops for it."""
IN_BED = (
    "You have gone to bed; before you fall asleep you can only look around, take stock of how "
    "you feel, look back over your day, add to your journal, read how the town works and see to "
    "your own files."
)
BEDRIDDEN = (
    "You are in bed, too ill to get up; you can only look around, take stock of how you feel "
    "and of what you have, speak to whoever comes, read how the town works and sleep."
)
AT_HOME = "You can sleep only at home."
"""Why `sleep` is refused away from home, as at work, which is never at home."""


def refusal(event: Base, tool: str, *, destination: str) -> str:
    """Why `tool`, which the base `event` does not offer (nor a conversation over it), cannot be
    used now. `destination` is the name of where a moving resident is going."""
    if isinstance(event, Movement):
        return f"You are on your way to {destination}; you can do nothing until you arrive."
    if isinstance(event, Sleep):
        return "You are asleep." if event.suspended else IN_BED
    if isinstance(event, Bedridden):
        return BEDRIDDEN
    if tool == "leave_conversation":
        return "You are not in a conversation."
    if tool == "sleep":
        return AT_HOME
    if tool in SLEEP_TOOLS:
        return "You can do that only once you have gone to bed."
    if isinstance(event, Work):
        return (
            "You are at work already."
            if tool == "start_work"
            else ("You are at work; leave work first.")
        )
    return "You are not at work."
