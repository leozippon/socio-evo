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
resident's food and health are reckoned and illness comes or passes, its wages are paid with its
rent and daily charges taken out of them, with a statement, the clients withdraw the tasks whose
time has run out, the portions the kitchen did not sell are gone and the next day's arrivals are
drawn; the forced sleep; and the checkpoint. Every hour on the hour, besides, the bodies are
brought up to date (see below). No place keeps hours, and residents go to bed and wake when they
choose, except that one sleep lasts at most a configured span and that nobody wakes between the
forced sleep and the checkpoint. At the checkpoint the world waits until every resident is asleep
and its runtime waits on its port, holds the clock, closes every workspace keeping its changes,
takes the snapshot and awaits `on_checkpoint(day, snapshot)`, through which the composition layer
writes the checkpoint and commits the agent directories. A lived day N runs from the checkpoint on
calendar day N to the one on calendar day N + 1; the journal, the acceptance runs and the record
`review_day` tells belong to it.

A resident's living (`Living`, of `world.body`) is what it has eaten since the last midnight and
its body's three needs; its inventory (`Inventory`, of `world.economy`) is its money and the items
it keeps, which act through it. Every unit of an item is held by one holder: a resident, a place
(what is left there for anyone, and at the Store and the Restaurant what the business keeps there:
the shelves, the larder and the portions) or the supplier outside the town; `move` is the only way
units change hands, and the one place that enforces presence: the resident who moves them is at the
place of every holder that is a place's, and any other resident it moves them to or from is awake
there with it (`reach`). The town's fund (`Fund`) takes in what clients pay for tasks accepted, the
rent, the Store's sales, the dishes served and the Hospital's fees, pays the supplier for the
Store's orders, and pays each resident at once a sum for each service and, at midnight, its wages
for its time on duty (`on_duty`: at work, which it sits down to at its own workplace, or on its way
at work for the mayor, whose duty runs anywhere; `Resident.worked`, counted as the body is reckoned
and cleared at midnight), with its rent and daily charges taken out of them. The daybook
(`Daybook`) keeps the days the mayor's `report` tells, with the fund's (`fund_report`), the
Office's, the Store's, the kitchen's, the Hospital's and the residents'; the mayor's announcements
stand on the Town Hall's board.

The Store (`Store`) sells while its shopkeeper is at work there (`serving`): a sale moves the price
to the fund and the units off its shelves and pays the shopkeeper its sum, and when the chef buys
for the kitchen, the fund pays and the units are sent to the kitchen's larder; the shopkeeper's
orders are paid to the supplier at once and the supplier's units come onto the shelves at the next
morning's delivery. The Restaurant's kitchen (`Kitchen`) serves while its chef is at work there:
the chef cooks portions from the larder, a portion bought, or handed over by the chef, is eaten at
once, and what perishes is gone at midnight, wherever it is. The Hospital's surgery is open while
its doctor is at work there, at the fees of `fees`. At each place the situation tells what is left
there, what is for sale and at what price, and the keeper of a business what it holds.

The body (`Body`) is reckoned lazily and exactly: `reckon` brings a resident up to the moment at
the rates of what it has been doing since it was last reckoned, and is called every hour on the
hour, before every change of activity (sitting down to work, setting off, arriving, going to bed,
falling asleep, waking) and at the checkpoint, so that a checkpoint carries the body as of its
moment. A resident awake and able to eat eats the ready food in its inventory, a helping at a time,
as it is reckoned; a dish is eaten as it is served. A resident the reckoning finds at work in the
lowest band of energy stops work, as `leave_work` stops it, keeping its task, and is told that it
cannot work until it has slept; before an action in its workspace the body is reckoned too, so that
the exhausted are refused it (`tools`). A need that crosses into another band is logged, and told
to the resident when it is awake at a place (the wake-up, the statement and a purchase's result
tell it otherwise); the situation names the needs in their lowest band. At midnight health moves by
the day, a resident not ill may fall ill, by a chance drawn from the run's seed, the day and its
name, and one ill for its nights is well again; a resident whose health has reached its floor takes
to its bed: it leaves what it was in, is carried home if it was elsewhere, and is in the event
Bedridden, where it can do little but speak to whoever comes and eat what it is given, until
treatment (`treat`) lets it up; those where it was and at its home are told, and a checkpoint keeps
it so. A durable with the effect travel shortens the owner's journeys, one with messaging lets it
write to other owners, and one with appearance shows its phrase wherever others perceive the owner:
who is here, who arrived, whom one is in conversation with; a low band of health shows the same
way. Rent is the home's, and a resident may move into a home with a free room.

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
import random
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from functools import partial
from pathlib import Path
from types import EllipsisType
from typing import Any

from agent.port import Percept, ToolResult, ToolSpec
from infrastructure.storage import RunDirectory
from world import tools
from world.backend import Backend
from world.board import Board
from world.body import Activity, Body, Living
from world.clock import (
    DAY,
    Clock,
    ManualClock,
    calendar_day,
    clock_time,
    parse_hour,
    tell_date,
    tell_moment,
)
from world.config import A_DAYS_FOOD, Band, Item, Occupation, Place, TownConfig
from world.economy import (
    LARDER,
    PAID,
    PORTIONS,
    SHELVES,
    SUPPLIER,
    TAKEN,
    Daybook,
    Fund,
    Holder,
    Inventory,
    Kitchen,
    Settled,
    Store,
    Supplier,
    add,
    money,
)
from world.events import (
    BEDSIDE,
    CONVERSATION_TOOLS,
    EXHAUSTED,
    OCCUPATION_TOOLS,
    TALK,
    TASK_TOOLS,
    WORK_DONE,
    Base,
    Bedridden,
    Conversation,
    Idle,
    Movement,
    Sleep,
    Work,
    refusal,
)
from world.log import Entry, WorldLog
from world.rules import Rules, amount, bare, longest_sleep
from world.telling import cap, counted, duration, listed, you

