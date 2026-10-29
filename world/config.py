"""The configuration of a town: its places, its residents and their occupations, its fund, its
work, the catalogue of its items, its social life, its clock and the few fixed hours of its day.
Every check that the world relies on is made when the configuration is validated, so that a bad
configuration stops a run before anything is written.

A place is a home, one of the five workplaces (`WORKPLACES`: the office, the store, the
restaurant, the hospital and the hall, exactly one of each) or a social place, which has no
purpose but company. Each resident has an `occupation`, which says where it works and what the
town pays it: a wage for each hour at work at the occupation's workplace and a sum for each
service rendered, both from the town's one fund, which starts at `fund.start`, except the wages
of an occupation paid from the fund's tax account, into which every resident pays `tax` of its
day's wages and sums at midnight. Each occupation
works at a place of its own kind (`WORKPLACE_OF`), and every workplace is some occupation's. The
office takes in clients' tasks (`work`), which arrive at random through the working day; the
hospital charges the fees of `hospital` for an examination and a treatment.

Living costs are rent, charged by the home a resident occupies (a home has `rooms`, `rent` a day
for each, and a `comfort`, which bears on how well its residents sleep and keep their health),
and what it buys. Every kind of thing in the town is an `Item` of one catalogue (`items`): the
world implements two kinds of item and the effects of `Effect`, and everything else about an
item is data, so the catalogue grows without code. A `consumable` is food, kept by the unit:
ready food, a helping of `nourishment` (a share of a day's need, 100 a full day) eaten whenever
its owner could eat, or an ingredient, of no nourishment (`nourishment: 0`), which is not eaten
as it is but cooked. A `durable` is owned once and kept, billed `fee_per_day` on the statement
while owned: `travel` makes the owner's journeys take `factor` of the time; `messaging` lets
owners write to one another wherever they are; `appearance` shows `phrase` to whoever sees the
owner. An item comes into the town in one of two ways: the supplier outside the town sells it at
`wholesale` and the Store sells it at a price that starts at `price` and is the shopkeeper's to
change, from shelves stocked at the start with `store.stock`; or the Restaurant's kitchen cooks
it, a dish, from its `ingredients`, units of what the supplier sells, and serves it at a price
that starts at `price` and is the chef's to change. An item that `perishes` is gone at midnight,
wherever it is.

The residents' bodies (`needs`, implemented by `world.body`) are three needs, each a number from
0 to 100 that the resident reads in bands of plain words: satiety, which falls by the hour and
rises with what is eaten; energy, spent awake, at work and on the road and restored by sleep
in proportion to the home's comfort, never above the resident's health; and health, reckoned
at midnight from the day, and worn by illness, which comes by chance at midnight. Every rate,
band and chance is configuration; the world knows only the three needs, that the lowest band of
each is where the consequences lie, and that illness is likelier the lower one's health.
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
Effect = Literal["food", "travel", "messaging", "appearance"]
"""What an item does in the world: the one enumeration of effects, each implemented by the
world."""
EFFECTS: tuple[str, ...] = get_args(Effect)
PlaceKind = Literal["home", "office", "store", "restaurant", "hospital", "hall", "social"]
WORKPLACES = ("office", "store", "restaurant", "hospital", "hall")
"""The kinds of place where an occupation works, exactly one place of each."""
OccupationId = Literal["programmer", "team-leader", "chef", "shopkeeper", "doctor", "mayor"]
WORKPLACE_OF: dict[str, str] = {
    "programmer": "office",
    "team-leader": "office",
    "chef": "restaurant",
    "shopkeeper": "store",
    "doctor": "hospital",
    "mayor": "hall",
}
"""The kind of place where each occupation works."""
A_DAYS_FOOD = 100
"""A day's need of food, which nourishment is a share of."""
HOLDERS = ("shelves", "larder", "portions", "supplier")
"""The holders of items that are neither a resident nor what is left at a place (see
`world.economy`), by the names no place may take."""


class Place(StrictModel):
    """A place of the town. `name` is how a sentence names it ("the Store"). Every place can be
    visited at any hour. A home has `rooms`, one a resident, charges `rent` a day for each and
    has a `comfort` (1 is an ordinary home)."""

    id: Id
    name: str = Field(min_length=1)
    kind: PlaceKind
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


