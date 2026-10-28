"""The configuration of a town: its places, its residents, its work, the goods for sale, its
social life, its clock and the few fixed hours of its day. Every check that the world relies on
is made when the configuration is validated, so that a bad configuration stops a run before
anything is written.

Living costs are rent, charged by the home a resident occupies (a home has `rooms`, `rent` a day
for each, and a `comfort`, which bears on how well its residents sleep and keep their health),
and the goods it buys. Goods are a catalogue (`goods`): the world implements three kinds of good
and the effects of `Effect`, and everything else about a good is data, so the catalogue grows
without code. A `consumable` is bought as a stock of `uses`, which its owner eats from as it gets
hungry, at most `per_day` units a day; an `immediate` good is consumed as it is bought; a
`durable` is owned once and kept, billed `fee_per_day` on the statement while owned. A good with
the effect `food` gives its `nourishment` when it is eaten, a share of a day's need (100 a full
day); `travel` makes the owner's journeys take `factor` of the time; `messaging` lets owners
write to one another wherever they are; `appearance` shows `phrase` to whoever sees the owner;
`examination` tells the buyer the numbers of its body and their causes; `treatment` restores
`restores` of its health.

The residents' bodies (`needs`, implemented by `world.body`) are three needs, each a number from
0 to 100 that the resident reads in bands of plain words: satiety, which falls by the hour and
rises with what is eaten; energy, spent awake, at work and on the road and restored by sleep
in proportion to the home's comfort, never above the resident's health; and health, reckoned
at midnight from the day. Every rate and band is configuration; the world knows only the three
needs and that the lowest band of each is where the consequences lie.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Literal, get_args

from pydantic import AfterValidator, Field, model_validator

from agent.wording import offences
from infrastructure.config import StrictModel
from world.clock import DAY, parse_hour


def _hour(text: str) -> str:
    parse_hour(text)
    return text


Hour = Annotated[str, AfterValidator(_hour)]
"""An hour of the day, `HH:MM`."""
Id = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*$")]
Name = Annotated[str, Field(pattern=r"^[A-Z][A-Za-z'-]*$")]
"""A resident's name: one capitalised word, the way others address it."""
Effect = Literal["food", "travel", "messaging", "appearance", "examination", "treatment"]
"""What a good does in the world: the one enumeration of effects, each implemented by the world."""
EFFECTS: tuple[str, ...] = get_args(Effect)
IMMEDIATE_EFFECTS = frozenset({"examination", "treatment"})
"""The effects that only an immediate good has: a service, used up as it is bought."""


class Place(StrictModel):
    """A place of the town. `name` is how a sentence names it ("the café on the square").
    Every place, the workplace included, can be visited and used at any hour. A home has `rooms`,
    one a resident, charges `rent` a day for each and has a `comfort` (1 is an ordinary home); a
    shop and a social place may sell goods."""

    id: Id
    name: str = Field(min_length=1)
    kind: Literal["home", "workplace", "social", "shop"]
    rent: int | None = Field(default=None, ge=0, description="a home's rent a day for one room")
    rooms: int | None = Field(default=None, ge=1, description="a home's rooms, one a resident")
    comfort: float | None = Field(default=None, gt=0, description="a home's comfort, 1 ordinary")

    @model_validator(mode="after")
    def _by_kind(self) -> Place:
        given = (self.rent, self.rooms, self.comfort)
        if self.kind == "home":
            if any(value is None for value in given):
                raise ValueError(f"the home {self.id} needs rent, rooms and comfort")
        elif any(value is not None for value in given):
            raise ValueError(f"{self.id} is not a home and has no rent, rooms or comfort")
        return self


