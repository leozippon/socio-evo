"""The world of one town: its state, its schedule, and one port per resident.

`World` is created from a configuration, a run directory and a work backend; creating it loads
the task split, checks that every task's image is present and that every agent directory exists,
and writes nothing. A new world stands at the checkpoint hour of day 1 with every resident asleep
at home, to wake at the forced waking hour, with day 1's arrivals of tasks drawn and nothing on
the board yet; `restore` puts it instead in the state of a saved checkpoint, with its open tasks
and the coming day's arrivals. `run` then drives the town until a given day's checkpoint.

Everything that happens at a moment of simulated time is a timer in one queue, run by `run` in the
order of its times: arrivals, wake-ups, the end of a silent conversation, the percept that tells a
waiting resident the time, and the day's schedule, which is all the fixed structure a day has. For
day N (whose daytime is calendar day N): the arrival of each task drawn for the day, told to those
at the Office, and the delivery of what the Store ordered the day before; midnight, when each
resident's food and health are reckoned and illness comes or passes, the treasury pays the salary
and takes the rent and daily charges, with a statement, the clients withdraw the tasks
whose time has run out, the portions the kitchen did not sell are gone and the next day's arrivals
are drawn; the forced sleep; and the checkpoint. Every hour on the hour, besides, the bodies are
brought up to date (`world.living`). No place keeps hours, and residents go to bed and wake when
they choose, except that one sleep lasts at most a configured span and that nobody wakes between the
forced sleep and the checkpoint. At the checkpoint the world waits until every resident is asleep
and its runtime waits on its port, holds the clock, closes every workspace keeping its changes,
takes the snapshot and awaits `on_checkpoint(day, snapshot)`, through which the composition layer
writes the checkpoint and commits the agent directories. A lived day N runs from the checkpoint on
calendar day N to the one on calendar day N + 1; the journal, the acceptance runs and the record
`review_day` tells belong to it.

Beyond its construction, the schedule, the checkpoint and the glue between them (recording and
delivering, places and people, going and arriving, conversations, a resident's tools and calls),
the world's concerns are modules of their own whose functions take the world first: what a resident
reads (`world.situation`), midnight and the treasury's day (`world.midnight`), items and their
holders (`world.holders`), the body, sleep and waking, bed and treatment (`world.living`) and each
resident's port (`world.port`), besides the tools (`world.tools`, `world.office`) and the
businesses (`world.businesses`). `World` binds as its own methods the functions that the tools, the
other modules and the outer layers call, so that `world.look(r)` is
`world.situation.look(world, r)`; a module reaches another's functions only through the world it is
given, and imports this one only to annotate, so that no import runs in a cycle.

A resident's living (`Living`, of `world.body`) is what it has eaten since the last midnight and
its body's three needs; its inventory (`Inventory`, of `world.economy`) is its money and the items
it keeps, which act through it. Whatever a resident is paid for its work, by a client, a customer
or a patient, goes into its purse with the tax withheld into the town's treasury (`earn`,
`Treasury`), which at midnight pays the mayor's salary and takes the rent and daily charges. Its
time on duty (`on_duty`; `Resident.worked`, counted as the body is reckoned and cleared at
midnight) earns nothing and is kept for the measures. The mayor's announcements stand on the Town
Hall's board. A durable with the effect travel shortens the owner's journeys, one with messaging
lets it write to other owners, and one with appearance shows its phrase wherever others perceive
the owner: who is here, who arrived, whom one is in conversation with; a low band of health shows
the same way. Rent is the home's, paid to the treasury, which owns the homes, and a resident may
move into a home with a free room.

The Store's counter, the Restaurant's kitchen and the Hospital's surgery are the town's businesses
(`world.businesses`), each open while its keeper is at work there and selling at the prices of
`prices`, and each is its keeper's. A sale at the Store moves the price from the buyer's purse to
the shopkeeper's and the units off its shelves, and when the chef buys for the kitchen, the chef
pays and the units are sent to the kitchen's larder; the shopkeeper pays the supplier for the
orders (`Store`) at once, and the supplier's units come onto the shelves at the next morning's
delivery. The chef cooks portions from the larder, a portion bought, or handed over by the chef,
is eaten at once, and what perishes is gone at midnight, wherever it is. At each place the
situation tells what is left there, what is for sale and at what price, and the keeper of a
business what it holds.

Each resident's port declares to its runtime the tools of its event at its place now that its
occupation gives it (`usable`), so that what a request offers is what can be done; a call of one
of the town's tools that was not declared is carried out all the same, or refused naming the
condition (`call`). The world delivers each percept to the ports of those who perceive it.
Speech reaches the residents it is addressed to, at their place and awake; it draws into the
conversation, with `interrupt`, those it names and, when it is said to everyone, those not
working outside the conversation. In a conversation a resident can still do what the event it
covers offers, and doing what the conversation does not offer of its own (its work, for one)
leaves the conversation first. A resident at work outside it hears a remark to everyone
without being drawn in or interrupted, and reads it, like everything else, with its runtime's
next tool result or when it next waits. A resident in transit is at no place and perceives
nothing there; an asleep resident cannot be addressed, and what is told to it while suspended is
held until it wakes.
"""

