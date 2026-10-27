"""The events a resident lives in, the tools each offers, and the refusal of the others.

A resident is always in exactly one event. Its base event is Idle, Movement, Work or Sleep, or
Dead once its health has run out, from which nothing brings it back; a Conversation sits on top
of the Idle or Work it found the resident in and adds its own actions to that event's, so that
someone spoken to at work can go on working, and leaving the conversation leaves the event
underneath as it is. Work is entered by claiming a task or acting in its workspace, wherever the
resident is, except by one exhausted, and ends when the body is found exhausted (`EXHAUSTED`).
One leaves by doing something else: `go` and `sleep` leave a conversation and work on their
own; waiting in a conversation is listening, and leaves it standing. A
Conversation is shared by its members:
the residents at one place (in the isolated mode, the paired residents) who have spoken or been
drawn in by speech. Sleep has two stages: in bed, where the resident may still look around,
review its day, go to bed again to add to its journal entry, rate (where ratings are on) and see
to its files, and suspended, once its
runtime has nothing more to do (or at the forced hour), from which only the wake-up brings it
back.

The tool sets are exactly the architecture's table; a conversation's are those it adds. Every
world tool the town declares is declared at every step (`rate` and `message` only where the town
has ratings or something to write with); calling one the resident cannot use now returns the
refusal below, naming the condition.
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
        "buy",
        "give",
        "move_in",
        "sleep",
        "wait",
    }
)
WORK_TOOLS = frozenset(
    {
        "help",
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
        "buy",
        "give",
        "wait",
        "leave_work",
    }
)
CONVERSATION_TOOLS = frozenset({"share_file", "leave_conversation"})
TASK_TOOLS = frozenset(
    {"shell", "read_repo_file", "write_repo_file", "edit_repo_file", "submit", "abandon_task"}
)
"""What acts on the task one holds, of use only to one who holds a task."""
SLEEP_TOOLS = frozenset({"help", "look_around", "how_am_i", "review_day", "rate", "sleep"})


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
    """`longest`: the body wakes the resident at `wake`, before the hour it gave, since one sleep
    lasts no longer."""

    wake: int
    suspended: bool = False
    longest: bool = False
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
ENDED = "Your life has ended."
"""What a dead resident reads, should its runtime still ask anything."""
EXHAUSTED = "You are exhausted and cannot work until you have slept."
"""Why one in the lowest band of energy cannot claim a task or act in its workspace, and what
it is told when its work stops for it."""
UNTIL_JOINED = "you can work on it once someone else claims it with you"
"""When one who holds a task for two alone can work on it: told on claiming it first, on being
left with it and whenever it reaches for its workspace meanwhile."""


def refusal(event: Base, tool: str, *, destination: str, ratings: bool = True) -> str:
    """Why `tool`, which neither the base `event` nor a conversation on top of it offers,
    cannot be used now. `destination` is the name of where a moving resident is going;
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
            f"of how you feel, look back over your day, add to your journal{rate}, read how the "
            "town works and see to your own files."
        )
    if tool in CONVERSATION_TOOLS:
        return "You are not in a conversation."
    if tool in SLEEP_TOOLS:
        return "You can do that only once you have gone to bed."
    if isinstance(event, Work):
        return "You are at work; leave work first."
    return "You are not at work."