class Item(StrictModel):
    """A kind of thing of the town's catalogue (see the module docstring). `name` is how a
    sentence names it, with its article ("a bicycle", "bread", "an omelette"). It is either
    bought from the supplier (`wholesale`) or cooked in the kitchen (`ingredients`, a dish), and
    `price` is its price at the start where it is sold: the Store's for a unit, the menu's for a
    portion."""

    id: Id
    name: str = Field(min_length=1)
    kind: Literal["consumable", "durable"]
    effect: Effect
    wholesale: int | None = Field(
        default=None, ge=1, description="what the supplier charges for a unit, if it sells it"
    )
    price: int = Field(ge=1, description="the price of a unit at the start, where it is sold")
    ingredients: dict[Id, Annotated[int, Field(ge=1)]] = Field(
        default_factory=dict, description="a dish's: the units of other items a portion takes"
    )
    perishes: bool = Field(default=False, description="whether it is gone at midnight")
    fee_per_day: int = Field(default=0, ge=0, description="a durable's charge a day while owned")
    nourishment: int | None = Field(
        default=None, ge=0, le=A_DAYS_FOOD, description="food: what a helping gives, 0 if raw"
    )
    factor: float | None = Field(default=None, gt=0, le=1, description="travel: the time taken")
    phrase: str | None = Field(default=None, description="appearance: what others see")

    @model_validator(mode="after")
    def _consistent(self) -> Item:
        what = f"the item {self.id}"
        if (self.wholesale is None) == (not self.ingredients):
            raise ValueError(f"{what} is either bought from the supplier or cooked, and not both")
        if self.ingredients and not self.ready:
            raise ValueError(f"{what} is a dish, which is food that is eaten")
        if self.perishes and self.kind != "consumable":
            raise ValueError(f"{what} is not consumable and does not perish")
        if (self.kind == "consumable") != (self.effect == "food"):
            raise ValueError(f"{what}: food is consumable, and everything else durable")
        if self.kind != "durable" and self.fee_per_day:
            raise ValueError(f"{what} is not durable and carries no fee")
        if (self.nourishment is not None) != (self.effect == "food"):
            raise ValueError(f"{what}: nourishment belongs to the effect food, and only to it")
        if (self.factor is not None) != (self.effect == "travel"):
            raise ValueError(f"{what}: factor belongs to the effect travel, and only to it")
        if (self.phrase is not None) != (self.effect == "appearance"):
            raise ValueError(f"{what}: phrase belongs to the effect appearance, and only to it")
        if self.phrase is not None:
            if not self.phrase.strip():
                raise ValueError(f"{what} has an empty phrase")
            if found := offences(self.phrase):
                raise ValueError(f"{what}'s phrase has words the town does not use: {found}")
        return self

    @property
    def ready(self) -> bool:
        """Whether it is ready food, eaten as it is; an ingredient is not."""
        return bool(self.nourishment)

    @property
    def dish(self) -> bool:
        """Whether the kitchen cooks it, a portion at a time, and serves it to be eaten there."""
        return bool(self.ingredients)


class StoreSettings(StrictModel):
    stock: dict[Id, Annotated[int, Field(ge=0)]] = Field(
        description="the units of each item on the Store's shelves at the start"
    )


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


Chance = Annotated[float, Field(ge=0, le=1)]


class Illness(StrictModel):
    """At midnight a resident not ill and not in bed falls ill with the chance of its band of
    health: `chance` in the top band, `run_down` in the second, `unwell` in the third and below;
    `poor_home` more in a home of comfort below 1. While ill it loses `per_night` health at each
    midnight, which mends nothing, and sleep restores half as much energy; it is well again after
    `nights` midnights, or when treated."""

    chance: Chance
    run_down: Chance
    unwell: Chance
    poor_home: Chance
    per_night: float = Field(ge=0)
    nights: int = Field(ge=1)


class Health(Need):
    """Reckoned at midnight: falls `starving` when satiety is in its lowest band, `exhausted`
    when energy is, `poor_home` when the home's comfort is below 1, and by the illness if the
    resident is ill; rises `recovery` when neither starving nor exhausted nor ill. At 0 the
    resident takes to its bed until treated."""

    starving: float = Field(ge=0)
    exhausted: float = Field(ge=0)
    poor_home: float = Field(ge=0)
    recovery: float = Field(ge=0)
    illness: Illness


class Needs(StrictModel):
    """The three needs of a resident's body (see the module docstring)."""

    satiety: Satiety
    energy: Energy
    health: Health


class Route(StrictModel):
    """The walking time between two places, in both directions."""

    between: tuple[Id, Id]
    minutes: int = Field(ge=1)


