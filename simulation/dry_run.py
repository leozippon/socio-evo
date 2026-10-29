"""A scripted resident for dry runs: `DryRunModel` answers every resident's requests by playing
a plausible day from what each request shows, so that the whole pipeline runs without a model.

The day it plays depends on the resident's occupation. The shopkeeper goes to the Store at waking,
starts work, orders from the supplier the bread and what the kitchen will take the next day, sets a
price, buys bread at her own counter, keeps it until 19:00 and goes to the Restaurant, where she
leaves a helping of her bread for anyone. The chef goes to the Store once the morning's delivery is
in, buys bread for itself and, for the kitchen, what two dishes take, goes to the Restaurant, cooks
them, serves until 20:00 and, once a day, hands a dish to the first one it sees there, which nobody
pays for. Everyone else waits at home until tasks start to come in and goes to its workplace. A
programmer sits down to work there and reads the board; the first of the programmers claims a free
task, one of its own a day, and the others wait to be given one; with a task, the task's actions
offered once it is held, it runs a command, reads a file, writes a fix and submits. The team leader,
who lets the programmers look first when a task comes in and takes no task herself, gives a task
still free to the last of the programmers who holds none. While nothing is free they wait at the
Office for the next task to come in, until 17:00. The doctor keeps the surgery until 18:00,
examining and treating whoever comes; the mayor announces, grants the first programmer a little
money from the treasury and stays at work until 17:00. Then they go to the Store and buy bread if
it is open and eat a helping, the first of the programmers going by the Hospital first to be seen,
and to the Restaurant, where they have a dish if one is ready, take what is left there for anyone
and, if anyone is there, say something once and pass the first of them a little money. At 20:00
everyone goes home and to bed with a journal entry, to wake at the town's forced waking hour; in
bed, it reviews the day, notes it in memory/notes.md and falls asleep. Spoken to, it answers once a
day and leaves the conversation, at the Restaurant going back to its evening there. It keeps no
state of its own: the resident's name comes from the system prompt, and the day so far from the
messages since the last wake-up, so it continues a resumed run as it would have continued the run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.texts import NOTES_HEADINGS
from infrastructure.llm import LLMRequest, LLMResponse, Message, ToolCall
from infrastructure.llm.scripted import reply, tool_call
from world.clock import parse_hour
from world.config import TownConfig
from world.telling import bare

WORK_ENDS = parse_hour("17:00")
SURGERY_CLOSES = parse_hour("18:00")
COUNTER_CLOSES = parse_hour("19:00")
EVENING = parse_hour("20:00")
PORTIONS = 4
"""What the chef cooks of each of the first two dishes."""
BREAD = 25
"""The helpings of bread the shopkeeper orders for the next day: three for each resident."""
ANNOUNCEMENT = "The Town Hall is open today."
GRANT = 10
"""What the mayor grants the first programmer each day, for the work at the Office."""
_MOMENT = re.compile(r"\b\w+day \d+ \w+, (\d\d:\d\d)\.")
_BOARD_LINE = re.compile(r"^(\d+)\. .* The client pays \S+ and withdraws it at .*?\.(.*)$", re.M)
_HOLDER = re.compile(r"(\w+) holds it\.")
CLOSED = ("is closed: nobody is at the counter.", "The kitchen is closed.")


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
        self._occupations = {r.name: town.occupation(r.occupation) for r in town.residents}
        self._places = {place.name: place.id for place in town.places}
        self._store = town.workplace("store").id
        self._restaurant = town.workplace("restaurant").id
        self._hospital = town.workplace("hospital").id
        self._programmers = [r.name for r in town.residents if r.occupation == "programmer"]
        doctor = any(r.occupation == "doctor" for r in town.residents)
        self._patient = self._programmers[0] if doctor and self._programmers else None
        """Who goes by the Hospital after work: the first programmer, if there is a doctor."""
        self._bread = next(item.id for item in town.supplied if item.ready)
        self._dishes = town.dishes[:2]
        kitchen: dict[str, int] = {}
        for dish in self._dishes:
            for item, units in dish.ingredients.items():
                kitchen[item] = kitchen.get(item, 0) + units * PORTIONS
        self._kitchen = kitchen

    def __call__(self, request: LLMRequest) -> LLMResponse:
        if not request.tools:  # the check that the model answers, before the run
            return reply("Yes.")
        if request.tool_choice == "none":  # the compaction: the one request for text only
            return reply("\n".join(f"{heading}\nLiving my day." for heading in NOTES_HEADINGS))
        name = re.search(r"\bI am (\w+)", request.messages[0].content)
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
        self.told = "\n".join(str(m.content) for m in today if m.role in ("user", "tool"))
        self.news = messages[users[-1]].content if users else ""
        self.situation = self.news.rsplit("\n\n", 1)[-1]
        moments = _MOMENT.findall(self.situation)
        self.hour = parse_hour(moments[-1]) if moments else 0
        self.fresh = bool(messages) and messages[-1].role == "user"
        self.batch = self._last_batch() if not self.fresh else []
        occupation = model._occupations[name]
        self.occupation, self.workplace = occupation.id, occupation.workplace

    @property
    def _office(self) -> bool:
        return self.occupation in ("programmer", "team-leader")

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
        if self.occupation == "team-leader" and "came in on the board" in self.news:
            if self.hour < WORK_ENDS:  # the programmers look first
                return self._wait_minutes(5)
        if "You are at work at" in s:
            return self._at_work()
        place = self._place()
        if place == self.home:
            if self._did("go"):
                return reply("", self._sleep())
            if self.occupation == "shopkeeper":  # the counter opens at waking
                return self._go(self.model._store)
            town = self.model._town
            starts = town.day.delivery if self.occupation == "chef" else town.work.arrive_from
            if self.hour < parse_hour(starts):
                return self._wait_until(parse_hour(starts))
            return self._go(self.model._store if self.occupation == "chef" else self.workplace)
        if place == self.workplace:
            return self._at_workplace()
        if place == self.model._hospital:
            return self._seen()
        if place == self.model._store:
            return self._shop()
        if place == self.model._restaurant and self.hour < EVENING:
            return self._dine()
        return self._go(self.home)

    def _at_workplace(self) -> LLMResponse:
        """Idle at its own workplace: begin the day's work, or, the work done, move on."""
        if self._office:
            if self.hour >= WORK_ENDS:
                return self._leave()
            return reply("", tool_call("start_work"), tool_call("view_board"))
        if self.occupation == "shopkeeper":
            if self.hour >= COUNTER_CLOSES:
                return self._go(self.model._restaurant)
            orders = {self.model._bread: BREAD} | self.model._kitchen  # what the day will sell
            return reply(
                "",
                tool_call("start_work"),
                *[tool_call("order", item=item, quantity=n) for item, n in orders.items()],
                tool_call("set_price", item=self.model._bread, price=self._price_now()),
                tool_call("buy", item=self.model._bread, units=3),  # for herself, at her counter
                self._wait_call(COUNTER_CLOSES),
            )
        if self.occupation == "chef":
            if self.hour >= EVENING:
                return self._go(self.home)
            cook = [
                tool_call("cook", dish=dish.id, portions=PORTIONS) for dish in self.model._dishes
            ]
            return reply("", *cook, self._wait_call(EVENING))
        if self.occupation == "doctor":
            if self.hour >= SURGERY_CLOSES:
                return self._go(self.model._store)
            return reply("", tool_call("start_work"), self._wait_call(SURGERY_CLOSES))
        if self.hour >= WORK_ENDS:  # the mayor
            return self._go(self.model._store)
        granted = self.model._programmers[:1] or [self.name]
        return reply(
            "",
            tool_call("announce", text=ANNOUNCEMENT),
            tool_call("grant", amount=GRANT, to=granted[0], reason="For the work at the Office."),
            self._wait_call(WORK_ENDS),
        )

    def _at_work(self) -> LLMResponse:
        if self._office:
            if self.hour >= WORK_ENDS:
                return reply("", tool_call("leave_work"), *self._leave().tool_calls)
            return reply("", tool_call("view_board"))
        if self.occupation == "shopkeeper":
            if self.hour >= COUNTER_CLOSES:
                return reply(
                    "", tool_call("leave_work"), tool_call("go", place=self.model._restaurant)
                )
            ends = COUNTER_CLOSES
        elif self.occupation == "chef":
            here, dish = self._here(), self._ready_dish()
            if here and dish is not None and not self._did("pass") and self.hour < EVENING:
                return reply("", tool_call("pass", item=dish, to=here[0]), self._wait_call(EVENING))
            ends = EVENING
        elif self.occupation == "doctor":
            patients = [
                name for name in self._here() if not self._did("treat", f"You treated {name}")
            ]
            if patients and self.hour < SURGERY_CLOSES:
                name = patients[0]
                return reply(
                    "",
                    tool_call("examine", patient=name),
                    tool_call("treat", patient=name),
                    self._wait_call(SURGERY_CLOSES),
                )
            ends = SURGERY_CLOSES
        else:
            ends = WORK_ENDS
        if self.hour < ends:
            return self._wait_until(ends)
        after = self.home if self.occupation == "chef" else self.model._store
        return reply("", tool_call("leave_work"), tool_call("go", place=after))

    def _leave(self) -> LLMResponse:
        """Off from the Office: by the Hospital, for the one who goes there, or to the Store."""
        seen = self.name == self.model._patient and not self._did("go", "for the Hospital")
        return self._go(self.model._hospital if seen else self.model._store)

    def _seen(self) -> LLMResponse:
        """At the Hospital, to be seen: waits until the doctor has treated it, or the surgery
        has closed, and goes on to the Store."""
        if "treated you" in self.told or self.hour >= SURGERY_CLOSES:
            return self._go(self.model._store)
        return self._wait_minutes(30)

    def _shop(self) -> LLMResponse:
        """At the Store: the chef in the morning, buying for itself and for the kitchen; anyone
        else after work, buying bread if the counter is open."""
        closed = CLOSED[0] in self.situation
        if self.occupation == "chef":
            if closed:
                return self._wait_minutes(10)
            kitchen = [
                tool_call("buy", item=item, units=units, for_the_kitchen=True)
                for item, units in self.model._kitchen.items()
            ]
            return reply(
                "",
                tool_call("buy", item=self.model._bread, units=2),
                *kitchen,
                tool_call("go", place=self.model._restaurant),
            )
        calls = []
        if not closed and not self._did("buy", "You bought"):
            bread = self.model._bread
            calls = [
                tool_call("buy", item=bread, units=3),
                tool_call("eat", item=bread),
                tool_call("inventory"),
            ]
        return reply("", *calls, tool_call("go", place=self.model._restaurant))

    def _dine(self) -> LLMResponse:
        """At the Restaurant in the evening: a dish if one is ready, what is left there for anyone,
        the shopkeeper leaving a helping of bread there, a word to whoever is there and a little
        money for the first of them, and then the evening passes."""
        calls = []
        dish = self._ready_dish()
        if dish is not None and not self._did("buy", "You had"):
            calls.append(tool_call("buy", item=dish))
        left = re.search(r"Left here for anyone to take: (.+?)\.(?: |$)", self.situation)
        if left and not self._did("get") and not self._did("put"):
            items = self.model._town.items
            calls += [tool_call("get", item=next(i.id for i in items if bare(i.name) in left[1]))]
        if self.occupation == "shopkeeper" and not self._did("put"):
            calls.append(tool_call("put", item=self.model._bread))
        if (here := self._here()) and not self._said():
            calls += [
                tool_call("say", text=self._greeting()),
                tool_call("pass", item="money", units=2, to=here[0]),
                tool_call("leave_conversation"),
            ]
        return reply("", *calls, self._wait_call(EVENING))

    def _ready_dish(self) -> str | None:
        """The first dish the situation tells is ready, if the kitchen is open."""
        if CLOSED[1] in self.situation:
            return None
        for dish in self.model._town.dishes:
            found = re.search(
                rf"\b{re.escape(bare(dish.name))} \S+ \((\d+) ready\)", self.situation
            )
            if found:
                return dish.id
        return None

    def _here(self) -> list[str]:
        """The others the situation says are here, by name."""
        found = re.search(r"Also here: (.+?)\.(?: |$)", self.situation)
        if found is None:
            return []
        return [n for n in re.findall(r"\b([A-Z]\w+)\b", found[1]) if n in self.model._index]

    def _price_now(self) -> int:
        """A price one more than the Store's starting price of bread."""
        return self.model._town.item(self.model._bread).price + 1

    def _go(self, place: str) -> LLMResponse:
        return reply("", tool_call("go", place=place))

    def _wait_call(self, until: int) -> ToolCall:
        return tool_call("wait", minutes=min(600, max(1, (until - self.hour) // 60)))

    def _wait_until(self, until: int) -> LLMResponse:
        return reply("", self._wait_call(until))

    @staticmethod
    def _wait_minutes(minutes: int) -> LLMResponse:
        return reply("", tool_call("wait", minutes=minutes))

    def _after(self, batch: list[_Call]) -> LLMResponse:
        """The reply once the calls of `batch` have been answered and nothing new was told."""
        names = [call.name for call in batch]
        if "view_board" in names:
            return self._work(batch[names.index("view_board")].result)
        if "assign" in names:
            return reply("", tool_call("view_board"))
        if "claim_task" in names:  # taken, or by another first
            claimed = "claimed task" in batch[names.index("claim_task")].result
            return self._fix() if claimed else reply("", tool_call("view_board"))
        if "review_day" in names:
            return reply("Good night.")
        if "leave_conversation" in names and self._place() == self.model._restaurant:
            if self.hour < EVENING:  # back to the evening, and to what was left meanwhile
                return self._dine()
        return reply("")

    def _work(self, board: str) -> LLMResponse:
        """At the board: go on with the task held; the leader gives a free task to a free
        programmer; or claim a free task, one a day, the first programmer; or wait for the next
        to come in. The task's actions come with the next request, once the task is held."""
        lines = [(int(number), rest) for number, rest in _BOARD_LINE.findall(board)]
        if any("You hold it" in rest for _, rest in lines):
            return self._fix()
        free = [number for number, rest in lines if "holds it" not in rest]
        if self.occupation == "team-leader":
            holders = {found[1] for _, rest in lines if (found := _HOLDER.search(rest))}
            idle = [name for name in self.model._programmers if name not in holders]
            if free and idle:
                return reply("", tool_call("assign", task=free[0], to=idle[-1]))
            return self._wait_until(WORK_ENDS)
        given = self.name != self.model._programmers[0]
        if not free or given or self._did("submit", "ccepted"):  # one task of one's own a day
            return self._wait_until(WORK_ENDS)
        start = self.model._index[self.name] % len(lines)
        task = min(free, key=lambda number: (number - 1 - start) % len(lines))
        return reply(f"I will work on task {task}.", tool_call("claim_task", task=task))

    def _fix(self) -> LLMResponse:
        return reply(
            "",
            tool_call("shell", command="git status --short && ls"),
            tool_call("read_repo_file", path="README"),
            tool_call("write_repo_file", path="fix.py", content="FIX\n"),
            tool_call("submit"),
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
        return reply(
            "",
            tool_call("review_day"),
            tool_call("write_file", path="memory/notes.md", content=f"- {self._account()}\n"),
        )

    def _sleep(self) -> ToolCall:
        return tool_call("sleep", until=self.model._town.day.forced_wake, journal=self._account())

    def _account(self) -> str:
        """The day in a few sentences, from what its calls returned."""
        parts = []
        claim = next((c for c in self.calls if c.name == "claim_task"), None)
        if claim is not None and "claimed task" in claim.result:
            parts.append(f"I claimed task {claim.arguments['task']} at {self._workplace_name}.")
        if self._did("assign", "You gave task"):
            parts.append("I gave a task to one of the programmers.")
        submit = next((c for c in self.calls if c.name == "submit"), None)
        if submit is not None:
            accepted = "Accepted." in submit.result
            parts.append("My fix was accepted." if accepted else "My fix was not accepted.")
        if self._did("order", "You ordered"):
            parts.append("I ordered from the supplier.")
        if self._did("cook", "You cooked"):
            parts.append("I cooked for the evening.")
        if self._did("treat", "You treated"):
            parts.append("I saw a patient.")
        if self._did("announce", "You announced"):
            parts.append("I made an announcement.")
        if self._did("grant", "You granted"):
            parts.append("I made a grant from the treasury.")
        if "treated you" in self.told:
            parts.append("I was seen at the Hospital.")
        if self._did("buy", "You bought"):
            parts.append("I bought what I needed.")
        if self._did("buy", "You had"):
            parts.append("I had my supper out.")
        if self._said():
            parts.append("I talked with people in the evening.")
        return " ".join(parts) or "A quiet day."

    def _greeting(self) -> str:
        return f"Hello, I am {self.name}. I spent the day at {self._workplace_name}."

    @property
    def _workplace_name(self) -> str:
        return self.model._town.place(self.workplace).name

    def _did(self, name: str, result: str = "") -> bool:
        """Whether `name` was called today, with a result that tells `result` (what happened
        meanwhile may be told ahead of it)."""
        return any(call.name == name and result in call.result for call in self.calls)

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
