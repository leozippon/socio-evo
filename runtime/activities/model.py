"""Serializable activities and a deterministic event clock, measured in integer seconds."""

import heapq
import math
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ConfigDict, Field

from infrastructure.config import StrictModel


class Timing(StrictModel):
    read_seconds_per_100_lines: int = Field(default=60, ge=1)
    edit_seconds_per_100_lines: int = Field(default=120, ge=1)
    command_seconds: int = Field(default=300, ge=1)
    search_seconds: int = Field(default=60, ge=1)
    handoff_seconds: int = Field(default=60, ge=1)
    submit_seconds: int = Field(default=60, ge=1)
    invite_seconds: int = Field(default=60, ge=1)
    read_units_per_minute: int = Field(default=500, ge=1)
    reply_units_per_minute: int = Field(default=250, ge=1)
    travel_seconds_per_unit: int = Field(default=60, ge=1)
    default_work_minutes: int = Field(default=60, ge=1, le=240)
    default_conversation_minutes: int = Field(default=30, ge=1, le=120)
    appointment_grace_seconds: int = Field(default=300, ge=0, le=3600)
    assessment_seconds: int = Field(default=1200, ge=1)
    warning_seconds: int = Field(default=300, ge=0)
    max_zero_transitions: int = Field(default=12, ge=2, le=100)
    max_read_lines: int = Field(default=400, ge=1, le=2000)
    max_message_units: int = Field(default=2000, ge=1, le=8000)

    def text_cost(self, text: str, *, reading: bool = False) -> int:
        speed = self.read_units_per_minute if reading else self.reply_units_per_minute
        return max(1, math.ceil(units(text) * 60 / speed))


# Count CJK characters individually; other letter/digit runs are words. Punctuation is free.
def units(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]|[^\W\u3400-\u9fff]+", text, re.UNICODE))


def clock(seconds: int) -> str:
    seconds %= 86400
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def at(day: int, text: str) -> int:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?", text):
        raise ValueError("Use HH:MM or HH:MM:SS")
    h, m, *s = map(int, text.split(":"))
    return (day - 1) * 86400 + h * 3600 + m * 60 + (s[0] if s else 0)


class MutableState(StrictModel):
    model_config = ConfigDict(frozen=False, validate_assignment=True)


class Member(MutableState):
    start: int
    end: int
    cursor: int = 0
    joined_cursor: int = 0
    event_cursor: int = 0
    active: bool = True


class Activity(MutableState):
    id: str
    kind: str
    place: str
    start: int
    latest_end: int
    status: Literal["active", "paused", "ended"] = "active"
    members: dict[str, Member] = Field(default_factory=dict)
    tools: tuple[str, ...] = ()
    feedback: dict[str, list[str]] = Field(default_factory=dict)
    result: dict[str, str] = Field(default_factory=dict)

    @property
    def participants(self) -> tuple[str, ...]:
        return tuple(who for who, member in self.members.items() if member.active)


class RestActivity(Activity):
    kind: Literal["rest"] = "rest"
    wake_invitations: bool = True


class MoveActivity(Activity):
    kind: Literal["move"] = "move"
    origin: str
    destination: str


class WorkActivity(Activity):
    tools: tuple[str, ...] = (
        "board",
        "claim",
        "read_code",
        "search",
        "diff",
        "edit",
        "command",
        "test",
        "handoff",
        "apply_handoff",
        "submit",
        "leave",
    )
    kind: Literal["work"] = "work"
    task_id: str | None = None
    public: bool = False
    mode: Literal["parallel", "relay"] = "parallel"
    relay_owner: str | None = None
    history: list[dict] = Field(default_factory=list)


class Message(StrictModel):
    id: int
    author: str
    sent_at: int
    text: str
    audience: tuple[str, ...]


class ConversationActivity(Activity):
    tools: tuple[str, ...] = ("read", "reply", "wait", "invite", "leave")
    kind: Literal["conversation"] = "conversation"
    topic: str
    public: bool = False
    invited: tuple[str, ...] = ()
    messages: list[Message] = Field(default_factory=list)

    def unread(self, who: str) -> list[Message]:
        member = self.members[who]
        if not member.active:
            return []
        return [m for m in self.messages[member.cursor :] if who in m.audience and m.author != who]


class Invitation(MutableState):
    id: str
    owner: str
    invited: tuple[str, ...]
    confirmed: list[str]
    place: str
    topic: str
    start: int
    duration: int
    grace_end: int
    public: bool = False
    status: Literal["pending", "started", "cancelled"] = "pending"
    conversation: str | None = None


class Handoff(MutableState):
    id: str
    task_id: str
    sender: str
    recipient: str
    patch: str
    description: str
    created_at: int
    version: str
    status: Literal["offered", "accepted", "declined"] = "offered"


@dataclass(order=True)
class Scheduled:
    time: int
    priority: int
    sequence: int
    kind: str = field(compare=False)
    data: dict = field(default_factory=dict, compare=False)


class EventQueue:
    def __init__(self):
        self.events: list[Scheduled] = []
        self.sequence = 0

    def add(self, time: int, kind: str, *, priority: int = 1, **data):
        self.sequence += 1
        heapq.heappush(self.events, Scheduled(time, priority, self.sequence, kind, data))

    def pop_at(self, time: int) -> list[Scheduled]:
        found = []
        while self.events and self.events[0].time == time:
            found.append(heapq.heappop(self.events))
        return found

    def next_time(self) -> int:
        return self.events[0].time


ACTIVITIES = {
    "rest": RestActivity,
    "move": MoveActivity,
    "work": WorkActivity,
    "conversation": ConversationActivity,
}