class Good(StrictModel):
    """A good for sale (see the module docstring). `name` is how a sentence names it, with its
    article ("a bicycle", "groceries", "a meal at Café Linde"); `sold_at` names the places that
    sell it."""

    id: Id
    name: str = Field(min_length=1)
    price: int = Field(ge=1)
    sold_at: tuple[Id, ...] = Field(min_length=1)
    kind: Literal["consumable", "immediate", "durable"]
    effect: Effect
    uses: int | None = Field(default=None, ge=1, description="a consumable's units in one purchase")
    per_day: int | None = Field(default=None, ge=1, description="a consumable's units used a day")
    fee_per_day: int = Field(default=0, ge=0, description="a durable's charge a day while owned")
    nourishment: int | None = Field(default=None, ge=1, description="food: what one unit gives")
    factor: float | None = Field(default=None, gt=0, le=1, description="travel: the time taken")
    phrase: str | None = Field(default=None, description="appearance: what others see")
    restores: float | None = Field(default=None, gt=0, description="treatment: the health given")

    @model_validator(mode="after")
    def _consistent(self) -> Good:
        what = f"the good {self.id}"
        if self.kind == "consumable":
            if self.uses is None or self.per_day is None:
                raise ValueError(f"{what} is consumable and needs uses and per_day")
            if self.per_day > self.uses:
                raise ValueError(f"{what} uses more a day than one purchase holds")
        elif self.uses is not None or self.per_day is not None:
            raise ValueError(f"{what} is not consumable and has no uses or per_day")
        if self.kind != "durable" and self.fee_per_day:
            raise ValueError(f"{what} is not durable and carries no fee")
        if self.effect == "food":
            if self.kind == "durable":
                raise ValueError(f"{what} is food and so is consumable or immediate")
        elif self.effect in IMMEDIATE_EFFECTS:
            if self.kind != "immediate":
                raise ValueError(
                    f"{what} has the effect {self.effect}, which only an immediate has"
                )
        elif self.kind != "durable":
            raise ValueError(f"{what} has the effect {self.effect}, which only a durable has")
        if (self.nourishment is not None) != (self.effect == "food"):
            raise ValueError(f"{what}: nourishment belongs to the effect food, and only to it")
        if (self.factor is not None) != (self.effect == "travel"):
            raise ValueError(f"{what}: factor belongs to the effect travel, and only to it")
        if (self.phrase is not None) != (self.effect == "appearance"):
            raise ValueError(f"{what}: phrase belongs to the effect appearance, and only to it")
        if (self.restores is not None) != (self.effect == "treatment"):
            raise ValueError(f"{what}: restores belongs to the effect treatment, and only to it")
        if self.phrase is not None:
            if not self.phrase.strip():
                raise ValueError(f"{what} has an empty phrase")
            if found := offences(self.phrase):
                raise ValueError(f"{what}'s phrase has words the town does not use: {found}")
        return self

    @property
    def days(self) -> int:
        """How many days one purchase of a consumable lasts."""
        assert self.uses is not None and self.per_day is not None
        return self.uses // self.per_day


class Band(StrictModel):
    """A band of a need: the values from `floor` up to the next band's floor. `name` is how the
    resident reads it, after "you are" ("hungry", "a little tired"); `seen` is how others see it
    on the resident, if the band shows ("looking unwell")."""

    floor: float = Field(ge=0, lt=100)
    name: str = Field(min_length=1)
    seen: str | None = None

    @model_validator(mode="after")
    def _worded(self) -> Band:
        for text in (self.name, self.seen or ""):
            if text != text.strip() or (text and not text.strip()):
                raise ValueError(f"the band {self.name!r} has blank wording")
            if found := offences(text):
                raise ValueError(f"the band {self.name!r} has words the town does not use: {found}")
        return self