from __future__ import annotations

import asyncio
import copy
import heapq
import inspect
import itertools
import math
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from functools import partial
from pathlib import Path
from types import EllipsisType
from typing import Any

import world.holders
import world.living
import world.midnight
import world.situation
from agent.port import Percept, ToolResult, ToolSpec
from infrastructure.storage import RunDirectory
from world import office, tools
from world.backend import Backend
from world.body import Body, Living
from world.businesses import KITCHEN, STORE, SURGERY, starting_prices
from world.clock import (
    DAY,
    Clock,
    ManualClock,
    clock_time,
    parse_hour,
    tell_moment,
)
from world.config import Occupation, TownConfig
from world.economy import (
    LARDER,
    PORTIONS,
    SHELVES,
    SUPPLIER,
    Holder,
    Inventory,
    Store,
    Supplier,
    Treasury,
)
from world.events import (
    CONVERSATION_TOOLS,
    TALK,
    Base,
    Conversation,
    Idle,
    Movement,
    Sleep,
    Work,
    refusal,
)
from world.log import Entry, WorldLog
from world.occupations import BEDSIDE, OCCUPATIONS, TASK_TOOLS, WORK_DONE
from world.office import Board
from world.port import ResidentPort
from world.rules import Rules
from world.telling import cap, counted, listed, you

Tell = Callable[[str | None], str]
"""A text as told to a witness (None: to nobody in particular)."""
OnCheckpoint = Callable[[int, dict[str, Any]], Awaitable[None]]
HANDLERS = tools.HANDLERS | office.HANDLERS  # every handler, by the name of what it does


@dataclass(order=True)
class _Timer:
    t: int
    order: int
    fn: Callable[[], Any] = field(compare=False)
    cancelled: bool = field(default=False, compare=False)

    def cancel(self) -> None:
        self.cancelled = True


@dataclass(eq=False)
class Resident:
    """A resident's state in the world. `home` is where it lives now; `timer` is its arrival or
    its wake-up; `tick` the percept that will tell it the time while its runtime waits;
    `reckoned` the simulated time its body was last brought up to; `worked` the seconds it has
    spent on duty since the last midnight (`World.on_duty`), for the measures; `day`
    the record of its lived day: (simulated time, kind, its wording, payload) of every entry that
    concerns it."""

    name: str
    home: str
    agent_dir: Path
    place: str | None
    base: Base
    occupation: Occupation
    living: Living = field(default_factory=Living)
    inventory: Inventory = field(default_factory=Inventory)
    reckoned: int = 0
    worked: int = 0
    conversation: Conversation | None = None
    wait_minutes: int | None = None
    timer: _Timer | None = None
    tick: _Timer | None = None
    day: list[tuple[int, str, str, dict[str, Any]]] = field(default_factory=list)
    port: ResidentPort = field(init=False)

    @property
    def event(self) -> Base | Conversation:
        """The event the resident is in: its conversation while one lasts, else its base."""
        return self.conversation or self.base

    @property
    def tools(self) -> frozenset[str]:
        """What the resident can do now: its base event's actions and, in a conversation, the
        conversation's talk besides."""
        if self.conversation is None:
            return self.base.tools
        return self.base.tools | TALK

    @property
    def awake(self) -> bool:
        return not isinstance(self.base, Sleep)

    @property
    def suspended(self) -> bool:
        """Whether nothing reaches the resident: asleep."""
        return isinstance(self.base, Sleep) and self.base.suspended