Tell = Callable[[str | None], str]
"""A text as told to a witness (None: to nobody in particular)."""
OnCheckpoint = Callable[[int, dict[str, Any]], Awaitable[None]]
MOVES = {
    "service": "received {money} for {about}",
    "received": "received {money} from {about}",
    "gave": "gave {money} to {about}",
    "bought": "bought {about} for {money}",
    "paid": "paid {money} for {about}",
}
"""How the statement tells each kind of movement of an inventory's money (`Inventory.moves`)."""


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
    spent on duty since the last midnight (`World.on_duty`), which its wages are paid for; `day`
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
        self._forced = parse_hour(config.day.forced_sleep)
        self._forced_wake = parse_hour(config.day.forced_wake)
        self._delivery = parse_hour(config.day.delivery)
        self._checkpoint_hour = parse_hour(config.day.checkpoint)
        self._longest = parse_hour(config.day.sleep_at_most)
        start = self._checkpoint_hour
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
        self.money: Callable[[int], str] = partial(money, config.currency)
        self.fund = Fund(config.fund.start)
        self.store = Store({item.id: item.price for item in config.supplied})
        self.kitchen = Kitchen({dish.id: dish.price for dish in config.dishes})
        self.holders: dict[str, Holder] = {place.id: Holder() for place in config.places}
        """Every holder of items but the residents, by name (see `holder`)."""
        self.holders |= {
            SHELVES: Holder(dict(config.store.stock)),
            LARDER: Holder(),
            PORTIONS: Holder(),
            SUPPLIER: Supplier(),
        }
        hospital = config.hospital
        self.fees = {"examination": hospital.examination, "treatment": hospital.treatment}
        self.announcements: list[list[int | str]] = []
        """The mayor's announcements standing on the Town Hall's board, each `[time, text]`."""
        self.daybook = Daybook()
        self.board = Board(
            tasks, backend, config.work, seed=config.seed, names=names, money=self.money
        )
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
            self._put_to_sleep(r, self._forced_wake, suspended=True)

    @property
    def ports(self) -> dict[str, ResidentPort]:
        return {name: r.port for name, r in self.residents.items()}

    def lived_day(self) -> int:
        """The day being lived: from one checkpoint to the next."""
        return (self.clock.now() - self._checkpoint_hour) // DAY + 1

    # The schedule ---------------------------------------------------------------------------

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

    def _at(self, t: int, fn: Callable[[], Any]) -> _Timer:
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
            self._at(t, partial(self._arrival, t))
        self._at((day - 1) * DAY + self._delivery, self._deliver)
        self._at(day * DAY, partial(self._midnight, day))
        self._at(day * DAY + self._forced, partial(self._force_sleep, day))
        self._at(day * DAY + self._checkpoint_hour, partial(self._checkpoint, day))

    def _arrival(self, t: int) -> None:
        """A client's task, due at `t`, comes in on the Office's board: told to those there."""
        self.board.schedule.remove(t)
        number = self.board.arrive(calendar_day(t))
        task = self.board.task(number)
        office = self.config.workplace("office")
        here = [r for r in self.residents.values() if r.place == office.id and r.awake]
        hour = clock_time(t)
        self.record(
            "task_arrived",
            lambda w: f"It is {hour}: task {number} ({task.repo}) came in on the board.",
            place=office.id,
            audience=here,
            payload={"task": number, "instance_id": task.instance_id, "repo": task.repo},
        )

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
            audience=self.of_occupation("shopkeeper"),
            payload={"items": came},
        )

    def _hourly(self) -> None:
        """Every hour on the hour, every resident's body is brought up to it; the first call,
        as the world starts to run, only arms the next hour."""
        for r in self.residents.values():
            self.reckon(r)
        now = self.clock.now()
        self._at(now - now % 3600 + 3600, self._hourly)

    def _midnight(self, day: int) -> None:
        """The end of calendar day `day`: its food, its health and illness reckoned, its wages
        paid with the rent and charges taken out of them, the tasks whose time runs out with it
        withdrawn, what perishes gone wherever it is (the portions the kitchen did not sell), and
        the next day's arrivals drawn."""
        self._settle(day)
        self._withdraw(day)
        for key in [*self.residents, *self.holders]:
            held = self.holder(key).items
            for item in [item for item in held if self.config.item(item).perishes]:
                self.moved(self.move(item, held[item], key, None))
        self.board.schedule = self.board.draw(day + 1)

    def _withdraw(self, day: int) -> None:
        """The clients withdraw the tasks not accepted in time, told to whoever held each."""
        office = self.config.workplace("office").id
        for number, holder in self.board.withdraw(day):
            held = [self.residents[holder]] if holder is not None else []
            self.record(
                "task_withdrawn",
                lambda w, number=number, holder=holder: (
                    f"At midnight the client withdrew task {number}, which you held; its "
                    "workspace is gone."
                    if w is not None and w == holder
                    else f"At midnight the client withdrew task {number}."
                ),
                place=office,
                audience=held,
                payload={"task": number, "holder": holder},
            )

    def _settle(self, day: int) -> None:
        """Midnight for every resident, in the configuration's order: its body is brought up to
        the hour and its health moves by the day (a resident whose health has reached its floor
        takes to its bed here), its illness passes or comes (`_illness`), the day's food is
        reckoned, its wages for its time at work are paid with its rent and daily charges taken
        out of them (`Fund.settle`: when the fund runs short, those settled first are paid first),
        and the statement is told, the team leader's with the Office's day (`_office_told`); then
        the fund's day and the daybook's are closed."""
        date = tell_date(day, self.config.start_date)
        hours: dict[str, int] = {}
        for r in self.residents.values():
            self.reckon(r)
            living, inventory = r.living, r.inventory
            home = self.config.place(r.home)
            assert home.rent is not None and home.comfort is not None
            before = self.body.bands(living)
            was_ill = living.ill
            night = self.body.night(living, home.comfort)
            if living.health <= 0 and not living.bedridden:
                self._take_to_bed(r, day)
            illness = self._illness(r, day, was_ill, home.comfort)
            self.note_bands(r, before, tell=False)
            stock = []
            for item in self.config.items:
                if item.dish or not item.ready or not living.eaten.get(item.id):
                    continue
                assert item.nourishment
                left = inventory.units(item.id)
                if not left:
                    stock.append(f"You have used up your {bare(item.name)}.")
                elif left * item.nourishment < A_DAYS_FOOD:  # less than a day's food
                    stock.append(f"You have {amount(item, left)} left.")
            unsold = self.held_told(self.holders[PORTIONS].items)
            if r.occupation.id == "chef" and unsold:
                stock.append(f"What the kitchen did not sell is gone: {listed(unsold)}.")
            charged = [i for i in self.config.items if i.fee_per_day and inventory.units(i.id)]
            wages = r.worked * r.occupation.wage_per_hour // 3600
            charges = sum(item.fee_per_day for item in charged)
            settled = self.fund.settle(r.name, wages, home.rent, charges)
            held = inventory.money
            inventory.money += settled.paid
            self.record(
                "wage",
                lambda w, r=r, held=held, paid=settled.paid: (
                    f"At midnight your purse held {self.money(held)}"
                    + (
                        f", and {self.money(paid)} of your wages went into it."
                        if paid
                        else "; none of your wages went into it."
                    )
                    if w == r.name
                    else f"{r.name} was paid {self.money(paid) if paid else 'nothing'} at midnight."
                ),
                actor=r,
                place=None,
                payload={
                    "hours": round(r.worked / 3600, 2),
                    **asdict(settled),
                    "money": inventory.money,
                },
            )
            nourishment = self.nourishment(r)
            eaten = [self._eaten(item, units) for item, units in living.eaten.items()]
            food = (
                f"You ate today: {listed(eaten)}."
                if nourishment
                else "You had nothing to eat today."
            )
            moves = self._moves_told(inventory)
            items = moves + self._wages_told(r, settled, home, charged)
            office = [self._office_told(r, day)] if r.occupation.id == "team-leader" else []
            statement = " ".join(
                [f"Your statement for {date}: {'; '.join(items)}.", food, *stock]
                + ([illness] if illness else [])
                + [self.body.condition(living), self.purse(r), *office]
            )
            self.record(
                "settlement",
                lambda w, r=r, statement=statement: (
                    statement if w == r.name else f"{r.name} was told the midnight statement."
                ),
                actor=r,
                place=None,
                audience=[r],
                payload={
                    "nourishment": nourishment,
                    "satiety": round(living.satiety, 1),
                    "energy": round(living.energy, 1),
                    "health": round(living.health, 1),
                    "night": night,
                    "ill": living.ill,
                },
            )
            hours[r.name] = r.worked
            living.eaten, inventory.moves, r.worked = {}, [], 0
        self.daybook.close_day(day, hours, self.fund)
        self.fund.close_day()

    def _illness(self, r: Resident, day: int, was_ill: int, comfort: float) -> str | None:
        """`r`'s illness at the midnight that ends calendar day `day`, its night reckoned: one
        ill before it (`was_ill`) whose nights are over is well again; one well, with health
        left, falls ill by the chance of its health and its home (of `comfort`), drawn from the
        run's seed, the day and its name. Logged, told by the statement: what it tells, if
        anything."""
        living = r.living
        if was_ill:
            if living.ill:
                return None
            self.record(
                "recovered",
                lambda w: "Your illness has passed." if w == r.name else f"{r.name} is well again.",
                actor=r,
                place=None,
                payload={
                    "illness": True,
                    "bedridden": False,
                    "treated": False,
                    "health": round(living.health, 1),
                },
            )
            return "Your illness has passed."
        if living.bedridden:
            return None
        chance = self.body.illness_chance(living, comfort)
        if random.Random(f"{self.config.seed}:illness:{day}:{r.name}").random() >= chance:
            return None
        self.body.fall_ill(living)
        self.record(
            "illness",
            lambda w: "You have fallen ill." if w == r.name else f"{r.name} fell ill.",
            actor=r,
            place=None,
            payload={
                "chance": round(chance, 4),
                "nights": living.ill,
                "health": round(living.health, 1),
            },
        )
        return "You have fallen ill."

    def _eaten(self, item: str, units: int) -> str:
        """`units` of the ready food or the dish `item`, as the statement tells what was eaten."""
        return amount(self.config.item(item), units)

    def _moves_told(self, inventory: Inventory) -> list[str]:
        """The statement's items on the movements of `inventory`'s money since the last midnight,
        in their order, the same movement told once with how many times it was made."""
        times: dict[tuple[str, int, str], int] = {}
        for kind, paid, about in inventory.moves:
            key = (str(kind), int(paid), str(about))
            times[key] = times.get(key, 0) + 1
        return [
            MOVES[kind].format(money=self.money(paid), about=about)
            + (f", {n} times" if n > 1 else "")
            for (kind, paid, about), n in times.items()
        ]

    def _wages_told(
        self, r: Resident, settled: Settled, home: Place, charged: list[Item]
    ) -> list[str]:
        """The statement's items on `r`'s wages as `settled` at midnight: its time at work and
        what it earned, what the fund owed it, the rent for its room at `home`, the daily
        charges on the items `charged` and the rent it owed, and what came of them."""
        worked = duration(r.worked)
        money = self.money
        items = [
            f"{worked} at work, {money(settled.wages)} in wages" if worked else "no time at work"
        ]
        if settled.owed_before:
            items.append(f"{money(settled.owed_before)} the fund owed you")
        items.append(f"rent for your room at {home.name} {money(settled.rent)}")
        items += [f"the daily charge on {item.name} {money(item.fee_per_day)}" for item in charged]
        if settled.arrears_before:
            items.append(f"{money(settled.arrears_before)} of rent you owed")
        left, paid = settled.remainder, settled.paid
        if left < 0:
            items.append(
                f"your wages fell {money(-left)} short of that; you owe it, and it is taken from "
                "your next wages"
            )
        elif not left:
            items.append("nothing left of your wages")
        elif paid == left:
            items.append(f"{money(left)} left of your wages, paid into your purse")
        elif paid:
            items.append(
                f"{money(left)} left of your wages, of which {money(paid)} paid into your purse; "
                f"the fund could not pay the other {money(settled.owed)} and owes it to you"
            )
        else:
            items.append(
                f"{money(left)} left of your wages, which the fund could not pay and owes you"
            )
        return items

    def _office_told(self, r: Resident, day: int) -> str:
        """The Office's day, as the team leader `r`'s statement tells it at the midnight that
        ends calendar day `day`, before the clients withdraw what is out of time: the tasks
        accepted that day and by whom (the daybook's), those the clients withdraw at this
        midnight and who held them, and the tasks left open on the board, with those that came
        in that day and who holds each."""
        board = self.board
        accepted = [
            f"task {task} by {you(name, r.name)}" for name, task in self.daybook.today["accepted"]
        ]
        withdrawn, left = [], []
        for number in sorted(board.open):
            holder = board.holder(number)
            if board.withdrawn_on(number) <= day:
                held = f", which {you(holder, r.name)} held" if holder is not None else ""
                withdrawn.append(f"task {number}{held}")
                continue
            came = ", which came in today" if board.open[number] == day else ""
            held = f"held by {you(holder, r.name)}" if holder is not None else "held by nobody"
            left.append(f"task {number} ({board.task(number).repo}){came}, {held}")
        told = [
            f"{cap(self.config.workplace('office').name)} today. Accepted: "
            f"{listed(accepted) or 'none'}."
        ]
        if withdrawn:
            told.append(f"Withdrawn by the clients at midnight: {'; '.join(withdrawn)}.")
        told.append(f"Open on the board: {'; '.join(left) or 'nothing'}.")
        return " ".join(told)

    def _take_to_bed(self, r: Resident, day: int) -> None:
        """`r`'s health has reached its floor at the midnight that ends calendar day `day`: it
        takes to its bed at home, carried there if it was elsewhere, and keeps to it until
        treated. It leaves its conversation and its work and keeps its task; one in bed or
        asleep already is bedridden on waking. It is told, and so are those where it was and
        those at its home."""
        r.living.bedridden = True
        origin = r.place
        witnesses = self.addressable(r)
        self.break_off(r)
        carried = False
        if not isinstance(r.base, Sleep):
            if r.timer is not None:  # on the road: the arrival never comes
                r.timer.cancel()
                r.timer = None
            carried = origin != r.home
            r.place, r.base = r.home, Bedridden()
            witnesses += [other for other in self.addressable(r) if other not in witnesses]
        how = "were carried home to bed" if carried else "took to your bed"
        told = f"You are too ill to go on: you {how}, and keep to it until you are treated."
        seen = (
            f"{r.name} was carried home to bed, too ill to go on."
            if carried
            else f"{r.name} took to bed, too ill to go on."
        )
        claim = self.board.claims.get(r.name)
        self.record(
            "bedridden",
            lambda w: told if w == r.name else seen,
            actor=r,
            place=r.home,
            audience=[r, *witnesses],
            payload={
                "day": day,
                "home": r.home,
                "from": origin,
                "carried": carried,
                "task": claim.task if claim else None,
            },
        )

    def treat(self, r: Resident, restores: float) -> None:
        """Treatment restores `restores` of `r`'s health, ends its illness and, if `r` was
        bedridden, lets it up, Idle at its home; either is logged as `recovered`, told to it
        and, out of bed, to those there. The doctor's treatment, at the Hospital or at a
        patient's bedside, calls this."""
        self.reckon(r)
        ill, bedridden = bool(r.living.ill), r.living.bedridden
        self.body.treat(r.living, restores)
        r.living.bedridden = False
        if isinstance(r.base, Bedridden):
            r.base = Idle()
        if not (ill or bedridden):
            return
        self.record(
            "recovered",
            lambda w: (
                (
                    "You are well enough to leave your bed."
                    if w == r.name
                    else f"{r.name} is well enough to get up."
                )
                if bedridden
                else ("Your illness is over." if w == r.name else f"{r.name} is well again.")
            ),
            actor=r,
            audience=[r, *self.addressable(r)] if bedridden else [r],
            payload={
                "illness": ill,
                "bedridden": bedridden,
                "treated": True,
                "health": round(r.living.health, 1),
            },
        )

    # The body ---------------------------------------------------------------------------------

    def reckon(self, r: Resident) -> None:
        """Bring `r`'s body up to the moment at the rates of what it has been doing since it was
        last reckoned, counting its time on duty towards its wages, let it eat from its stock if
        it is awake and could eat, and note each need that crossed into another band, telling `r`
        if it is awake at a place; if `r` is at work and exhausted, its work stops."""
        now = self.clock.now()
        before = self.body.bands(r.living)
        home = self.config.place(r.home)
        assert home.comfort is not None
        self.body.elapse(r.living, now - r.reckoned, self.activity(r), home.comfort)
        if self.on_duty(r):
            r.worked += now - r.reckoned
        r.reckoned = now
        self.feed(r)
        self.note_bands(r, before, tell=r.awake and r.place is not None)
        if isinstance(r.base, Work) and self.body.lowest("energy", r.living.energy):
            self._exhausted(r)

    def _exhausted(self, r: Resident) -> None:
        """`r`, found exhausted at work, stops work as `leave_work` stops it and is told that it
        cannot work until it has slept, and which task it still holds."""
        r.base = Idle()
        claim = self.board.claims.get(r.name)
        held = f" You still hold task {claim.task}." if claim else ""
        self.record(
            "leave_work",
            lambda w: (
                f"You stopped work. {EXHAUSTED}{held}"
                if w == r.name
                else f"{r.name} stopped work, exhausted."
            ),
            actor=r,
            audience=[r],
        )

    @staticmethod
    def on_duty(r: Resident) -> bool:
        """Whether `r`'s hours at work are running: at work, which one enters only at one's own
        workplace and, unless one's duty runs anywhere (`Occupation.duty`), leaves by leaving it;
        or on one's way at work, the duty running."""
        return isinstance(r.base, Work) or (isinstance(r.base, Movement) and r.base.working)

    def activity(self, r: Resident) -> Activity:
        """What `r`'s body is doing now, for the rates of the hours."""
        if isinstance(r.base, Work):
            return "work"
        if isinstance(r.base, Movement):
            return "walk"
        if r.suspended:
            return "sleep"
        return "awake"

    def feed(self, r: Resident) -> None:
        """Awake and able to eat, `r` eats the ready food in its inventory, a helping at a time,
        until it could eat no more."""
        if not r.awake:
            return
        for item in self.config.items:
            while item.ready and self.body.hungry(r.living) and r.inventory.units(item.id):
                self.eat(r, item.id, 1)

    def note_bands(self, r: Resident, before: dict[str, Band], *, tell: bool) -> None:
        """Log each need of `r` whose band is no longer `before`'s, in the band's words, and
        tell `r` so if `tell` (a result, the wake-up or the statement tells it otherwise)."""
        for name, band in self.body.bands(r.living).items():
            if band is before[name]:
                continue
            self.record(
                "condition",
                lambda w, band=band: (
                    f"You are {band.name}." if w == r.name else f"{r.name} is {band.name}."
                ),
                actor=r,
                audience=[r] if tell else [],
                payload={
                    "need": name,
                    "band": band.name,
                    "value": round(getattr(r.living, name), 1),
                    "lowest": band is self.body.need(name).lowest,
                },
            )

    def nourishment(self, r: Resident) -> int:
        """What `r` has eaten since the last midnight, as nourishment: the one measure of
        whether it has eaten today."""
        return sum(self._food(item) * units for item, units in r.living.eaten.items())

    def _food(self, item: str) -> int:
        """What a helping of the ready food `item`, or a portion of the dish `item`, gives."""
        nourishment = self.config.item(item).nourishment
        assert nourishment
        return nourishment

    def eat(self, r: Resident, item: str, units: int = 1) -> None:
        """`r` eats `units` of the ready food or the dish `item` it holds: they go out of its
        inventory into nothing, today's record grows and its satiety rises. Logged; told to
        nobody, since a result or the statement tells it."""
        self.moved(self.move(item, units, r.name, None, by=r))
        r.living.eaten[item] = r.living.eaten.get(item, 0) + units
        self.body.eat(r.living, self._food(item) * units)
        eaten = amount(self.config.item(item), units)
        self.record_move(
            "eat",
            lambda w: f"{cap(you(r.name, w))} ate {eaten}.",
            by=r,
            item=item,
            units=units,
            source=r.name,
        )

    # Items and their holders ----------------------------------------------------------------

    def holder(self, key: str) -> Holder:
        """The holder named `key`: a resident by its name, what is left at a place by the place's
        id, or `SHELVES`, `LARDER`, `PORTIONS` or `SUPPLIER`."""
        r = self.residents.get(key)
        return r.inventory if r is not None else self.holders[key]

    def where(self, key: str) -> str | None:
        """The place of the holder `key`, which is no resident: a place's own, the Store's for its
        shelves, the Restaurant's for the larder and the portions; none for the supplier."""
        if key == SHELVES:
            return self.config.workplace("store").id
        if key in (LARDER, PORTIONS):
            return self.config.workplace("restaurant").id
        return None if key == SUPPLIER else key

    def reach(self, by: Resident, key: str) -> str | None:
        """Why `by` cannot move units from or to the holder `key`, or None if it can: a place's
        holder it reaches at that place, another resident only awake at its own place."""
        other = self.residents.get(key)
        if other is not None:
            if other is by:
                return None
            if not self.visible(by, other):
                return f"{other.name} is not here."
            return None if other.awake else f"{other.name} is asleep."
        place = self.where(key)
        if place is not None and place != by.place:
            return f"You are not at {self.config.place(place).name}."
        return None

    def move(
        self,
        item: str,
        units: int,
        source: str | None,
        target: str | None,
        *,
        by: Resident | None = None,
    ) -> str | None:
        """Move `units` of `item` from the holder `source` to the holder `target` (`holder`):
        the only way units change hands. A `source` of None brings units into being (portions
        cooked); a `target` of None takes them out of it (eaten, cooked with, perished). `by`,
        the resident who moves them, must reach both holders (`reach`); the world's own moves (a
        delivery, what the chef bought sent to the kitchen, midnight) have none. Returns the
        refusal, nothing moved: a holder out of reach, a source that does not hold the units, or
        a resident who would hold more than one of a durable; or None once moved."""
        thing = self.config.item(item)
        for key in (source, target):
            if by is not None and key is not None and (refused := self.reach(by, key)):
                return refused
        if source is not None and (held := self.holder(source).units(item)) < units:
            return self._short(source, thing, held, by)
        if target in self.residents and thing.kind == "durable":
            w = by.name if by is not None else None
            who, verb = cap(you(target, w)), "have" if target == w else "has"
            if self.holder(target).units(item):
                return f"{who} already {verb} {thing.name}."
            if units > 1:
                return f"{who} can have only one {bare(thing.name)}."
        if source is not None:
            self.holder(source).take(item, units)
        if target is not None:
            self.holder(target).add(item, units)
        return None

    @staticmethod
    def moved(refusal: str | None) -> None:
        """A move the world makes of its own, or once its conditions are checked, is never
        refused."""
        if refusal is not None:
            raise RuntimeError(f"a move the world makes was refused: {refusal}")

    def _short(self, source: str, thing: Item, held: int, by: Resident | None) -> str:
        """Why the holder `source`, holding `held` units of `thing`, cannot give more."""
        what = f"only {amount(thing, held)}" if held else f"no {bare(thing.name)}"
        if by is not None and source == by.name:
            return f"You have {what}."
        if source in self.residents:
            return f"{source} has {what}."
        if source == SHELVES:
            return f"{cap(self.config.workplace('store').name)} has {what} left."
        if source == LARDER:
            return f"The kitchen holds {what}."
        if source == PORTIONS:
            return f"The kitchen has {what} ready."
        return f"You find {what} here."

    def record_move(
        self,
        reason: str,
        tell: Tell,
        *,
        by: Resident,
        audience: list[Resident] | tuple[Resident, ...] = (),
        item: str | None = None,
        units: int = 0,
        source: str | None = None,
        target: str | None = None,
        money: int = 0,
        seller: str | None = None,
    ) -> None:
        """Log a move `by` made, told as `tell` to `audience`: `units` of `item` from the holder
        `source` to the holder `target` (None: into or out of nothing), with the `money` that
        went with it, if any, and why (`reason`: get, put, pass, eat or buy); `seller` is who
        was serving at a purchase. Money alone, handed over, has no item."""
        payload = {"item": item, "units": units, "source": source, "target": target}
        payload |= {"money": money, "reason": reason, "seller": seller}
        self.record("move", tell, actor=by, audience=audience, payload=payload)

    def take_in(self, r: Resident, *, tell: bool = False) -> None:
        """`r` has just been handed something: the ready food it could eat is eaten at once, and
        each need that crossed into another band is noted, told to it if `tell` (a result tells
        one who took it itself)."""
        before = self.body.bands(r.living)
        self.feed(r)
        self.note_bands(r, before, tell=tell)

    def served(self, r: Resident, dish: str, units: int = 1) -> None:
        """`r` eats the `units` of `dish` it has just been served, there and then, as a dish is
        eaten; the result or what it is told of the serving tells it."""
        before = self.body.bands(r.living)
        self.eat(r, dish, units)
        self.note_bands(r, before, tell=False)

    def held_told(self, held: dict[str, int]) -> list[str]:
        """The units of each item of `held`, in the catalogue's order, as a sentence names them."""
        return [amount(item, held[item.id]) for item in self.config.items if held.get(item.id)]

    def _force_sleep(self, day: int) -> None:
        wake = day * DAY + self._forced_wake
        hour = clock_time(self.clock.now())
        for r in self.residents.values():
            if isinstance(r.base, Sleep):
                if not r.base.suspended:
                    self._fall_asleep(r, f"It is {hour}: you fell asleep.")
                continue
            if isinstance(r.base, Bedridden):  # in bed already
                self.break_off(r)
                self._put_to_sleep(r, wake)
                self._fall_asleep(r, f"It is {hour}: you fell asleep.")
                continue
            self.break_off(r)
            if r.timer is not None:
                r.timer.cancel()
            again = " again" if self.went_to_bed(r) else ""
            self.record(
                "forced_sleep",
                lambda w, r=r, again=again: (
                    f"It is {hour}: {you(r.name, w)} fell asleep without going to bed{again}, and "
                    f"will wake at home at {clock_time(wake)}."
                ),
                actor=r,
                audience=[r],
                payload={"wake": wake},
            )
            r.place = r.home
            self._put_to_sleep(r, wake)
            self._fall_asleep(r, None)

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
            for name in self.board.runs:
                self.board.runs[name] = {}
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

    # Checkpoints ----------------------------------------------------------------------------

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
            "fund": asdict(self.fund),
            "store": asdict(self.store),
            "kitchen": asdict(self.kitchen),
            "holders": {
                key: dict(holder.items) for key, holder in self.holders.items() if key != SUPPLIER
            },
            "fees": dict(self.fees),
            "announcements": copy.deepcopy(self.announcements),
            "daybook": copy.deepcopy(asdict(self.daybook)),
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
        self.fund = Fund(**copy.deepcopy(state["fund"]))
        self.store = Store(**copy.deepcopy(state["store"]))
        self.kitchen = Kitchen(**copy.deepcopy(state["kitchen"]))
        if set(state["holders"]) != set(self.holders) - {SUPPLIER}:
            raise ValueError("the checkpoint's holders are not the configuration's places'")
        for key, items in state["holders"].items():
            self.holders[key] = Holder(dict(items))
        self.fees = dict(state["fees"])
        self.announcements = copy.deepcopy(state["announcements"])
        self.daybook = Daybook(**copy.deepcopy(state["daybook"]))
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
            # A checkpoint from before the body woke anyone early has no `longest`.
            longest = saved.get("longest", False)
            self._put_to_sleep(r, saved["wake"], suspended=True, longest=longest)
            if saved["claim"] is not None:
                self.board.hold(name, saved["claim"])
            r.port.held = [Percept(**percept) for percept in saved["held"]]
        moment = tell_moment(state["time"], self.config.start_date)
        self.record(
            "resume",
            lambda w: f"The town went back to {moment}.",
            payload={"day": self.lived_day() - 1, "time": state["time"]},
        )

    # Recording and delivering ---------------------------------------------------------------

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

    # Places and people ----------------------------------------------------------------------

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

    def serving(self, kind: str) -> Resident | None:
        """Who is at work at the town's workplace of `kind`, of those whose workplace it is: the
        shopkeeper at the Store's counter, the chef in the kitchen, the doctor in the surgery;
        None while nobody is, and the door is shut."""
        place = self.config.workplace(kind).id
        return next(
            (
                r
                for r in self.residents.values()
                if r.place == place and r.occupation.workplace == place and isinstance(r.base, Work)
            ),
            None,
        )

    def counter_told(self, r: Resident) -> list[str]:
        """What `r` is told where it is of what is for sale there now and at what price, at the
        Store, the Restaurant or the Hospital, or that its door is shut; what the business holds
        is always told to its keeper, open or shut: to the shopkeeper at the Store the shelves
        and what is on order, to the chef the menu with its portions and, there or at the Store,
        what the kitchen holds."""
        store, restaurant = self.config.workplace("store"), self.config.workplace("restaurant")
        hospital = self.config.workplace("hospital")
        told = []
        if r.place == hospital.id:
            if self.serving("hospital") is None:
                told.append("The surgery is closed.")
            else:
                fees = self.fees
                told.append(
                    f"The surgery is open: an examination costs {self.money(fees['examination'])}"
                    f", a treatment {self.money(fees['treatment'])}."
                )
        if r.place == store.id:
            keeper = r.occupation.workplace == store.id
            if self.serving("store") is None:
                told.append(f"{cap(store.name)} is closed: nobody is at the counter.")
                if keeper:
                    told.append(self._counter("On the shelves"))
            else:
                told.append(self._counter())
            if keeper and self.store.pending:
                coming: dict[str, int] = {}
                for item, units, _ in self.store.pending:
                    add(coming, str(item), int(units))
                told.append(f"On order from the supplier: {listed(self.held_told(coming))}.")
        elif r.place == restaurant.id:
            if self.serving("restaurant") is None:
                told.append("The kitchen is closed.")
            if self.serving("restaurant") is not None or r.occupation.workplace == restaurant.id:
                told.append(self._menu())
        if r.occupation.workplace == restaurant.id and r.place in (store.id, restaurant.id):
            told.append(self.kitchen_told())
        return told

    def _counter(self, heading: str = "At the counter") -> str:
        """The Store's shelves: each item it sells, with its price and how many are left, and
        what is sold out."""
        stocked, out = [], []
        shelves = self.holders[SHELVES]
        for item in self.config.supplied:
            left = shelves.units(item.id)
            price = self.money(self.store.prices[item.id])
            if left:
                stocked.append(f"{bare(item.name)} {price} ({left} left)")
            else:
                out.append(bare(item.name))
        told = f"{heading}: {listed(stocked) or 'nothing'}"
        return told + (f"; sold out: {listed(out)}." if out else ".")

    def _menu(self) -> str:
        """The menu: each dish with its price and how many portions are ready."""
        portions = self.holders[PORTIONS]
        menu = [
            f"{bare(dish.name)} {self.money(self.kitchen.menu[dish.id])} "
            f"({portions.units(dish.id) or 'none'} ready)"
            for dish in self.config.dishes
        ]
        return f"On the menu: {listed(menu)}."

    def kitchen_told(self) -> str:
        """What the kitchen's larder holds, as the chef reads it."""
        held = self.held_told(self.holders[LARDER].items)
        return f"The kitchen holds {listed(held)}." if held else "The kitchen holds nothing."

    def left_told(self, r: Resident) -> list[str]:
        """What is left where `r` is for anyone to take, in a sentence, or nothing."""
        assert r.place is not None
        left = self.held_told(self.holders[r.place].items)
        return [f"Left here for anyone to take: {listed(left)}."] if left else []

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

    def appears(self, r: Resident) -> str:
        """How `r` appears to others: the phrases of what it owns that shows and of its health
        where that shows, or nothing."""
        phrases = [
            item.phrase
            for item in self.config.items
            if item.phrase is not None and r.inventory.units(item.id)
        ]
        if (seen := self.body.seen(r.living)) is not None:
            phrases.append(seen)
        return ", ".join(phrases)

    def named(self, r: Resident, *notes: str) -> str:
        """`r` by name, with `notes` and how it appears in brackets: `Mei (working, in a new
        coat)`."""
        noted = [*notes, *([seen] if (seen := self.appears(r)) else [])]
        return f"{r.name} ({', '.join(noted)})" if noted else r.name

    def people_here(self, r: Resident) -> str:
        def state(other: Resident) -> str:
            if not other.awake:
                return f"{other.name} (asleep)"
            notes = []
            if isinstance(other.base, Work):
                notes.append("working")
            elif isinstance(other.base, Bedridden):
                notes.append("in bed")
            if other.conversation is not None:
                notes.append("in a conversation")
            return self.named(other, *notes)

        people = self.company(r)
        if not people:
            return "Nobody else is here."
        return f"Also here: {listed([state(other) for other in people])}."

    def things_told(self, r: Resident) -> str:
        """What `r` owns and keeps, in its own words."""
        things = self.held_told(r.inventory.items)
        return f"You have {listed(things)}." if things else "You have nothing of your own yet."

    def purse(self, r: Resident) -> str:
        """The money `r` has, in its own words."""
        return f"Your purse holds {self.money(r.inventory.money)}."

    def cannot_pay(self, r: Resident, amount: int) -> str | None:
        """Why `r` cannot pay `amount` now, or None if it can."""
        if amount > r.inventory.money:
            return f"You do not have {self.money(amount)}. {self.purse(r)}"
        return None

    def inventory_told(self, r: Resident) -> str:
        """What `r` has, as `inventory` tells it: its money, then each thing it keeps, a line
        each, with how much is left of a stock and any daily charge."""
        lines = [f"Money: {self.money(r.inventory.money)}."]
        for item in self.config.items:
            units = r.inventory.units(item.id)
            if not units:
                continue
            if item.kind == "consumable":
                each = "portion" if item.dish else "helping" if item.ready else "unit"
                lines.append(f"{cap(bare(item.name))}: {counted(units, each)}.")
            elif item.fee_per_day:
                charge = self.money(item.fee_per_day)
                lines.append(f"{cap(item.name)}, with a daily charge of {charge}.")
            else:
                lines.append(f"{cap(item.name)}.")
        return "\n".join(lines)

    def pay_service(
        self,
        r: Resident,
        service: str,
        about: str,
        *,
        due: int | None = None,
        task: int | None = None,
        tell: bool = False,
    ) -> str:
        """`r` is paid a sum for a service rendered, told as being for `about`: its
        occupation's sum unless `due` is given, into its inventory as far as the fund has it, the
        rest owed. `service` names the service in the log: `task`, a task of one's own accepted;
        `team`, one of the programmers' tasks accepted, to the team leader; `sale`; `dish`;
        `patient`, a patient examined or treated. It is
        told to `r` if `tell` (a result tells it otherwise); returns what `r` is told, nothing
        when the sum is nothing."""
        due = r.occupation.per_service if due is None else due
        if not due:
            return ""
        paid = self.fund.service(r.name, due)
        r.inventory.money += paid
        if paid:
            r.inventory.moves.append(["service", paid, about])
        owed = due - paid

        def told(w: str | None) -> str:
            who = cap(you(r.name, w))
            if not owed:
                return f"{who} received {self.money(paid)} for {about}."
            return (
                f"{who} received {self.money(paid)} of the {self.money(due)} for {about}; "
                f"the fund owes {you(r.name, w)} the rest."
            )

        self.record(
            "service",
            told,
            actor=r,
            audience=[r] if tell else [],
            payload={
                "for": service,
                "task": task,
                "amount": due,
                "paid": paid,
                "owed": owed,
                "money": r.inventory.money,
            },
        )
        return told(r.name)

    def report(self) -> str:
        """The town's report, as the mayor reads it at the Town Hall: what the fund holds and its
        day before (`fund_report`); the last seven days the daybook has closed, a line each (the
        fund's balance and how it moved, the tasks accepted, the sales, the dishes served, the
        patients); today so far (the Office's open tasks and who holds them, the Store's shelves
        and the menu, what was accepted, sold, served and seen today); each resident's
        occupation, time at work the day before and health as others see it, whether it is ill
        and whether it is in bed; and the announcements standing. No purse is in it."""
        c, book = self.config, self.daybook
        parts = [f"The town's report, {tell_moment(self.clock.now(), c.start_date)}."]
        parts.append(f"The fund. {self.fund_report()}")
        week = [f"{tell_date(d['day'], c.start_date)}: {self._day_told(d)}" for d in book.days]
        parts.append(
            "The last days, as each closed at midnight:\n" + "\n".join(week)
            if week
            else "No day has closed yet."
        )

        held = {claim.task: name for name, claim in self.board.claims.items()}
        open_tasks = [
            f"task {n} ({self.board.task(n).repo}), "
            + (f"held by {held[n]}" if n in held else "held by nobody")
            for n in sorted(self.board.open)
        ]
        fees = self.fees
        today = [
            f"{cap(c.workplace('office').name)}. Open on the board: "
            f"{'; '.join(open_tasks) or 'nothing'}.",
            f"{cap(c.workplace('store').name)}. {self._counter('In stock')}",
            f"{cap(c.workplace('restaurant').name)}. {self._menu()}",
            f"{cap(c.workplace('hospital').name)}. An examination costs "
            f"{self.money(fees['examination'])}, a treatment {self.money(fees['treatment'])}.",
            f"So far today: {self._day_told(book.today, closed=False)}",
        ]
        parts.append("Today.\n" + "\n".join(today))

        yesterday = book.yesterday
        people = []
        for r in self.residents.values():
            worked = duration(yesterday["hours"].get(r.name, 0))
            line = f"{r.name}, {r.occupation.title}: {worked or 'no time'} at work yesterday"
            if r.living.bedridden:
                line += ", in bed, too ill to get up"
            elif (looks := self.body.seen(r.living)) is not None:
                line += f", {looks}"
            if r.living.ill:
                line += ", ill"
            people.append(line + ".")
        parts.append("The residents. " + " ".join(people))
        parts.append(f"{cap(c.workplace('hall').name)}. {self.hall_board()}")
        return "\n\n".join(parts)

    def _day_told(self, day: dict[str, Any], *, closed: bool = True) -> str:
        """A day of the daybook in a line of the report: for a `closed` day, the fund's balance
        at its midnight and how the day moved it; the tasks accepted, by whom; what the Store
        sold; the dishes served; the patients the doctor saw."""
        money = self.money
        told = []
        if closed:
            net = day["net"]
            moved = f"up {money(net)}" if net > 0 else f"down {money(-net)}" if net < 0 else "even"
            told.append(f"the fund held {money(day['fund'])} at midnight, {moved} on the day")
        accepted = [f"task {task} by {name}" for name, task in day["accepted"]]
        seen: dict[str, list[str]] = {}
        for name, service in day["patients"]:
            seen.setdefault(name, []).append(service)
        patients = [f"{name} ({listed(services)})" for name, services in seen.items()]
        told += [
            f"accepted {listed(accepted) or 'nothing'}",
            f"sold {listed(self.held_told(day['sales'])) or 'nothing'}",
            f"served {listed(self.held_told(day['dishes'])) or 'nothing'}",
            f"{listed(patients) or 'nobody'} seen at {self.config.workplace('hospital').name}",
        ]
        return "; ".join(told) + "."

    def hall_board(self) -> str:
        """The announcements standing on the Town Hall's board, each with when it was made."""
        if not self.announcements:
            return "Nothing is posted on the board."
        lines = [
            f"{tell_moment(int(t), self.config.start_date)}: “{text}”"
            for t, text in self.announcements
        ]
        return "On the board, the mayor's announcements:\n" + "\n".join(lines)

    def fund_report(self) -> str:
        """The fund's day, as the town tells it: what the fund holds, what it took in and paid
        out by kind on the day the last midnight closed, what it owes in wages and who owes it
        rent."""
        fund, money = self.fund, self.money
        day = fund.yesterday
        took = [f"{money(day[kind])} {words}" for kind, words in TAKEN.items() if kind in day]
        paid = [f"{money(day[kind])} {words}" for kind, words in PAID.items() if kind in day]
        parts = [
            f"The fund holds {money(fund.balance)}.",
            f"Yesterday it took in {listed(took) or 'nothing'} and paid out "
            f"{listed(paid) or 'nothing'}.",
        ]
        if fund.owed:
            owed = listed([f"{name} {money(amount)}" for name, amount in fund.owed.items()])
            parts.append(f"It owes in wages it could not pay: {owed}.")
        if fund.arrears:
            owing = listed([f"{name} {money(amount)}" for name, amount in fund.arrears.items()])
            parts.append(f"Owing rent the wages did not cover: {owing}.")
        return " ".join(parts)

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

    def look(self, r: Resident) -> str:
        """What `r` sees looking around: the hour and the place, whose home it is, who is here
        and what each is doing, what is for sale here and what the business holds, as the
        situation tells it, what is left here, and at the Town Hall its board."""
        assert r.place is not None
        place = self.config.place(r.place)
        text = f"It is {clock_time(self.clock.now())}. You are at {place.name}."
        if place.kind == "home":
            homes = [other.name for other in self.occupants(place.id)]
            others = [name for name in homes if name != r.name]
            if r.name in homes:
                text += " It is your home" + (
                    f", which you share with {listed(others)}." if others else "."
                )
            elif homes:
                text += f" It is the home of {listed(homes)}."
        text = " ".join([text, self.people_here(r), *self.counter_told(r), *self.left_told(r)])
        if place.kind == "hall":
            text += f"\n\n{self.hall_board()}"
        return text

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
            f"midnight your rent is {self.money(home.rent)} a day."
        )

    def stop_work(self, r: Resident) -> None:
        """`r` stops work: by its own `leave_work`, by leaving its workplace or going to bed, or
        because the forced sleep takes it, so that every stretch of work in the log ends. The
        body is reckoned first, and may have stopped it already."""
        self.reckon(r)
        if isinstance(r.base, Work):
            r.base = Idle()
            self.record("leave_work", lambda w: f"{cap(you(r.name, w))} stopped work.", actor=r)

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
        r.timer = self._at(arrival, partial(self._arrive, r))
        return arrival

    def _arrive(self, r: Resident) -> None:
        assert isinstance(r.base, Movement)
        self.reckon(r)
        r.timer = None
        place, working = r.base.destination, r.base.working
        r.place, r.base = place, Work() if working else Idle()
        others = self.addressable(r)
        name = self.config.place(place).name
        here = self.people_here(r)
        seen = f", {appears}" if (appears := self.appears(r)) else ""
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

    # Conversations --------------------------------------------------------------------------

    def converse(self, speaker: Resident, recipients: list[Resident]) -> Conversation:
        """The conversation `speaker` speaks in, with it and `recipients` in it: the one held
        at its place."""
        assert speaker.place is not None
        room = speaker.place
        conversation = self._rooms.get(room)
        if conversation is None:
            conversation = Conversation(room, speaker.place, set(), self.clock.now())
            self._rooms[room] = conversation
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
        conversation.silence = self._at(
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
            conversation.silence = self._at(
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
        del self._rooms[conversation.room]
        if members:
            self.record(
                "conversation_end",
                lambda w: text,
                place=conversation.place,
                audience=members,
                payload={"room": conversation.room},
            )

    # Sleep, waking and waiting --------------------------------------------------------------

    def _put_to_sleep(
        self, r: Resident, wake: int, suspended: bool = False, longest: bool = False
    ) -> None:
        """`r` sleeps until `wake`, which replaces any hour it was to wake at before; `longest`
        whether that is when its longest sleep ends, before the hour it gave."""
        self.reckon(r)
        if r.timer is not None:
            r.timer.cancel()
        r.base = Sleep(wake, suspended, longest)
        r.timer = self._at(wake, partial(self._wake_up, r))

    def wake_time(self, hour: int) -> tuple[int, bool]:
        """When a resident who goes to bed now, asking to wake at `hour` (seconds after
        midnight), wakes, and whether its body wakes it before that hour: at the next time the
        clock shows that hour, an hour at or before the present one meaning tomorrow, or when
        the longest sleep ends, if that is sooner. Everyone must be asleep from the forced sleep
        to the checkpoint, so a waking in between becomes the checkpoint's."""
        now = self.clock.now()
        wake = now - now % DAY + hour
        if wake <= now:
            wake += DAY
        longest = wake - now > self._longest
        wake = min(wake, now + self._longest)
        night = self.lived_day() * DAY
        if night + self._forced <= wake < night + self._checkpoint_hour:
            wake = night + self._checkpoint_hour
        return wake, longest

    def went_to_bed(self, r: Resident) -> bool:
        """Whether `r` has gone to bed in the day being lived."""
        return any(kind == "sleep" for _, kind, _, _ in r.day)

    def go_to_bed(self, r: Resident, hour: int, journal: str | None, day: int) -> str:
        """`r` goes to bed, to wake at `hour` (seconds after midnight) or when its longest sleep
        ends, with the day's entry in its journal if it wrote one, and returns what `sleep`
        answers. Going to bed from elsewhere, it is told in bed what it may still do; from bed,
        the answer alone tells the hour it will wake, so that with nothing more to read it falls
        asleep at its next wait."""
        in_bed = isinstance(r.base, Sleep)
        wake, longest = self.wake_time(hour)
        self._put_to_sleep(r, wake, longest=longest)
        until = f"You are in bed and will wake at {clock_time(wake)}"
        if longest:
            until += f", since you cannot sleep longer than {longest_sleep(self.config.day)}"
        kept = "; your journal entry for today is kept" if journal else ""
        parts = [f"{until}{kept}."]
        if not in_bed:
            parts.append(
                "Before you fall asleep you can look back over your day and see to your files; "
                "you fall asleep once you have nothing more to do."
            )
        told = " ".join(parts)
        wrote = " and wrote in the journal" if journal else ""
        self.record(
            "sleep",
            lambda w: told if w == r.name else f"{r.name} went to bed{wrote}.",
            actor=r,
            audience=[] if in_bed else [r],
            payload={"journal": journal, "day": day, "wake": wake},
        )
        return told if in_bed else "You went to bed."

    def fall_asleep(self, r: Resident) -> None:
        """`r`, in bed, has nothing more to do: it falls asleep until its wake-up."""
        self._fall_asleep(r, None)
        self.record(
            "fell_asleep",
            lambda w: f"{cap(you(r.name, w))} fell asleep.",
            actor=r,
            payload={"forced": False},
        )

    def _fall_asleep(self, r: Resident, told: str | None) -> None:
        if told is not None:  # told before the resident is suspended, so that it hears it
            self.record(
                "fell_asleep",
                lambda w: told if w == r.name else f"{r.name} fell asleep.",
                actor=r,
                audience=[r],
                payload={"forced": True},
            )
        assert isinstance(r.base, Sleep)
        self.reckon(r)
        r.base.suspended = True
        r.wait_minutes = None
        self.disarm_tick(r)
        self.rest_changed()

    def _wake_up(self, r: Resident, tell: Tell | None = None) -> None:
        """`r` wakes at home, at its hour, when its longest sleep ends or, told `tell`, woken
        by the town, eats from its stock if it could, and is told what shape it is in."""
        self.reckon(r)
        longest = isinstance(r.base, Sleep) and r.base.longest
        r.timer = None
        r.base, r.place = (Bedridden() if r.living.bedridden else Idle()), r.home
        before = self.body.bands(r.living)
        self.feed(r)
        self.note_bands(r, before, tell=False)
        r.port.release()
        moment = tell_moment(self.clock.now(), self.config.start_date)
        could = " could sleep no longer and" if longest else ""
        woke = tell or (lambda w: f"{cap(you(r.name, w))}{could} woke up at home. It is {moment}.")
        shape = self.body.condition(r.living)
        self.record(
            "wake",
            lambda w: f"{woke(w)} {shape}" if w == r.name else woke(w),
            actor=r,
            audience=[r],
        )
        self.rest_changed()

    def arm_tick(self, r: Resident) -> None:
        """Make sure `r` hears something within its idle interval, or within the minutes it
        asked to wait."""
        asked = r.wait_minutes
        minutes = asked or self.config.clock.idle_minutes
        r.wait_minutes = None
        r.tick = self._at(self.clock.now() + minutes * 60, partial(self._tick, r, asked))

    def disarm_tick(self, r: Resident) -> None:
        if r.tick is not None:
            r.tick.cancel()
            r.tick = None

    def end_wait(self, r: Resident, began: int) -> None:
        """`r`'s wait for the minutes it asked, begun at `began`, was ended sooner by what it
        has just been told: it is told so, and the time, after that."""
        now = self.clock.now()
        text = f"That ended the wait you began at {clock_time(began)}; it is now {clock_time(now)}."
        self.record(
            "time",
            lambda w: text,
            actor=r,
            audience=[r],
            payload={"waited_minutes": (now - began) // 60, "cut_short": True},
        )

    def _tick(self, r: Resident, asked: int | None) -> None:
        r.tick = None
        hour = clock_time(self.clock.now())
        text = (
            f"You waited {counted(asked, 'minute')}; it is now {hour}."
            if asked
            else f"It is now {hour}."
        )
        self.record(
            "time", lambda w: text, actor=r, audience=[r], payload={"waited_minutes": asked}
        )

    # What a resident reads ------------------------------------------------------------------

    def situation(self, r: Resident) -> str:
        now = self.clock.now()
        parts = [f"{tell_moment(now, self.config.start_date)}."]
        if isinstance(r.base, Sleep):
            parts.append(
                "You are asleep."
                if r.base.suspended
                else f"You are in bed at home and will wake at {clock_time(r.base.wake)}."
            )
        elif isinstance(r.base, Movement):
            parts.append(
                f"You are on your way to {self.config.place(r.base.destination).name} and will "
                f"arrive at {clock_time(r.base.arrival)}. There is nothing to do until you arrive."
            )
        else:
            assert r.place is not None
            place = self.config.place(r.place).name
            if isinstance(r.base, Work) and r.place == r.occupation.workplace:
                where = f"You are at work at {place}"
            elif isinstance(r.base, Work):  # on a duty that runs anywhere
                where = f"You are at {place}, at work"
            elif isinstance(r.base, Bedridden):
                where = "You are in bed at home, too ill to get up"
            else:
                where = f"You are at {place}"
            if r.conversation is not None:
                others = [
                    self.named(self.residents[name])
                    for name in sorted(r.conversation.members - {r.name})
                ]
                parts.append(f"{where}, in a conversation with {listed(others)}.")
            else:
                parts.append(f"{where}.")
            parts.append(self.people_here(r))
            parts += self.counter_told(r)
            parts += self.left_told(r)
        parts.append(self.purse(r))
        parts += self.body.warnings(r.living)
        if r.place == r.home:
            parts.append(self.things_told(r))
        claim = self.board.claims.get(r.name)
        if claim is not None:
            parts.append(f"You hold task {claim.task} ({self.board.task(claim.task).repo}).")
        return " ".join(parts)

    def usable(self, r: Resident) -> list[ToolSpec]:
        """The tools `r`'s event offers at its place now, in declared order and as its
        occupation declares them, less those of no use to it there: the work of other
        occupations; its own away from its workplace, where the board hangs and the machines
        are, the counter, the kitchen, the surgery or the report, except the doctor's at the
        bedside of one too ill to get up; the task's without a task; `start_work` where it has no
        work; and `message` with nothing to write with."""
        if r.suspended:
            return []
        own = OCCUPATION_TOOLS[r.occupation.id]
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

    def review(self, r: Resident) -> str:
        """The world's record of `r`'s day, told to it as its own day; the work in a workspace
        is told as one line per stretch of commands and file reads and writes."""
        lines: list[str] = []
        stretch: dict[str, Any] | None = None

        def close_stretch() -> None:
            if stretch is None:
                return
            done = []
            if stretch["commands"]:
                failed = stretch["failed"]
                done.append(
                    f"ran {counted(stretch['commands'], 'command')}"
                    + (f" ({failed} failed)" if failed else "")
                )
            if stretch["reads"]:
                done.append(f"read {counted(stretch['reads'], 'file')}")
            if stretch["writes"]:
                done.append(f"wrote {counted(stretch['writes'], 'file')}")
            lines.append(
                f"{clock_time(stretch['start'])}-{clock_time(stretch['end'])} For task "
                f"{stretch['task']} you {listed(done)}."
            )

        for t, kind, text, payload in r.day:
            if kind == "time":
                continue
            if kind in ("command", "file_read", "file_write"):
                if stretch is None or stretch["task"] != payload["task"]:
                    close_stretch()
                    stretch = {
                        "task": payload["task"],
                        "start": t,
                        "commands": 0,
                        "failed": 0,
                        "reads": 0,
                        "writes": 0,
                    }
                stretch["end"] = t
                if kind == "command":
                    stretch["commands"] += 1
                    stretch["failed"] += payload["exit_code"] != 0
                else:
                    stretch["reads" if kind == "file_read" else "writes"] += 1
                continue
            close_stretch()
            stretch = None
            lines.append(f"{clock_time(t)} {text}")
        close_stretch()
        if not lines:
            return "Nothing to look back on yet today."
        return "Your day, as it went:\n" + "\n".join(lines)

    def knows(self, r: Resident, name: str) -> bool:
        """Whether `name` is one of the town's tools as `r`'s occupation has them, whether or not
        it can use it now."""
        return name in self._specs[r.occupation.id]

    async def call(self, r: Resident, name: str, args: dict[str, Any]) -> ToolResult:
        """Carry out the tool `name` (`knows`) for `r`, whether or not its last request declared
        it: refused, naming the condition, when `r` is asleep, when its event does not offer it
        (`refusal`), when it is another occupation's work or its arguments do not fit; in a
        conversation, what the conversation does not offer of its own leaves it first."""
        handler = tools.HANDLERS[name]
        if r.suspended:
            return ToolResult("You are asleep.", ends_turn=True)
        if name not in r.tools:
            base = r.base
            destination = (
                self.config.place(base.destination).name if isinstance(base, Movement) else ""
            )
            text = refusal(base, name, destination=destination)
            return ToolResult(text, ends_turn=isinstance(base, Movement))
        if name in WORK_DONE - OCCUPATION_TOOLS[r.occupation.id]:
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


class ResidentPort:
    """One resident's reach into the world: `agent.port.WorldPort`, and the owner of its inbox.

    `wait` returns as soon as a percept is pending. While the resident is awake it is told
    something within the idle interval of simulated time (or within the minutes it asked to
    wait, and if something else ends that wait sooner, that it did); while it sleeps nothing
    reaches it until it wakes, and what was told to it meanwhile is held and delivered with the
    wake-up. A resident in bed whose runtime waits with nothing pending falls asleep."""

    def __init__(self, world: World, resident: Resident) -> None:
        self._world = world
        self._resident = resident
        self._inbox: list[Percept] = []
        self.held: list[Percept] = []
        self._arrived = asyncio.Event()
        self._interrupt = asyncio.Event()
        self.waiting = False

    def rules(self) -> str:
        """The rules as they stand: who lives where now, and so one's own home and rent."""
        return self._world.rules.text(self._resident.name, self._world.homes())

    def tool_specs(self) -> list[ToolSpec]:
        """The tools the resident's event offers at its place now (`World.usable`)."""
        return self._world.usable(self._resident)

    def knows(self, name: str) -> bool:
        return self._world.knows(self._resident, name)

    @property
    def asleep(self) -> bool:
        return self._resident.suspended

    def situation(self) -> str:
        return self._world.situation(self._resident)

    def sim_time(self) -> int:
        return self._world.clock.now()

    def set_busy(self, busy: bool) -> None:
        self._world.clock.set_busy(self._resident.name, busy)

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        return await self._world.call(self._resident, name, args)

    def pending(self) -> list[Percept]:
        taken, self._inbox = self._inbox, []
        self._arrived.clear()
        self._interrupt.clear()
        return taken

    async def wait(self) -> list[Percept]:
        world, r = self._world, self._resident
        self.waiting = True
        asked, began, armed = r.wait_minutes, world.clock.now(), False
        try:
            if not self._inbox:
                if isinstance(r.base, Sleep) and not r.base.suspended:
                    world.fall_asleep(r)
                if not r.suspended:
                    world.arm_tick(r)
                    armed = True
            world.rest_changed()
            await self._arrived.wait()
            if asked and (not armed or r.tick is not None):  # news came before the minutes
                world.end_wait(r, began)
            return self.pending()
        finally:
            self.waiting = False
            r.wait_minutes = None
            world.disarm_tick(r)
            world.rest_changed()

    @property
    def interrupt(self) -> asyncio.Event:
        return self._interrupt

    @property
    def has_pending(self) -> bool:
        return bool(self._inbox)

    def deliver(self, percept: Percept, interrupt: bool) -> None:
        if self._resident.suspended:
            self.held.append(percept)
            return
        self._inbox.append(percept)
        self._arrived.set()
        if interrupt:
            self._interrupt.set()

    def release(self) -> None:
        """Deliver what was held while the resident slept."""
        held, self.held = self.held, []
        for percept in held:
            self.deliver(percept, False)