class Occupation(StrictModel):
    """What a resident does for a living. `title` is how a sentence names it ("the chef");
    `workplace` the place, of the occupation's own kind (`WORKPLACE_OF`), where its work is done
    and where one sits down to work; it is paid `wage_per_hour` for each hour at work and
    `per_service` at once for each service rendered: a programmer for a task of its own accepted,
    the team leader for one of the programmers', the chef for a dish served, the shopkeeper for a
    sale, the doctor for a patient examined or treated. Its `duty` says where the hours at work
    run once one has sat down: at the workplace, until one leaves it or stops; or `anywhere`,
    wherever one goes until one stops, as the mayor's, whose work is being about the town. Its
    wages are `paid_from` the fund, or from the fund's tax account (`taxes`), as the mayor's."""

    id: OccupationId
    title: str = Field(min_length=1)
    workplace: Id
    wage_per_hour: int = Field(ge=1)
    per_service: int = Field(ge=0)
    duty: Literal["workplace", "anywhere"] = "workplace"
    paid_from: Literal["fund", "taxes"] = "fund"


class FundSettings(StrictModel):
    start: int = Field(ge=0, description="the balance the town's fund starts with")


class HospitalSettings(StrictModel):
    """The Hospital's fees at the start, which the doctor changes, and the health a treatment
    restores (it also ends an illness and lets one in bed up)."""

    examination: int = Field(ge=1)
    treatment: int = Field(ge=1)
    restores: float = Field(gt=0, le=100)


class Resident(StrictModel):
    """A resident: its name, its home, its occupation, the money it starts with (`purse`), and
    its agent directory, which the composition layer sets; without one it is `agents/<name>` in
    the run directory. What it has with the others is told in its own background."""

    name: Name
    home: Id
    occupation: Id
    purse: int = Field(ge=0)
    agent_dir: Path | None = None


class Work(StrictModel):
    """The work at the office. `split` names the task pool, which the run's seed shuffles once
    into a rotation; each calendar day a number of tasks drawn with mean `tasks_a_day` arrive, each
    the next of the rotation, at minutes drawn between `arrive_from` and `arrive_until`. The client
    withdraws a task not accepted by the midnight that ends the `expiry_days`th day after the day
    it arrived. A task accepted pays the fund `payment`."""

    split: str = Field(min_length=1)
    tasks_a_day: float = Field(ge=0, description="the mean number of tasks arriving a day")
    arrive_from: Hour
    arrive_until: Hour
    expiry_days: int = Field(ge=0)
    payment: int = Field(ge=1)
    acceptance_runs: int = Field(ge=1, description="acceptance runs per task per resident per day")
    shell_timeout_s: int = Field(ge=1)
    acceptance_timeout_s: int = Field(ge=1)

    @model_validator(mode="after")
    def _window(self) -> Work:
        if parse_hour(self.arrive_from) >= parse_hour(self.arrive_until):
            raise ValueError("tasks arrive between arrive_from and a later arrive_until")
        return self


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
    """The only fixed hours of a day, all after midnight: at `forced_sleep`, the night's end,
    whoever is still up falls asleep where it is, to wake at `forced_wake`; at `checkpoint`,
    between the two, the day's state is saved; at `delivery`, no earlier than the waking, what the
    Store ordered the day before arrives. A lived day runs from one checkpoint to the next.
    `sleep_at_most` is not an hour but the longest one sleep may last, written the same way and so
    less than a day; it is at least the forced sleep's span."""

    forced_sleep: Hour
    checkpoint: Hour
    forced_wake: Hour
    delivery: Hour
    sleep_at_most: Hour

    def of_day(self, hour: str) -> int:
        """`hour` in seconds from the midnight that begins the lived day; an hour earlier than
        the checkpoint falls after the next midnight."""
        t = parse_hour(hour)
        return t + DAY if t < parse_hour(self.checkpoint) else t


