"""The events a resident lives in, the tools each offers, and the refusal of the others.

A resident is always in exactly one event. Its base event is Idle, Movement, Work, Sleep or
Bedridden; a Conversation takes the place of the Idle, Work or Bedridden it found the resident
in while it lasts, offering its own actions and not the base event's, and when it ends, by
leaving, by everyone else leaving or by the silence rule, the base event is back as it was: one
spoken to at work is at work again without sitting down anew, and its stretch of work runs on
through the talk. Work is entered at one's own workplace by `start_work` or by doing the work of
one's occupation there, except by one exhausted, and ends when the body is found exhausted
(`EXHAUSTED`); the doctor also examines and treats at the bedside of one too ill to get up,
without sitting down to work there. `go`
leaves a conversation on its own; waiting in a conversation is listening, and leaves it standing.
A Conversation is shared by its members: the residents at one place who have spoken or been
drawn in by speech. Sleep has two stages: in bed, where the resident may still look around,
review its day, go to bed again to add to its journal entry and see to its files, and suspended,
once its runtime has nothing more to do (or at the forced hour), from which only the wake-up
brings it back. Bedridden is where health at its floor puts a resident, at its home, until it is
treated: it can only ask, look around, take stock of itself and of what it has, speak to whoever
comes and sleep.

Each event's tools are the architecture's table. What everyone can do is in them all; each
occupation adds its own work (`OCCUPATION_TOOLS`), done at its workplace. The resident's request
declares the tools of its event at its place now that are its own, less the ones of no use there
(`World.usable`); a call that names one the event does not offer by the time it is carried out
returns the refusal below, naming the condition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

IDLE_TOOLS = frozenset(
    {
        "help",
        "look_around",
        "how_am_i",
        "inventory",
        "go",
        "start_work",
        "view_board",
        "read_task",
        "claim_task",
        "shell",
        "read_repo_file",
        "write_repo_file",
        "edit_repo_file",
        "submit",
        "abandon_task",
        "assign",
        "cook",
        "order",
        "set_price",
        "examine",
        "treat",
        "report",
        "announce",
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
        "inventory",
        "go",
        "sleep",
        "view_board",
        "read_task",
        "claim_task",
        "shell",
        "read_repo_file",
        "write_repo_file",
        "edit_repo_file",
        "submit",
        "abandon_task",
        "assign",
        "cook",
        "order",
        "set_price",
        "examine",
        "treat",
        "report",
        "announce",
        "say",
        "message",
        "buy",
        "give",
        "wait",
        "leave_work",
    }
)
CONVERSATION_TOOLS = frozenset(
    {
        "help",
        "look_around",
        "how_am_i",
        "inventory",
        "go",
        "wait",
        "say",
        "give",
        "leave_conversation",
    }
)
BOARD_TOOLS = frozenset({"view_board", "read_task", "claim_task"})
"""What reads and claims from the board, which hangs at the office."""
TASK_TOOLS = frozenset(
    {"shell", "read_repo_file", "write_repo_file", "edit_repo_file", "submit", "abandon_task"}
)
"""What acts on the task one holds, of use only to one who holds a task, at the office."""
OCCUPATION_TOOLS: dict[str, frozenset[str]] = {
    "programmer": BOARD_TOOLS | TASK_TOOLS,
    "team-leader": BOARD_TOOLS | TASK_TOOLS | {"assign"},
    "chef": frozenset({"cook", "set_price"}),
    "shopkeeper": frozenset({"order", "set_price"}),
    "doctor": frozenset({"examine", "treat", "set_price"}),
    "mayor": frozenset({"report", "announce"}),
}
"""What each occupation adds to what everyone can do: its work, done at its workplace."""
BEDSIDE = frozenset({"examine", "treat"})
"""The doctor's work that is also done at the home of one too ill to get up."""
WORK_DONE = frozenset().union(*OCCUPATION_TOOLS.values())
"""Everything that is some occupation's work."""
SLEEP_TOOLS = frozenset({"help", "look_around", "how_am_i", "review_day", "sleep"})
BEDRIDDEN_TOOLS = frozenset({"help", "look_around", "how_am_i", "inventory", "say", "sleep"})


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
class Bedridden:
    kind: ClassVar[str] = "bedridden"
    tools: ClassVar[frozenset[str]] = BEDRIDDEN_TOOLS


@dataclass(eq=False)
class Conversation:
    """`silence` is the world's timer that ends it."""

    room: str
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


def refusal(event: Base | Conversation, tool: str, *, destination: str) -> str:
    """Why `tool`, which `event` does not offer, cannot be used now. `destination` is the name
    of where a moving resident is going."""
    if isinstance(event, Movement):
        return f"You are on your way to {destination}; you can do nothing until you arrive."
    if isinstance(event, Sleep):
        return "You are asleep." if event.suspended else IN_BED
    if isinstance(event, Bedridden):
        return BEDRIDDEN
    if isinstance(event, Conversation):
        return "You are in a conversation; leave it first."
    if tool == "leave_conversation":
        return "You are not in a conversation."
    if tool in SLEEP_TOOLS:
        return "You can do that only once you have gone to bed."
    if isinstance(event, Work):
        return (
            "You are at work already."
            if tool == "start_work"
            else ("You are at work; leave work first.")
        )
    return "You are not at work."
