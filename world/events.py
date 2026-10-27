"""The events a resident lives in, the tools each offers, and the refusal of the others.

A resident is always in exactly one event. Its base event is Idle, Movement, Work or Sleep, or
Dead once its health has run out, from which nothing brings it back; a Conversation sits on top
of the Idle or Work it interrupted, and leaving the conversation returns the resident to that
event as it was. One leaves by doing something else: `go` and
`sleep` leave a conversation and work on their own, and `start_work` a conversation; waiting in
a conversation is listening, and leaves it standing. A Conversation is shared by its members:
the residents at one place (in the isolated mode, the paired residents) who have spoken or been
drawn in by speech. Sleep has two stages: in bed, where the resident may still look around,
review its day, go to bed again to add to its journal entry, rate (where ratings are on) and see
to its files, and suspended, once its
runtime has nothing more to do (or at the forced hour), from which only the wake-up brings it
back.

The tool sets are exactly the architecture's table. Every world tool the town declares is
declared at every step (`rate` and `message` only where the town has ratings or something to
write with); calling one the current event does not offer returns the refusal below, naming the
condition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

IDLE_TOOLS = frozenset(
    {
        "help",
        "look_around",
        "how_am_i",
        "go",
        "start_work",
        "say",
        "message",
        "buy",
        "move_in",
        "sleep",
        "wait",
    }
)
WORK_TOOLS = frozenset(
    {
        "look_around",
        "how_am_i",
        "go",
        "sleep",
        "view_board",
        "claim_task",
        "shell",
        "read_repo_file",
        "write_repo_file",
        "edit_repo_file",
        "submit",
        "abandon_task",
        "say",
        "message",
        "leave_work",
    }
)
CONVERSATION_TOOLS = frozenset(
    {
        "say",
        "message",
        "give_money",
        "share_skill",
        "buy",
        "look_around",
        "how_am_i",
        "go",
        "wait",
        "sleep",
        "start_work",
        "leave_conversation",
    }
)
SLEEP_TOOLS = frozenset({"look_around", "how_am_i", "review_day", "rate", "sleep"})


@dataclass
class Idle:
    kind: ClassVar[str] = "idle"
    tools: ClassVar[frozenset[str]] = IDLE_TOOLS


@dataclass
class Movement:
    destination: str
    arrival: int
    kind: ClassVar[str] = "movement"
    tools: ClassVar[frozenset[str]] = frozenset()


@dataclass
class Work:
    kind: ClassVar[str] = "work"
    tools: ClassVar[frozenset[str]] = WORK_TOOLS


@dataclass
class Sleep:
    wake: int
    suspended: bool = False
    kind: ClassVar[str] = "sleep"
    tools: ClassVar[frozenset[str]] = SLEEP_TOOLS


@dataclass
class Dead:
    kind: ClassVar[str] = "dead"
    tools: ClassVar[frozenset[str]] = frozenset()


@dataclass(eq=False)
class Conversation:
    """`budget` is the messages each member has left, in a paired exchange only; `pair` names
    that exchange's two residents; `silence` is the world's timer that ends it."""

    room: str
    place: str
    members: set[str]
    last_speech: int
    budget: dict[str, int] | None = None
    pair: tuple[str, str] | None = None
    silence: Any = None
    kind: ClassVar[str] = "conversation"
    tools: ClassVar[frozenset[str]] = CONVERSATION_TOOLS


Base = Idle | Movement | Work | Sleep | Dead
Event = Base | Conversation
ENDED = "Your life has ended."
"""What a dead resident reads, should its runtime still ask anything."""


def refusal(
    event: Event, tool: str, *, workplace: str, destination: str, ratings: bool = True
) -> str:
    """Why `tool`, which `event` does not offer, cannot be used now. `workplace` and
    `destination` are the names of the workplace and of where a moving resident is going;
    `ratings` whether the town has bedtime ratings."""
    if isinstance(event, Dead):
        return ENDED
    if isinstance(event, Movement):
        return f"You are on your way to {destination}; you can do nothing until you arrive."
    if isinstance(event, Sleep):
        if event.suspended:
            return "You are asleep."
        rate = ", rate people" if ratings else ""
        return (
            "You have gone to bed; before you fall asleep you can only look around, take stock "
            f"of how you feel, look back over your day, add to your journal{rate} and see to your "
            "own files."
        )
    if isinstance(event, Conversation):
        return "You are in a conversation; leave it first."
    if isinstance(event, Work):
        return (
            "You are already at work."
            if tool == "start_work"
            else ("You are at work; leave work first.")
        )
    if tool in WORK_TOOLS:
        return f"You are not at work; start work at {workplace} first."
    if tool in CONVERSATION_TOOLS:
        return "You are not in a conversation."
    return "You can do that only once you have gone to bed."