class TownConfig(StrictModel):
    currency: str = Field(min_length=1, description="the symbol money is written with")
    start_date: date = Field(description="the date of day 1")
    seed: int = Field(description="seeds the tasks' rotation and arrivals, and illness")
    places: tuple[Place, ...] = Field(min_length=1)
    travel_minutes: int = Field(ge=1, description="walking time between places without a route")
    routes: tuple[Route, ...] = ()
    residents: tuple[Resident, ...] = Field(min_length=1)
    occupations: tuple[Occupation, ...] = Field(min_length=1)
    fund: FundSettings
    tax: float = Field(
        default=0,
        ge=0,
        lt=1,
        description="the share of its day's wages and sums each resident pays into the fund's "
        "tax account at midnight; none unless set",
    )
    work: Work
    items: tuple[Item, ...] = Field(min_length=1)
    store: StoreSettings
    hospital: HospitalSettings
    needs: Needs
    social: Social
    clock: ClockSettings
    day: DayHours

    @model_validator(mode="after")
    def _consistent(self) -> TownConfig:
        places = {place.id: place for place in self.places}
        items = {item.id: item for item in self.items}
        _unique("place id", [place.id for place in self.places])
        _unique("resident name", [resident.name for resident in self.residents])
        _unique("agent directory", [r.agent_dir for r in self.residents if r.agent_dir])
        _unique("route", [frozenset(route.between) for route in self.routes])
        _unique("item id", [item.id for item in self.items])
        for place in self.places:
            if place.id in HOLDERS:
                raise ValueError(f"{place.id} names a holder of items and cannot name a place")
        for dish in self.dishes:
            for item_id in dish.ingredients:
                found = items.get(item_id)
                if found is None or found.effect != "food" or found.wholesale is None:
                    raise ValueError(
                        f"the dish {dish.id} is cooked from {item_id}, which is no food the "
                        "supplier sells"
                    )
        for item_id in self.store.stock:
            if item_id not in items or items[item_id].wholesale is None:
                raise ValueError(f"the Store's stock has {item_id}, which the supplier lacks")
        if not any(item.ready for item in self.items):
            raise ValueError("the town sells nothing to eat")
        for route in self.routes:
            a, b = route.between
            if a == b or a not in places or b not in places:
                raise ValueError(f"route {a}-{b} must join two different known places")
        for kind in WORKPLACES:
            found = [place.id for place in self.places if place.kind == kind]
            if len(found) > 1:
                raise ValueError(f"a town has at most one {kind}, not {len(found)}")
        for kind in WORKPLACES:
            if not any(place.kind == kind for place in self.places):
                raise ValueError(f"the town has no {kind}")
        _unique("occupation id", [occupation.id for occupation in self.occupations])
        for occupation in self.occupations:
            kind = WORKPLACE_OF[occupation.id]
            workplace = places.get(occupation.workplace)
            if workplace is None or workplace.kind != kind:
                article = "an" if kind[0] in "aeiou" else "a"
                raise ValueError(
                    f"the occupation {occupation.id} works at {article} {kind}, and "
                    f"{occupation.workplace} is not one"
                )
        staffed = {occupation.workplace for occupation in self.occupations}
        for place in self.places:
            if place.kind in WORKPLACES and place.id not in staffed:
                raise ValueError(f"the {place.kind} {place.id} is no occupation's workplace")
        occupations = {occupation.id for occupation in self.occupations}
        if "team-leader" in occupations and "programmer" not in occupations:
            raise ValueError("the team leader leads programmers, and the town has none")
        for resident in self.residents:
            if places.get(resident.home, None) is None or places[resident.home].kind != "home":
                raise ValueError(f"{resident.name}'s home {resident.home} is not a home")
            if resident.occupation not in occupations:
                raise ValueError(f"{resident.name}'s occupation {resident.occupation} is not known")
        for place in self.places:
            if place.kind == "home":
                living = [resident.name for resident in self.residents if resident.home == place.id]
                assert place.rooms is not None
                if len(living) > place.rooms:
                    raise ValueError(
                        f"{place.id} has {place.rooms} rooms for {len(living)} residents"
                    )
        day = self.day
        hours = (day.forced_sleep, day.checkpoint, day.forced_wake)
        forced, checkpoint, wake = map(parse_hour, hours)
        longest = parse_hour(day.sleep_at_most)
        if not forced < checkpoint < wake:
            raise ValueError("the hours must run forced_sleep < checkpoint < forced_wake")
        if parse_hour(day.delivery) < wake:
            raise ValueError("the hours must run forced_wake <= delivery")
        if parse_hour(self.work.arrive_from) < wake:
            raise ValueError("tasks arrive no earlier than forced_wake")
        if longest < wake - forced:
            raise ValueError("sleep_at_most must last at least from forced_sleep to forced_wake")
        return self

    def workplace(self, kind: str) -> Place:
        """The town's place of the workplace kind `kind`."""
        return next(place for place in self.places if place.kind == kind)

    def place(self, place_id: str) -> Place:
        return next(place for place in self.places if place.id == place_id)

    def item(self, item_id: str) -> Item:
        return next(item for item in self.items if item.id == item_id)

    @property
    def supplied(self) -> tuple[Item, ...]:
        """The items the supplier sells, which the Store stocks, in the catalogue's order."""
        return tuple(item for item in self.items if item.wholesale is not None)

    @property
    def dishes(self) -> tuple[Item, ...]:
        """The items the kitchen cooks, in the catalogue's order."""
        return tuple(item for item in self.items if item.dish)

    def occupation(self, occupation_id: str) -> Occupation:
        return next(o for o in self.occupations if o.id == occupation_id)

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