class Need(StrictModel):
    """A need from 0 to 100, read in `bands` from the top band down to the lowest, whose floor
    is 0 and where the consequences lie."""

    bands: tuple[Band, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _descending(self) -> Need:
        floors = [band.floor for band in self.bands]
        if floors != sorted(floors, reverse=True) or len(set(floors)) < len(floors):
            raise ValueError("a need's bands run from the top down, each floor below the last")
        if floors[-1] != 0:
            raise ValueError("a need's lowest band begins at 0")
        if len({band.name for band in self.bands}) < len(self.bands):
            raise ValueError("a need's bands have different names")
        return self

    @property
    def lowest(self) -> Band:
        return self.bands[-1]


class Satiety(Need):
    """Falls `per_hour` at all hours; a day's need is 100, which is what nourishment is a
    share of."""

    per_hour: float = Field(gt=0)


class Energy(Need):
    """Falls `awake_per_hour` awake, `work_per_hour` more at work, `walk_per_minute` more on the
    road; rises `sleep_per_hour` times the home's comfort asleep, up to the resident's health or
    to `rested_at_least`, whichever is higher, so that an ill resident still wakes with some of
    a day's energy. In its lowest band the resident cannot work: its work stops and it cannot
    sit down to work again until it has slept, so `rested_at_least` must reach the band above,
    or an ill resident could never work again."""

    awake_per_hour: float = Field(ge=0)
    work_per_hour: float = Field(ge=0)
    walk_per_minute: float = Field(ge=0)
    sleep_per_hour: float = Field(gt=0)
    rested_at_least: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _untrapped(self) -> Energy:
        if self.rested_at_least < self.bands[-2].floor:
            raise ValueError("sleep must restore energy out of its lowest band at any health")
        return self


class Health(Need):
    """Reckoned at midnight: falls `starving` when satiety is in its lowest band, `exhausted`
    when energy is, `poor_home` when the home's comfort is below 1; rises `recovery` when
    neither starving nor exhausted. At 0 the resident dies."""

    starving: float = Field(ge=0)
    exhausted: float = Field(ge=0)
    poor_home: float = Field(ge=0)
    recovery: float = Field(ge=0)


class Needs(StrictModel):
    """The three needs of a resident's body (see the module docstring)."""

    satiety: Satiety
    energy: Energy
    health: Health


class Route(StrictModel):
    """The walking time between two places, in both directions."""

    between: tuple[Id, Id]
    minutes: int = Field(ge=1)


class Resident(StrictModel):
    """A resident: its name, its home, the money it starts with, the people it knows already
    (`ties`: for each, a sentence or two in the second person on how, which the rules tell it;
    every tie is mutual), and its agent directory, which the composition layer sets; without one
    it is `agents/<name>` in the run directory."""

    name: Name
    home: Id
    purse: int
    ties: dict[Name, str] = Field(default_factory=dict)
    agent_dir: Path | None = None


class Work(StrictModel):
    """The work at the workplace. `split` names the task pool, of which the board posts
    `board_size` tasks every day at the hour `day.board_posted`, in a rotation through the whole
    pool; a claim made on a calendar day runs out at the midnight that ends the day
    `claim_expiry_days` days later."""

    split: str = Field(min_length=1)
    board_size: int = Field(ge=1, description="tasks posted a day, the whole pool if it is smaller")
    payment: int = Field(ge=1)
    acceptance_runs: int = Field(ge=1, description="acceptance runs per task per resident per day")
    claim_expiry_days: int = Field(ge=0)
    shell_timeout_s: int = Field(ge=1)
    acceptance_timeout_s: int = Field(ge=1)


class Social(StrictModel):
    silence_minutes: int = Field(ge=1, description="a conversation ends after this much silence")


class ClockSettings(StrictModel):
    """The clock's speeds in simulated seconds per real second, and the longest a resident waits
    without being told anything, in simulated minutes. The speed is `speed_idle` while no resident
    is busy (in a model request or a tool execution); while some are, it falls linearly with
    their number from `speed_busy_one`, with one, to `speed_busy_all`, with every resident."""

    speed_idle: float
    speed_busy_one: float
    speed_busy_all: float
    idle_minutes: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> ClockSettings:
        if not self.speed_idle >= self.speed_busy_one >= self.speed_busy_all >= 1:
            raise ValueError(
                "the speeds must run speed_idle >= speed_busy_one >= speed_busy_all >= 1"
            )
        return self


class DayHours(StrictModel):
    """The only fixed hours of a day, all after midnight: at `forced_sleep` whoever is still up
    falls asleep, to wake at `forced_wake`; at `checkpoint`, between the two, the day's state is
    saved; at `board_posted`, no earlier than the waking, the day's board goes up at the
    workplace. A lived day runs from one checkpoint to the next. `sleep_at_most` is not an hour
    but the longest one sleep may last, written the same way and so less than a day; it is at
    least the forced sleep's span."""

    forced_sleep: Hour
    checkpoint: Hour
    forced_wake: Hour
    board_posted: Hour
    sleep_at_most: Hour

    def of_day(self, hour: str) -> int:
        """`hour` in seconds from the midnight that begins the lived day; an hour earlier than
        the checkpoint falls after the next midnight."""
        t = parse_hour(hour)
        return t + DAY if t < parse_hour(self.checkpoint) else t


class TownConfig(StrictModel):
    currency: str = Field(min_length=1, description="the symbol money is written with")
    start_date: date = Field(description="the date of day 1")
    seed: int = Field(description="seeds the board's rotation")
    places: tuple[Place, ...] = Field(min_length=1)
    travel_minutes: int = Field(ge=1, description="walking time between places without a route")
    routes: tuple[Route, ...] = ()
    residents: tuple[Resident, ...] = Field(min_length=1)
    work: Work
    goods: tuple[Good, ...] = Field(min_length=1)
    needs: Needs
    social: Social
    clock: ClockSettings
    day: DayHours

    @model_validator(mode="after")
    def _consistent(self) -> TownConfig:
        places = {place.id: place for place in self.places}
        _unique("place id", [place.id for place in self.places])
        _unique("resident name", [resident.name for resident in self.residents])
        _unique("agent directory", [r.agent_dir for r in self.residents if r.agent_dir])
        _unique("route", [frozenset(route.between) for route in self.routes])
        _unique("good id", [good.id for good in self.goods])
        for good in self.goods:
            for place_id in good.sold_at:
                if places.get(place_id, None) is None or places[place_id].kind not in (
                    "social",
                    "shop",
                ):
                    raise ValueError(
                        f"the good {good.id} is sold at {place_id}, not a shop or social place"
                    )
        if not any(good.effect == "food" for good in self.goods):
            raise ValueError("the town sells nothing to eat")
        for route in self.routes:
            a, b = route.between
            if a == b or a not in places or b not in places:
                raise ValueError(f"route {a}-{b} must join two different known places")
        workplaces = [place for place in self.places if place.kind == "workplace"]
        if len(workplaces) != 1:
            raise ValueError(f"a town has exactly one workplace, not {len(workplaces)}")
        residents = {resident.name: resident for resident in self.residents}
        for resident in self.residents:
            if places.get(resident.home, None) is None or places[resident.home].kind != "home":
                raise ValueError(f"{resident.name}'s home {resident.home} is not a home")
        for place in self.places:
            if place.kind == "home":
                living = [resident.name for resident in self.residents if resident.home == place.id]
                assert place.rooms is not None
                if len(living) > place.rooms:
                    raise ValueError(
                        f"{place.id} has {place.rooms} rooms for {len(living)} residents"
                    )
        for resident in self.residents:
            for other, how in resident.ties.items():
                if other == resident.name or other not in residents:
                    raise ValueError(
                        f"{resident.name}'s tie to {other}: no other resident is so named"
                    )
                if resident.name not in residents[other].ties:
                    raise ValueError(f"{resident.name}'s tie to {other} is not mutual")
                if not how.strip():
                    raise ValueError(f"{resident.name}'s tie to {other} says nothing")
        day = self.day
        hours = (day.forced_sleep, day.checkpoint, day.forced_wake, day.board_posted)
        forced, checkpoint, wake, posted = map(parse_hour, hours)
        longest = parse_hour(day.sleep_at_most)
        if not forced < checkpoint < wake <= posted:
            raise ValueError(
                "the hours must run forced_sleep < checkpoint < forced_wake <= board_posted"
            )
        if longest < wake - forced:
            raise ValueError("sleep_at_most must last at least from forced_sleep to forced_wake")
        return self

    @property
    def workplace(self) -> Place:
        return next(place for place in self.places if place.kind == "workplace")

    def place(self, place_id: str) -> Place:
        return next(place for place in self.places if place.id == place_id)

    def good(self, good_id: str) -> Good:
        return next(good for good in self.goods if good.id == good_id)

    def travel(self, a: str, b: str) -> int:
        """Walking minutes from place `a` to place `b`; zero from a place to itself."""
        if a == b:
            return 0
        for route in self.routes:
            if set(route.between) == {a, b}:
                return route.minutes
        return self.travel_minutes


def _unique(what: str, values: list[object]) -> None:
    seen: set[object] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {what}: {value}")
        seen.add(value)
