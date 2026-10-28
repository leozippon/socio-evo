"""The world of one town: its state, its schedule, and one port per resident.

`World` is created from a configuration, a run directory and a work backend; creating it loads
the task split, checks that every task's image is present and that every agent directory exists,
and writes nothing. A new world stands at the checkpoint hour of day 1 with every resident asleep
at home, to wake at the forced waking hour, before any board is posted; `restore` puts it instead
in the state of a saved checkpoint, whose board is what was left of the last one posted. `run`
then drives the town until a given day's checkpoint.

Everything that happens at a moment of simulated time is a timer in one queue, run by `run` in
the order of its times: arrivals, wake-ups, the end of a silent conversation, the percept that
tells a waiting resident the time, and the day's schedule, which is all the fixed structure a day
has. For day N (whose daytime is calendar day N): the posting of day N's board at the workplace
in the morning, which replaces what was left of the day before's; midnight, when each resident's
food and health are reckoned, its rent and fees are charged with a statement and expired claims
run out; the forced sleep; and the checkpoint. Every hour on the hour, besides, the bodies are
brought up to date (see below). The workplace never closes, and residents go to bed and wake
when they choose, except that one sleep lasts at most a configured span and that nobody wakes
between the forced sleep and the checkpoint. At the checkpoint the world waits until every
resident is asleep and its runtime waits on its port, holds the clock, closes every workspace
keeping its changes, takes the snapshot and awaits `on_checkpoint(day, snapshot)`, through which
the composition layer writes the checkpoint and commits the agent directories. A lived day N
runs from the checkpoint on calendar day N to the one on calendar day N + 1; the journal, the
acceptance runs and the record `review_day` tells belong to it.

A resident's living (`Living`, of `world.body`) is what it owns and keeps in stock, what it has
eaten since the last midnight, and its body's three needs: the goods of the catalogue act through
it. The body (`Body`) is reckoned lazily and exactly: `reckon` brings a resident up to the moment
at the rates of what it has been doing since it was last reckoned, and is called every hour on
the hour, before every change of activity (sitting down to work, setting off, arriving, going
to bed, falling asleep, waking) and at the checkpoint, so that a checkpoint carries the body as
of its moment. A resident awake and able to eat eats from its stock of food as it is reckoned;
food bought on the spot is eaten as it is bought. A resident the reckoning finds at work in the
lowest band of energy stops work, as `leave_work` stops it, keeping its task, and is told that
it cannot work until it has slept; before an action in its workspace the body is reckoned too,
so that the exhausted are refused it (`tools`). A need that crosses into another band is
logged, and told to the resident when it is awake at a place (the wake-up, the statement and a
purchase's result tell it otherwise); the situation names the needs in their lowest band. At
midnight health moves by the day, and a resident whose health has reached its floor takes to
its bed: it leaves what it was in, is carried home if it was elsewhere, and is in the event
Bedridden, where it can do little but speak to whoever comes and eat what it is given, until
treatment (`treat`) lets it up; those where it was and at its home are told, and a checkpoint
keeps it so. A durable with the effect travel shortens the owner's journeys, one with messaging
lets it write to other owners, and one with appearance shows its phrase wherever others perceive
the owner: who is here, who arrived, whom one is in conversation with; a low band of health
shows the same way. Rent is the home's, and a resident may move into a home with a free room.

Each resident's port declares to its runtime the tools of its event at its place now
(`usable`), so that what a request offers is what can be done; the situation no longer lists
them. The world delivers each percept to the ports of those who perceive it. Speech reaches the
residents it is addressed to, at their place and awake; it draws into the conversation, with
`interrupt`, those it names and, when it is said to everyone, those not working outside the
conversation. A resident at work outside it hears a remark to everyone without being drawn in or
interrupted, and reads it, like everything else, with its runtime's next tool result or when it
next waits. A resident in transit is at no place and perceives nothing there; an asleep resident
cannot be addressed, and what is told to it while suspended is held until it wakes.
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
from world.clock import DAY, Clock, ManualClock, clock_time, parse_hour, tell_date, tell_moment
from world.config import Band, Good, TownConfig
from world.economy import Economy
from world.events import (
    BOARD_TOOLS,
    EXHAUSTED,
    TASK_TOOLS,
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
from world.rules import Rules, bare, longest_sleep
from world.telling import cap, counted, listed, you

Tell = Callable[[str | None], str]
"""A text as told to a witness (None: to nobody in particular)."""
OnCheckpoint = Callable[[int, dict[str, Any]], Awaitable[None]]


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
    `reckoned` the simulated time its body was last brought up to; `day` the record of its
    lived day: (simulated time, kind, its wording, payload) of every entry that concerns it."""

    name: str
    home: str
    agent_dir: Path
    place: str | None
    base: Base
    living: Living = field(default_factory=Living)
    reckoned: int = 0
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
        """What the resident can do now: its event's actions."""
        return self.event.tools

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
        self._board_posted = parse_hour(config.day.board_posted)
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
        self.economy = Economy(config.currency, {r.name: r.purse for r in config.residents})
        self.board = Board(
            tasks, backend, config.work, seed=config.seed, names=names, money=self.economy.money
        )
        self.body = Body(config.needs)
        self.rules = Rules(config)
        self.tool_specs: list[ToolSpec] = tools.specs(config)
        self._specs = {spec.name: spec for spec in self.tool_specs}
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
                rc.name, rc.home, directories[rc.name], rc.home, Sleep(0, True), reckoned=start
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
        them."""
        self._at((day - 1) * DAY + self._board_posted, partial(self._post_board, day))
        self._at(day * DAY, partial(self._midnight, day))
        self._at(day * DAY + self._forced, partial(self._force_sleep, day))
        self._at(day * DAY + self._checkpoint_hour, partial(self._checkpoint, day))

    def _post_board(self, day: int) -> None:
        """Post the board of calendar day `day`, in place of what was left of the day before's,
        and tell those at the workplace."""
        self.board.post(day)
        workplace = self.config.workplace
        here = [r for r in self.residents.values() if r.place == workplace.id and r.awake]
        hour = clock_time(self.clock.now())
        self.record(
            "board_posted",
            lambda w: f"It is {hour}: the day's board is posted at {workplace.name}.",
            place=workplace.id,
            audience=here,
            payload={"tasks": len(self.board.posted)},
        )

    def _hourly(self) -> None:
        """Every hour on the hour, every resident's body is brought up to it; the first call,
        as the world starts to run, only arms the next hour."""
        for r in self.residents.values():
            self.reckon(r)
        now = self.clock.now()
        self._at(now - now % 3600 + 3600, self._hourly)

    def _midnight(self, day: int) -> None:
        """The end of calendar day `day`: its food and its health reckoned and charges taken,
        and the claims that run out with it."""
        self._settle(day)
        self._expire(day)

    def _expire(self, day: int) -> None:
        board = self.board
        ending = [(name, board.claims[name]) for name in board.expired(day)]
        for name, claim in ending:
            workspace = board.drop(name)
            if workspace is not None:
                board.orphans.append(workspace)
            r = self.residents[name]
            self.record(
                "expiry",
                lambda w, r=r, claim=claim: (
                    f"{cap(you(r.name, w))} lost task {claim.task}: "
                    "the claim ran out unpaid at midnight."
                ),
                actor=r,
                place=None,
                audience=[r],
                payload={"task": claim.task},
            )

    def _settle(self, day: int) -> None:
        """Midnight for every resident: its body is brought up to the hour and its health moves
        by the day (a resident whose health has reached its floor takes to its bed here), the
        day's food is reckoned, rent and the fees of what it owns are taken, and the statement
        is told."""
        date = tell_date(day, self.config.start_date)
        for r in self.residents.values():
            self.reckon(r)
            living = r.living
            home = self.config.place(r.home)
            assert home.rent is not None and home.comfort is not None
            before = self.body.bands(living)
            night = self.body.night(living, home.comfort)
            if living.health <= 0 and not living.bedridden:
                self._take_to_bed(r, day)
            self.note_bands(r, before, tell=False)
            stock = []
            for good in self.config.goods:
                if good.kind != "consumable" or not living.eaten.get(good.id):
                    continue
                assert good.per_day is not None
                left = living.things.get(good.id, 0)
                if not left:
                    stock.append(f"You have used up your {bare(good.name)}.")
                elif left <= good.per_day:
                    stock.append(f"You have {counted(left, 'helping')} of {bare(good.name)} left.")
            charges = [(f"rent for your room at {home.name}", home.rent)]
            charges += [
                (f"the daily charge on {good.name}", good.fee_per_day)
                for good in self.config.goods
                if good.fee_per_day and living.things.get(good.id)
            ]
            fees = sum(amount for _, amount in charges[1:])
            nourishment = self.nourishment(r)
            eaten = [
                f"{counted(units, 'helping')} of {bare(good.name)}"
                if good.kind == "consumable"
                else good.name
                if units == 1
                else f"{units} × {good.name}"
                for good in self.config.goods
                if (units := living.eaten.get(good.id))
            ]
            food = (
                f"You ate today: {listed(eaten)}."
                if nourishment
                else "You had nothing to eat today."
            )
            items = self.economy.settle(r.name, charges)
            statement = " ".join(
                [f"Your statement for {date}: {'; '.join(items)}.", food, *stock]
                + [self.body.condition(living), self.economy.purse(r.name)]
            )
            self.record(
                "settlement",
                lambda w, r=r, statement=statement: (
                    statement if w == r.name else f"{r.name} was charged rent at midnight."
                ),
                actor=r,
                place=None,
                audience=[r],
                payload={
                    "rent": home.rent,
                    "fees": fees,
                    "nourishment": nourishment,
                    "purse": self.economy.purses[r.name],
                    "satiety": round(living.satiety, 1),
                    "energy": round(living.energy, 1),
                    "health": round(living.health, 1),
                    "night": night,
                },
            )
            living.eaten = {}

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
        """Treatment restores `restores` of `r`'s health and, if `r` was bedridden, lets it up:
        Idle at its home, logged as `recovered` and told to it and to those there. The clinic's
        treatment, which a resident buys there for itself, calls this; the Hospital's doctor at
        a patient's bedside will call the same. Until then a bedridden resident, which can
        neither leave its home nor buy, cannot be treated."""
        self.reckon(r)
        self.body.treat(r.living, restores)
        if not r.living.bedridden:
            return
        r.living.bedridden = False
        if isinstance(r.base, Bedridden):
            r.base = Idle()
        self.record(
            "recovered",
            lambda w: (
                "You are well enough to leave your bed."
                if w == r.name
                else f"{r.name} is well enough to leave its bed."
            ),
            actor=r,
            audience=[r, *self.addressable(r)],
            payload={"restores": restores, "health": round(r.living.health, 1)},
        )

    # The body ---------------------------------------------------------------------------------

    def reckon(self, r: Resident) -> None:
        """Bring `r`'s body up to the moment at the rates of what it has been doing since it was
        last reckoned, let it eat from its stock if it is awake and could eat, and note each
        need that crossed into another band, telling `r` if it is awake at a place; if `r` is at
        work and exhausted, its work stops."""
        now = self.clock.now()
        before = self.body.bands(r.living)
        home = self.config.place(r.home)
        assert home.comfort is not None
        self.body.elapse(r.living, now - r.reckoned, self.activity(r), home.comfort)
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
        """Awake and able to eat, `r` eats from its stock of food, a unit at a time and at most
        the good's units a day, until it could eat no more."""
        if not r.awake:
            return
        living = r.living
        for good in self.config.goods:
            if good.kind != "consumable" or good.nourishment is None:
                continue
            assert good.per_day is not None
            while (
                self.body.hungry(living)
                and living.things.get(good.id, 0)
                and living.eaten.get(good.id, 0) < good.per_day
            ):
                living.things[good.id] -= 1
                if not living.things[good.id]:
                    del living.things[good.id]
                self.eat(r, good, 1)

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
        return sum(
            good.nourishment * units
            for good in self.config.goods
            if good.nourishment is not None and (units := r.living.eaten.get(good.id))
        )

    def eat(self, r: Resident, good: Good, units: int) -> None:
        """`r` eats `units` of the food `good`: today's record grows and its satiety rises."""
        assert good.nourishment is not None
        r.living.eaten[good.id] = r.living.eaten.get(good.id, 0) + units
        self.body.eat(r.living, good.nourishment * units)

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
        """The world's whole state at a checkpoint: every resident asleep, nothing open."""
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
                "wake": r.base.wake,
                "longest": r.base.longest,
                "purse": self.economy.purses[name],
                "ledger": copy.deepcopy(self.economy.ledger[name]),
                "claim": claim.saved() if claim else None,
                "done": sorted(self.board.done[name]),
                "held": [asdict(percept) for percept in r.port.held],
            }
        return {"time": self.clock.now(), "posted": list(self.board.posted), "residents": residents}

    def restore(self, state: dict[str, Any]) -> None:
        """Put a new world in the state `snapshot` returned, and log the resumption."""
        if self._started:
            raise RuntimeError("a world is restored before it runs")
        if set(state["residents"]) != set(self.residents):
            raise ValueError("the checkpoint's residents are not the configuration's")
        self.clock.set(state["time"])
        self.board.posted = list(state["posted"])  # the last board, less what was paid for
        for name, saved in state["residents"].items():
            r = self.residents[name]
            assert r.timer is not None
            r.timer.cancel()
            r.place = saved["place"]
            r.home = saved["home"]
            r.living = Living(**copy.deepcopy(saved["living"]))
            r.reckoned = state["time"]
            # A checkpoint from before the body woke anyone early has no `longest`.
            longest = saved.get("longest", False)
            self._put_to_sleep(r, saved["wake"], suspended=True, longest=longest)
            self.economy.purses[name] = saved["purse"]
            self.economy.ledger[name] = copy.deepcopy(saved["ledger"])
            if saved["claim"] is not None:
                self.board.hold(name, saved["claim"])
            self.board.done[name] = set(saved["done"])
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
            good.phrase
            for good in self.config.goods
            if good.phrase is not None and r.living.things.get(good.id)
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
        """What `r` owns and has in stock, in its own words."""
        things = []
        for good in self.config.goods:
            left = r.living.things.get(good.id, 0)
            if not left:
                continue
            if good.kind == "consumable":
                things.append(f"{good.name} ({counted(left, 'helping')})")
            else:
                things.append(good.name)
        return f"You have {listed(things)}." if things else "You have nothing of your own yet."

    def travel_minutes(self, r: Resident, a: str, b: str) -> int:
        """How long `r` takes from `a` to `b`: the walk, shortened by what it owns for travel."""
        factor = min(
            (
                good.factor
                for good in self.config.goods
                if good.factor is not None and r.living.things.get(good.id)
            ),
            default=1.0,
        )
        return math.ceil(self.config.travel(a, b) * factor)

    def look(self, r: Resident) -> str:
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
        return f"{text} {self.people_here(r)}"

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
            f"midnight your rent is {self.economy.money(home.rent)} a day."
        )

    def stop_work(self, r: Resident) -> None:
        """`r` stops work: by its own `leave_work`, by going elsewhere or to bed, or because the
        forced sleep takes it, so that every stretch of work in the log ends. The body is
        reckoned first, and may have stopped it already."""
        self.reckon(r)
        if isinstance(r.base, Work):
            r.base = Idle()
            self.record("leave_work", lambda w: f"{cap(you(r.name, w))} stopped work.", actor=r)

    def break_off(self, r: Resident) -> str:
        """`r` leaves its conversation and stops work, if it is in them, as going elsewhere or
        to bed does on its own; what it is told of it, a sentence or nothing."""
        left = []
        if r.conversation is not None:
            self.leave_conversation(r)
            left.append("left the conversation")
        if isinstance(r.base, Work):
            self.stop_work(r)
            left.append("stopped work")
        return f"You {' and '.join(left)}. " if left else ""

    def depart(self, r: Resident, place: str) -> int:
        """Set `r` off from where it is to `place`; returns the time of arrival."""
        assert r.place is not None
        origin = r.place
        arrival = self.clock.now() + self.travel_minutes(r, origin, place) * 60
        witnesses = self.addressable(r)
        self.reckon(r)
        r.base, r.place = Movement(place, arrival), None
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
        place = r.base.destination
        r.place, r.base = place, Idle()
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
            payload={"place": place},
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
        """`r` leaves its conversation; the others are told at what time, since they may read it
        some time later."""
        conversation = r.conversation
        assert conversation is not None
        conversation.members.discard(r.name)
        r.conversation = None
        rest = [self.residents[name] for name in sorted(conversation.members)]
        hour = clock_time(self.clock.now())
        self.record(
            "leave_conversation",
            lambda w: f"At {hour} {you(r.name, w)} left the conversation.",
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
            if isinstance(r.base, Work):
                where = f"You are at work at {place}"
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
        parts.append(self.economy.purse(r.name))
        parts += self.body.warnings(r.living)
        if r.place == r.home:
            parts.append(self.things_told(r))
        claim = self.board.claims.get(r.name)
        if claim is not None:
            parts.append(f"You hold task {claim.task} ({self.board.task(claim.task).repo}).")
        return " ".join(parts)

    def usable(self, r: Resident) -> list[ToolSpec]:
        """The tools `r`'s event offers at its place now, in declared order, less those of no
        use there: `message` with nothing to write with, the board's and the task's away from
        the workplace, where the board hangs and the work is done, and the task's without a
        task."""
        if r.suspended:
            return []
        useless: set[str] = set()
        if not any(
            r.living.things.get(good.id) for good in self.config.goods if good.effect == "messaging"
        ):
            useless.add("message")
        if r.place != self.config.workplace.id:
            useless |= BOARD_TOOLS | TASK_TOOLS
        if r.name not in self.board.claims:
            useless |= TASK_TOOLS
        return [spec for spec in self.tool_specs if spec.name in r.tools - useless]

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

    async def call(self, r: Resident, name: str, args: dict[str, Any]) -> ToolResult:
        handler = tools.HANDLERS[name]
        if r.suspended:
            return ToolResult("You are asleep.", ends_turn=True)
        event = r.event
        if name not in event.tools:
            destination = (
                self.config.place(event.destination).name if isinstance(event, Movement) else ""
            )
            text = refusal(event, name, destination=destination)
            return ToolResult(text, ends_turn=isinstance(event, Movement))
        problem = tools.check(self._specs[name], args)
        if problem:
            return ToolResult(problem)
        return await handler(self, r, args)


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