class World:
    # What a resident reads.
    situation = world.situation.situation
    look = world.situation.look
    things_told = world.situation.things_told
    purse = world.situation.purse
    cannot_pay = world.situation.cannot_pay
    inventory_told = world.situation.inventory_told
    review = world.situation.review
    # The treasury's day, which the mayor's statement tells at midnight and the run's log after.
    treasury_told = world.midnight.treasury_told
    # Items and their holders.
    holder = world.holders.holder
    reach = world.holders.reach
    move = world.holders.move
    moved = staticmethod(world.holders.moved)
    record_move = world.holders.record_move
    hand = world.holders.hand
    eat_now = world.holders.eat_now
    held_told = world.holders.held_told
    # The body, sleep and waking, bed and treatment.
    reckon = world.living.reckon
    on_duty = staticmethod(world.living.on_duty)
    activity = world.living.activity
    note_bands = world.living.note_bands
    nourishment = world.living.nourishment
    eat = world.living.eat
    take_in = world.living.take_in
    take_to_bed = world.living.take_to_bed
    treat = world.living.treat
    go_to_bed = world.living.go_to_bed
    fall_asleep = world.living.fall_asleep

    def __init__(
        self,
        config: TownConfig,
        run_dir: Path,
        backend: Backend,
        *,
        clock: Clock | ManualClock | None = None,
    ) -> None:
        tasks = list(backend.load_split(config.work.split))
        if not tasks:
            raise ValueError(f"the split {config.work.split!r} has no tasks")
        backend.require_images(tasks)
        run = RunDirectory(run_dir)
        directories = {r.name: r.agent_dir or run.agent_dir(r.name) for r in config.residents}
        missing = [str(path) for path in directories.values() if not path.is_dir()]
        if missing:
            raise FileNotFoundError(f"missing agent directories: {', '.join(missing)}")

        self.config = config
        # The day's fixed hours, in seconds after midnight, and the longest a sleep lasts.
        self.forced_sleep = parse_hour(config.day.forced_sleep)
        self.forced_wake = parse_hour(config.day.forced_wake)
        self._delivery = parse_hour(config.day.delivery)
        self.checkpoint_hour = parse_hour(config.day.checkpoint)
        self.sleep_at_most = parse_hour(config.day.sleep_at_most)
        start = self.checkpoint_hour
        self.clock = clock or Clock(
            start,
            len(config.residents),
            speed_idle=config.clock.speed_idle,
            speed_busy_one=config.clock.speed_busy_one,
            speed_busy_all=config.clock.speed_busy_all,
        )
        self.clock.set(start)
        self.log = WorldLog(run.world_log_path)
        names = [r.name for r in config.residents]
        self.treasury = Treasury(config.treasury.start)
        self.prices = starting_prices(config)
        """What each business sells, at its price now, by the business's kind."""
        self.store = Store()
        self.holders: dict[str, Holder] = {place.id: Holder() for place in config.places}
        """Every holder of items but the residents, by name (see `holder`)."""
        self.holders |= {
            SHELVES: Holder(dict(config.store.stock)),
            LARDER: Holder(),
            PORTIONS: Holder(),
            SUPPLIER: Supplier(),
        }
        self.announcements: list[list[int | str]] = []
        """The mayor's announcements standing on the Town Hall's board, each `[time, text]`."""
        self.board = Board(tasks, backend, config, names=names)
        self.board.schedule = self.board.draw(1)
        self.body = Body(config.needs)
        self.rules = Rules(config)
        self.tool_specs: list[ToolSpec] = tools.specs(config)
        # Each occupation's declarations by name, as its residents' requests carry them.
        self._specs = {
            occupation.id: {spec.name: spec for spec in tools.own(self.tool_specs, occupation.id)}
            for occupation in config.occupations
        }
        self._timers: list[_Timer] = []
        self._order = itertools.count()
        self._pushed = asyncio.Event()
        self._rest = asyncio.Event()
        self._rooms: dict[str, Conversation] = {}
        self._started = False
        self._stopped = False
        self._until = 0
        self._on_checkpoint: OnCheckpoint | None = None
        self.residents: dict[str, Resident] = {}
        for rc in config.residents:
            r = Resident(
                rc.name,
                rc.home,
                directories[rc.name],
                rc.home,
                Sleep(0, True),
                config.occupation(rc.occupation),
                inventory=Inventory(money=rc.purse),
                reckoned=start,
            )
            r.port = ResidentPort(self, r)
            self.residents[rc.name] = r
            world.living.put_to_sleep(self, r, self.forced_wake, suspended=True)

    @property
    def ports(self) -> dict[str, ResidentPort]:
        return {name: r.port for name, r in self.residents.items()}

    def lived_day(self) -> int:
        """The day being lived: from one checkpoint to the next."""
        return (self.clock.now() - self.checkpoint_hour) // DAY + 1

    # The schedule -----------------------------------------------------------------------------

    async def run(self, until_day: int, on_checkpoint: OnCheckpoint) -> None:
        """Run the town until the checkpoint of `until_day` has been handed to
        `on_checkpoint`."""
        if until_day < self.lived_day():
            raise ValueError(f"day {until_day} is already over")
        self._started = True
        self._until, self._on_checkpoint, self._stopped = until_day, on_checkpoint, False
        self._schedule_day(self.lived_day())
        self._hourly()
        while not self._stopped:
            while self._timers[0].cancelled:
                heapq.heappop(self._timers)
            timer = self._timers[0]
            if timer.t > self.clock.now():
                await self._sleep_until(timer.t)
                continue
            heapq.heappop(self._timers)
            result = timer.fn()
            if inspect.isawaitable(result):
                await result

    def at(self, t: int, fn: Callable[[], Any]) -> _Timer:
        """Run `fn` at the simulated time `t`."""
        timer = _Timer(t, next(self._order), fn)
        heapq.heappush(self._timers, timer)
        self._pushed.set()
        return timer

    async def _sleep_until(self, t: int) -> None:
        """Sleep until `t` or until a timer is added, whichever comes first."""
        self._pushed.clear()
        sleeper = asyncio.ensure_future(self.clock.sleep_until(t))
        pushed = asyncio.ensure_future(self._pushed.wait())
        try:
            await asyncio.wait({sleeper, pushed}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleeper.cancel()
            pushed.cancel()

    def _schedule_day(self, day: int) -> None:
        """Arm the fixed hours of lived day `day`, from its opening checkpoint hour (where a new
        world starts and a restored one stands), which the configuration puts before all of
        them, and the day's arrivals of tasks, drawn at the midnight before."""
        for t in self.board.schedule:
            self.at(t, partial(office.arrival, self, t))
        self.at(self.delivery(day), self._deliver)
        self.at(day * DAY, partial(world.midnight.midnight, self, day))
        self.at(day * DAY + self.forced_sleep, partial(world.living.force_sleep, self, day))
        self.at(day * DAY + self.checkpoint_hour, partial(self._checkpoint, day))

    def delivery(self, day: int) -> int:
        """When what the Store ordered the day before comes onto its shelves on calendar day
        `day`."""
        return (day - 1) * DAY + self._delivery

    def _deliver(self) -> None:
        """What the Store ordered for this morning comes from the supplier onto its shelves, told
        to its shopkeeper."""
        came = self.store.due(self.clock.now())
        if not came:
            return
        for item, units in came.items():
            self.moved(self.move(item, units, SUPPLIER, SHELVES))
        store = self.config.workplace("store")
        goods = listed(self.held_told(came))
        hour = clock_time(self.clock.now())
        self.record(
            "delivery",
            lambda w: f"It is {hour}: the supplier delivered {goods} to {store.name}.",
            place=store.id,
            audience=[r for r in self.residents.values() if STORE.keeps(r.occupation.id)],
            payload={"items": came},
        )

    def _hourly(self) -> None:
        """Every hour on the hour, every resident's body is brought up to it; the first call,
        as the world starts to run, only arms the next hour."""
        for r in self.residents.values():
            self.reckon(r)
        now = self.clock.now()
        self.at(now - now % 3600 + 3600, self._hourly)

    # The checkpoint ---------------------------------------------------------------------------

    async def _checkpoint(self, day: int) -> None:
        while not self._all_resting():
            await self._rest.wait()
        assert self._on_checkpoint is not None
        with self.clock.hold():
            for name, claim in await self.board.close_all():
                self.record(
                    "workspace_closed",
                    lambda w, name=name, claim=claim: (
                        f"The workspace of task {claim.task} closed for the night, its changes "
                        f"kept for {you(name, w)}."
                    ),
                    actor=self.residents[name],
                    place=None,
                    payload={"task": claim.task, "diff": claim.diff},
                )
            self.board.new_day()
            for r in self.residents.values():
                r.day.clear()
                self.reckon(r)
            state = self.snapshot()
            self.record(
                "checkpoint", lambda w: f"The state of day {day} was saved.", payload={"day": day}
            )
            await self._on_checkpoint(day, state)
        if day >= self._until:
            self._stopped = True
        else:
            self._schedule_day(day + 1)

    def _all_resting(self) -> bool:
        return all(r.suspended and r.port.waiting for r in self.residents.values())

    def rest_changed(self) -> None:
        if self._all_resting():
            self._rest.set()
        else:
            self._rest.clear()

    def snapshot(self) -> dict[str, Any]:
        """The world's whole state at a checkpoint: every resident asleep, nothing open; every
        holder of items with what it holds (the residents' in their inventories)."""
        unsettled = [
            r.name
            for r in self.residents.values()
            if not r.suspended or r.conversation or r.port.has_pending
        ]
        if (
            unsettled
            or any(claim.workspace for claim in self.board.claims.values())
            or self.board.orphans
            or self._rooms
            or any(self.board.runs.values())
        ):
            raise RuntimeError(f"no checkpoint state: unsettled {unsettled or 'world state'}")
        residents = {}
        for name, r in self.residents.items():
            assert isinstance(r.base, Sleep)
            claim = self.board.claims.get(name)
            residents[name] = {
                "place": r.place,
                "home": r.home,
                "living": asdict(r.living),
                "inventory": asdict(r.inventory),
                "worked": r.worked,
                "wake": r.base.wake,
                "longest": r.base.longest,
                "claim": claim.saved() if claim else None,
                "held": [asdict(percept) for percept in r.port.held],
            }
        return {
            "time": self.clock.now(),
            "office": self.board.saved(),
            "treasury": asdict(self.treasury),
            "store": {"prices": dict(self.prices[STORE.kind])} | asdict(self.store),
            "kitchen": {"menu": dict(self.prices[KITCHEN.kind])},
            "holders": {
                key: dict(holder.items) for key, holder in self.holders.items() if key != SUPPLIER
            },
            "fees": dict(self.prices[SURGERY.kind]),
            "announcements": copy.deepcopy(self.announcements),
            "residents": residents,
        }

    def restore(self, state: dict[str, Any]) -> None:
        """Put a new world in the state `snapshot` returned, and log the resumption."""
        if self._started:
            raise RuntimeError("a world is restored before it runs")
        if set(state["residents"]) != set(self.residents):
            raise ValueError("the checkpoint's residents are not the configuration's")
        self.clock.set(state["time"])
        self.board.restore(state["office"])
        self.treasury = Treasury(**copy.deepcopy(state["treasury"]))
        self.prices = {
            STORE.kind: dict(state["store"]["prices"]),
            KITCHEN.kind: dict(state["kitchen"]["menu"]),
            SURGERY.kind: dict(state["fees"]),
        }
        self.store = Store(copy.deepcopy(state["store"]["pending"]))
        if set(state["holders"]) != set(self.holders) - {SUPPLIER}:
            raise ValueError("the checkpoint's holders are not the configuration's places'")
        for key, items in state["holders"].items():
            self.holders[key] = Holder(dict(items))
        self.announcements = copy.deepcopy(state["announcements"])
        for name, saved in state["residents"].items():
            r = self.residents[name]
            assert r.timer is not None
            r.timer.cancel()
            r.place = saved["place"]
            r.home = saved["home"]
            r.living = Living(**copy.deepcopy(saved["living"]))
            r.inventory = Inventory(**copy.deepcopy(saved["inventory"]))
            r.worked = saved["worked"]
            r.reckoned = state["time"]
            world.living.put_to_sleep(
                self, r, saved["wake"], suspended=True, longest=saved["longest"]
            )
            if saved["claim"] is not None:
                self.board.hold(name, saved["claim"])
            r.port.held = [Percept(**percept) for percept in saved["held"]]
        moment = tell_moment(state["time"], self.config.start_date)
        self.record(
            "resume",
            lambda w: f"The town went back to {moment}.",
            payload={"day": self.lived_day() - 1, "time": state["time"]},
        )

    # Recording and delivering -----------------------------------------------------------------

    def record(
        self,
        kind: str,
        tell: Tell,
        *,
        actor: Resident | None = None,
        place: str | None | EllipsisType = ...,
        audience: list[Resident] | tuple[Resident, ...] = (),
        interrupt: list[Resident] | tuple[Resident, ...] = (),
        payload: dict[str, Any] | None = None,
    ) -> Entry:
        """Log an event, add it to the day of each resident it concerns (the actor and the
        audience) in that resident's wording, and deliver it as a percept to the audience,
        interrupting those in `interrupt`. `place` defaults to the actor's."""
        if place is ...:
            place = actor.place if actor else None
        concerned = ([actor] if actor else []) + [r for r in audience if r is not actor]
        text = tell(None)
        personal = {r.name: told for r in concerned if (told := tell(r.name)) != text}
        entry = self.log.append(
            kind,
            self.clock.now(),
            text,
            actor=actor.name if actor else None,
            place=place,
            audience=[r.name for r in audience],
            personal=personal,
            payload=payload,
        )
        for r in concerned:
            r.day.append((entry.sim_time, kind, personal.get(r.name, text), dict(entry.payload)))
        loud = {r.name for r in interrupt}
        for r in audience:
            told = personal.get(r.name, text)
            percept = Percept(told, kind, entry.seq, entry.sim_time, entry.real_time)
            r.port.deliver(percept, r.name in loud)
        return entry

    # Places and people ------------------------------------------------------------------------

    def visible(self, a: Resident, b: Resident) -> bool:
        """Whether `a` perceives `b`: both at the same place."""
        return a is not b and a.place is not None and a.place == b.place

    def company(self, r: Resident) -> list[Resident]:
        return [other for other in self.residents.values() if self.visible(r, other)]

    def addressable(self, r: Resident) -> list[Resident]:
        return [other for other in self.company(r) if other.awake]

    def of_occupation(self, occupation: str) -> list[Resident]:
        """The residents whose occupation is `occupation`."""
        return [r for r in self.residents.values() if r.occupation.id == occupation]

    def occupants(self, place_id: str) -> list[Resident]:
        """Who lives at `place_id` now."""
        return [r for r in self.residents.values() if r.home == place_id]

    def homes(self) -> dict[str, list[str]]:
        """Who lives where now, for the rules and `help`."""
        return {
            place.id: [other.name for other in self.occupants(place.id)]
            for place in self.config.places
            if place.kind == "home"
        }

    # Work and pay -----------------------------------------------------------------------------

    def stop_work(self, r: Resident) -> None:
        """`r` stops work: by its own `leave_work`, by leaving its workplace or going to bed, or
        because the forced sleep takes it, so that every stretch of work in the log ends. The
        body is reckoned first, and may have stopped it already."""
        self.reckon(r)
        if isinstance(r.base, Work):
            r.base = Idle()
            self.record("leave_work", lambda w: f"{cap(you(r.name, w))} stopped work.", actor=r)

    def stopped_told(self, r: Resident, *why: str) -> str:
        """What `r` is told on stopping work, with `why`, if it did not choose to: that it
        stopped, and which task it still holds."""
        claim = self.board.claims.get(r.name)
        held = [f"You still hold task {claim.task}."] if claim else []
        return " ".join(["You stopped work.", *why, *held])

    def break_off(self, r: Resident, *, going: bool = False) -> str:
        """`r` stops work and leaves its conversation, if it is in them, as going elsewhere
        (`going`) does on its own, except that the work of a duty that runs anywhere goes on with
        it on its way (`Occupation.duty`); what it is told of it, a sentence or nothing."""
        stopped = isinstance(r.base, Work) and not (going and r.occupation.duty == "anywhere")
        if stopped:
            self.stop_work(r)
        left = []
        if r.conversation is not None:
            self.leave_conversation(r)
            left.append("left the conversation")
        if stopped:
            left.append("stopped work")
        return f"You {' and '.join(left)}. " if left else ""

    def earn(self, r: Resident, amount: int, about: str) -> int:
        """`r` is paid `amount` for its work, `about` what for as its statement tells it ("for
        task 3", "in sales"): `town.tax` of it, rounded down to the whole so that no receipt
        pays more than the rate, is withheld into the treasury at once, and the rest stays in its
        purse. Returns the tax."""
        tax = math.floor(Fraction(str(self.config.tax)) * amount)  # the rate as written, exactly
        r.inventory.receive(amount, "earned", about)
        if tax:
            r.inventory.spend(tax, "tax", about)
            self.treasury.take("tax", tax)
        return tax

    # Going and arriving -----------------------------------------------------------------------

    def travel_minutes(self, r: Resident, a: str, b: str) -> int:
        """How long `r` takes from `a` to `b`: the walk, shortened by what it owns for travel."""
        factor = min(
            (
                item.factor
                for item in self.config.items
                if item.factor is not None and r.inventory.units(item.id)
            ),
            default=1.0,
        )
        return math.ceil(self.config.travel(a, b) * factor)

    def move_in(self, r: Resident, place_id: str) -> str:
        """`r`, at the home `place_id`, moves into it, giving up its old room; those at the
        place are told. Returns what `r` reads."""
        old, home = self.config.place(r.home), self.config.place(place_id)
        assert home.rent is not None
        r.home = place_id
        witnesses = self.addressable(r)
        self.record(
            "move_in",
            lambda w: f"{cap(you(r.name, w))} moved into {home.name}.",
            actor=r,
            audience=witnesses,
            payload={"from": old.id, "to": home.id, "rent": home.rent},
        )
        return (
            f"You moved into {home.name}; your room at {old.name} is given up. From the next "
            f"midnight your rent is {self.config.money(home.rent)} a day."
        )

    def depart(self, r: Resident, place: str) -> int:
        """Set `r` off from where it is to `place`; returns the time of arrival."""
        assert r.place is not None
        origin = r.place
        arrival = self.clock.now() + self.travel_minutes(r, origin, place) * 60
        witnesses = self.addressable(r)
        self.reckon(r)
        r.base, r.place = Movement(place, arrival, isinstance(r.base, Work)), None
        origin_name, place_name = self.config.place(origin).name, self.config.place(place).name
        self.record(
            "depart",
            lambda w: f"{cap(you(r.name, w))} left {origin_name} for {place_name}.",
            actor=r,
            place=origin,
            audience=witnesses,
            payload={"from": origin, "to": place, "arrival": arrival},
        )
        r.timer = self.at(arrival, partial(self._arrive, r))
        return arrival

    def _arrive(self, r: Resident) -> None:
        assert isinstance(r.base, Movement)
        self.reckon(r)
        r.timer = None
        place, working = r.base.destination, r.base.working
        r.place, r.base = place, Work() if working else Idle()
        others = self.addressable(r)
        name = self.config.place(place).name
        here = world.situation.people_here(self, r)
        seen = f", {appears}" if (appears := world.situation.appears(self, r)) else ""
        self.record(
            "arrive",
            lambda w: (
                f"You arrived at {name}. {here}"
                if w == r.name
                else f"{r.name} arrived at {name}{seen}."
            ),
            actor=r,
            audience=[r, *others],
            payload={"place": place, "working": working},
        )

    # Conversations ----------------------------------------------------------------------------

    def converse(self, speaker: Resident, recipients: list[Resident]) -> Conversation:
        """The conversation `speaker` speaks in, with it and `recipients` in it: the one held
        at its place."""
        assert speaker.place is not None
        conversation = self._rooms.get(speaker.place)
        if conversation is None:
            conversation = Conversation(speaker.place, set(), self.clock.now())
            self._rooms[speaker.place] = conversation
        for r in (speaker, *recipients):
            if r.conversation is not conversation:
                r.conversation = conversation
                conversation.members.add(r.name)
        conversation.last_speech = self.clock.now()
        self._arm_silence(conversation)
        return conversation

    def _arm_silence(self, conversation: Conversation) -> None:
        if conversation.silence is not None:
            conversation.silence.cancel()
        minutes = self.config.social.silence_minutes
        conversation.silence = self.at(
            conversation.last_speech + minutes * 60, partial(self._end, conversation, minutes)
        )

    def leave_conversation(self, r: Resident) -> None:
        """`r` leaves its conversation, back to work if it was at work; the others are told so
        and at what time, since they may read it some time later."""
        conversation = r.conversation
        assert conversation is not None
        conversation.members.discard(r.name)
        r.conversation = None
        rest = [self.residents[name] for name in sorted(conversation.members)]
        hour = clock_time(self.clock.now())
        left = "went back to work" if isinstance(r.base, Work) else "left the conversation"
        self.record(
            "leave_conversation",
            lambda w: f"At {hour} {you(r.name, w)} {left}.",
            actor=r,
            audience=rest,
        )
        if len(conversation.members) < 2:
            self._end(conversation)

    def _end(self, conversation: Conversation, silent: int | None = None) -> None:
        """End `conversation`, after `silent` minutes in which nobody spoke, or because too few
        are left in it, telling those left when."""
        if silent is not None and any(self.clock.is_busy(n) for n in conversation.members):
            # Someone is still composing an answer: that is not silence. Look again shortly.
            conversation.silence = self.at(
                self.clock.now() + 60, partial(self._end, conversation, silent)
            )
            return
        ended = f"at {clock_time(self.clock.now())} the conversation ended."
        if silent is not None:
            ended = f"Nobody spoke for {counted(silent, 'minute')}; {ended}"
        text = cap(ended)
        members = [self.residents[name] for name in sorted(conversation.members)]
        for r in members:
            r.conversation = None
        conversation.members.clear()
        if conversation.silence is not None:
            conversation.silence.cancel()
        del self._rooms[conversation.place]
        if members:
            self.record(
                "conversation_end",
                lambda w: text,
                place=conversation.place,
                audience=members,
                payload={"room": conversation.place},
            )

    # What a resident can do -------------------------------------------------------------------

    def usable(self, r: Resident) -> list[ToolSpec]:
        """The tools `r`'s event offers at its place now, in declared order and as its
        occupation declares them, less those of no use to it there: the work of other
        occupations; its own away from its workplace, where the board hangs and the machines
        are, the counter, the kitchen, the surgery or the Hall's board, except the doctor's at the
        bedside of one too ill to get up; the task's without a task; `start_work` where it has no
        work; and `message` with nothing to write with."""
        if r.suspended:
            return []
        own = OCCUPATIONS[r.occupation.id].work
        useless = set(WORK_DONE - own)
        if r.place != r.occupation.workplace:
            useless |= own - (BEDSIDE if self.bedside(r) else frozenset())
            useless.add("start_work")
        if r.name not in self.board.claims:
            useless |= TASK_TOOLS
        if not any(r.inventory.units(i.id) for i in self.config.items if i.effect == "messaging"):
            useless.add("message")
        specs = self._specs[r.occupation.id]
        return [spec for name, spec in specs.items() if name in r.tools - useless]

    def bedside(self, r: Resident) -> list[Resident]:
        """Those lying in bed, awake, too ill to get up, at the home where `r` is."""
        if r.place is None or self.config.place(r.place).kind != "home":
            return []
        return [o for o in self.addressable(r) if o.living.bedridden]

    def knows(self, r: Resident, name: str) -> bool:
        """Whether `name` is one of the town's tools as `r`'s occupation has them, whether or not
        it can use it now."""
        return name in self._specs[r.occupation.id]

    async def call(self, r: Resident, name: str, args: dict[str, Any]) -> ToolResult:
        """Carry out the tool `name` (`knows`) for `r`, whether or not its last request declared
        it: refused, naming the condition, when `r` is asleep, when its event does not offer it
        (`refusal`), when it is another occupation's work or its arguments do not fit; in a
        conversation, what the conversation does not offer of its own leaves it first."""
        handler = HANDLERS[name]
        if r.suspended:
            return ToolResult("You are asleep.", ends_turn=True)
        if name not in r.tools:
            base = r.base
            destination = (
                self.config.place(base.destination).name if isinstance(base, Movement) else ""
            )
            text = refusal(base, name, destination=destination)
            return ToolResult(text, ends_turn=isinstance(base, Movement))
        if name in WORK_DONE - OCCUPATIONS[r.occupation.id].work:
            return ToolResult(f"That is not your work: you are {r.occupation.title}.")
        problem = tools.check(self._specs[r.occupation.id][name], args)
        if problem:
            return ToolResult(problem)
        if r.conversation is None or name in CONVERSATION_TOOLS:
            return await handler(self, r, args)
        working = isinstance(r.base, Work)
        self.leave_conversation(r)
        result = await handler(self, r, args)
        left = "You went back to work." if working else "You left the conversation."
        return ToolResult(f"{left} {result.text}", result.ends_turn)
