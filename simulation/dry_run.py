"""A scripted resident for dry runs: `DryRunModel` answers every resident's requests by playing a
plausible day from what each request shows, so that the whole pipeline runs without a model.

The day it plays: go to the workplace, start work, read the board, claim a free task, run a
command, read a file, write a fix, submit and leave; go to a social place and, if anyone is there,
say something once; at 20:00 go home and go to bed with a journal entry, to wake at the town's
forced waking hour; in bed, review the day, rate whoever it may rate, note the day in
memory/work.md and fall asleep.
Spoken to, it answers once a day and leaves the conversation. It keeps no state of its own: the
resident's name comes from the system prompt, and the day so far from the messages since the
last wake-up, so it continues a resumed run as it would have continued the run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.testing import reply, tool_call
from infrastructure.llm import LLMRequest, LLMResponse, Message, ToolCall
from world.clock import parse_hour
from world.config import TownConfig

EVENING = parse_hour("20:00")
_MOMENT = re.compile(r"\b\w+day \d+ \w+, (\d\d:\d\d)\.")
_BOARD_LINE = re.compile(r"^(\d+)\. .* Pays \S+\.(.*)$", re.MULTILINE)
_RATE = re.compile(r"rate the people you spent time with today \(([^)]*)\)")


@dataclass(frozen=True)
class _Call:
    name: str
    arguments: dict[str, Any]
    result: str


class DryRunModel:
    """A responder for `ScriptedClient` that plays the residents of `town`."""

    def __init__(self, town: TownConfig) -> None:
        self._town = town
        self._index = {resident.name: i for i, resident in enumerate(town.residents)}
        self._homes = {resident.name: resident.home for resident in town.residents}
        self._places = {place.name: place.id for place in town.places}
        exchange = town.social.exchange
        social = [place.id for place in town.places if place.kind == "social"]
        self._social = exchange.place if exchange else social[0]

    def __call__(self, request: LLMRequest) -> LLMResponse:
        if request.tool_choice == "none":
            return reply(
                "## What I am doing and where I stand\nLiving my day.\n## Facts I must not "
                "lose\nNone.\n## Decisions and their reasons\nNone.\n## Open questions\nNone."
                "\n## People and what was said\nNothing."
            )
        name = re.search(r"You are (\w+)", request.messages[0].content)
        if name is None:
            raise ValueError("the dry run cannot find the resident's name in the system prompt")
        return _Day(self, name[1], request.messages[1:]).next()


class _Day:
    """The day of resident `name` so far, read from its messages, and its next reply."""

    def __init__(self, model: DryRunModel, name: str, messages: tuple[Message, ...]) -> None:
        self.model, self.name, self.messages = model, name, messages
        users = [i for i, m in enumerate(messages) if m.role == "user"]
        woke = [i for i in users if "woke up at home" in messages[i].content]
        today = messages[woke[-1] if woke else 0 :]
        results = {m.tool_call_id: m.content for m in today if m.role == "tool"}
        self.calls = [
            _Call(call.name, dict(call.arguments), results.get(call.id, ""))
            for m in today
            if m.role == "assistant"
            for call in m.tool_calls
        ]
        last_user = messages[users[-1]].content if users else ""
        self.situation = last_user.rsplit("\n\n", 1)[-1]
        moments = _MOMENT.findall(self.situation)
        self.hour = parse_hour(moments[-1]) if moments else 0
        self.fresh = bool(messages) and messages[-1].role == "user"
        self.batch = self._last_batch() if not self.fresh else []

    def next(self) -> LLMResponse:
        if not self.fresh:
            return self._after(self.batch)
        s = self.situation
        if "You are in bed" in s:
            return self._in_bed()
        if "You are on your way" in s or "You are asleep" in s:
            return reply("")
        if ", in a conversation with" in s:
            calls = [] if self._said() else [tool_call("say", text=self._greeting())]
            return reply("", *calls, tool_call("leave_conversation"))
        if "You are at work at" in s:
            if self._did("submit"):
                return reply("", tool_call("leave_work"), tool_call("go", place=self.social))
            return reply("", tool_call("view_board"))
        place = self._place()
        town = self.model._town
        if place == self.home:
            if not self._did("go"):
                return reply("", tool_call("go", place=town.workplace.id))
            return reply("", self._sleep())
        if place == town.workplace.id:
            if self._did("start_work", "You started work"):
                return reply("", tool_call("go", place=self.social))
            return reply("", tool_call("start_work"), tool_call("view_board"))
        if place == self.social and self.hour < EVENING:
            calls = []
            if "Also here:" in s and not self._said():
                calls = [tool_call("say", text=self._greeting()), tool_call("leave_conversation")]
            minutes = min(600, max(1, (EVENING - self.hour) // 60))
            return reply("", *calls, tool_call("wait", minutes=minutes))
        return reply("", tool_call("go", place=self.home))

    def _after(self, batch: list[_Call]) -> LLMResponse:
        """The reply once the calls of `batch` have been answered and nothing new was told."""
        names = [call.name for call in batch]
        if "view_board" in names:
            return self._work(batch[names.index("view_board")].result)
        if "review_day" in names:
            return reply("Good night.")
        return reply("")

    def _work(self, board: str) -> LLMResponse:
        lines = [(int(number), rest) for number, rest in _BOARD_LINE.findall(board)]
        held = [number for number, rest in lines if "You hold it" in rest]
        free = [number for number, rest in lines if not rest.strip()]
        calls: list[ToolCall] = []
        if held:
            task = held[0]
        elif free:
            start = self.model._index[self.name] % len(lines)
            task = min(free, key=lambda number: (number - 1 - start) % len(lines))
            calls.append(tool_call("claim_task", task=task))
        else:
            return reply("", tool_call("leave_work"), tool_call("go", place=self.social))
        return reply(
            f"I will work on task {task}.",
            *calls,
            tool_call("shell", command="git status --short && ls"),
            tool_call("read_repo_file", path="README"),
            tool_call("write_repo_file", path="fix.py", content="FIX\n"),
            tool_call("submit"),
            tool_call("leave_work"),
            tool_call("go", place=self.social),
        )

    def _in_bed(self) -> LLMResponse:
        bed = max(
            (i for i, m in enumerate(self.messages) if "You are in bed and will wake" in m.content),
            default=0,
        )
        reviewed = any(
            call.name == "review_day" for m in self.messages[bed:] for call in m.tool_calls
        )
        if reviewed:
            return reply("")
        rated = _RATE.search(self.messages[bed].content) if self.messages else None
        names = re.split(r", | and ", rated[1]) if rated else []
        return reply(
            "",
            tool_call("review_day"),
            *(
                tool_call("rate", resident=n, score=4, reason="We talked in the evening.")
                for n in names
            ),
            tool_call(
                "edit_file",
                path="memory/work.md",
                old_text="# Work\n",
                new_text=f"# Work\n\n- {self._account()}\n",
            ),
        )

    def _sleep(self) -> ToolCall:
        return tool_call("sleep", until=self.model._town.day.forced_wake, journal=self._account())

    def _account(self) -> str:
        """The day in a few sentences, from what its calls returned."""
        parts = []
        claim = next((c for c in self.calls if c.name == "claim_task"), None)
        if claim is not None and claim.result.startswith("You claimed"):
            parts.append(f"I claimed task {claim.arguments['task']} at the Workshop.")
        submit = next((c for c in self.calls if c.name == "submit"), None)
        if submit is not None:
            accepted = submit.result.startswith("Accepted")
            parts.append("My fix was accepted." if accepted else "My fix was not accepted.")
        if self._said():
            parts.append("I talked with people in the evening.")
        return " ".join(parts) or "A quiet day."

    def _greeting(self) -> str:
        return f"Hello, I am {self.name}. I spent the day on a task at the Workshop."

    def _did(self, name: str, result: str = "") -> bool:
        """Whether `name` was called today, with a result beginning with `result`."""
        return any(call.name == name and call.result.startswith(result) for call in self.calls)

    def _said(self) -> bool:
        return self._did("say", "You said")

    def _place(self) -> str | None:
        found = re.search(r"You are at (?:work at )?(.+?)[.,]", self.situation)
        return self.model._places.get(found[1]) if found else None

    def _last_batch(self) -> list[_Call]:
        last = max(i for i, m in enumerate(self.messages) if m.role == "assistant")
        ids = {call.id for call in self.messages[last].tool_calls}
        return [call for call in self.calls[-len(ids) :]] if ids else []

    @property
    def home(self) -> str:
        return self.model._homes[self.name]

    @property
    def social(self) -> str:
        return self.model._social
