"""The configuration of a town: its places, its residents, its work, its social life, its clock
and the fixed hours of its day.

The four groups of the design differ only here: `social.mode` is `isolated` in A and B (each
resident lives in a town of its own and has a board of its own) and `town` in C and D (one town,
one shared board); `social.exchange` is set in B alone (the evening pairing); and
`social.skills_shareable` is false in D. Every check that the world relies on is made when the
configuration is validated, so that a bad configuration stops a run before anything is written.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

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


class Place(StrictModel):
    """A place of the town. `name` is how a sentence names it ("the café on the square").
    Only the workplace has opening hours: they decide when work can be done and when the board
    is posted. Homes and social places can be visited at any hour."""

    id: Id
    name: str = Field(min_length=1)
    kind: Literal["home", "workplace", "social"]
    opens: Hour | None = None
    closes: Hour | None = None

    @model_validator(mode="after")
    def _hours(self) -> Place:
        if self.kind == "workplace":
            if self.opens is None or self.closes is None:
                raise ValueError(f"the workplace {self.id} needs opens and closes")
            if parse_hour(self.opens) >= parse_hour(self.closes):
                raise ValueError(f"the workplace {self.id} must open before it closes")
        elif self.opens is not None or self.closes is not None:
            raise ValueError(f"only the workplace has opening hours, not {self.id}")
        return self


class Route(StrictModel):
    """The walking time between two places, in both directions."""

    between: tuple[Id, Id]
    minutes: int = Field(ge=1)


class Resident(StrictModel):
    """A resident: its name, its home, the money it starts with, and its agent directory, which
    the composition layer sets; without one it is `agents/<name>` in the run directory."""

    name: Name
    home: Id
    purse: int
    agent_dir: Path | None = None


class Work(StrictModel):
    """The work at the workplace. `split` names the task pool posted every morning; a claim
    runs out at the workplace's closing `claim_expiry_days` days after the day it was made."""

    split: str = Field(min_length=1)
    payment: int = Field(ge=1)
    living_cost: int = Field(ge=0)
    acceptance_runs: int = Field(ge=1, description="acceptance runs per task per resident per day")
    claim_expiry_days: int = Field(ge=0)
    shell_timeout_s: int = Field(ge=1)
    acceptance_timeout_s: int = Field(ge=1)


class Exchange(StrictModel):
    """Group B's evening: at `at` the residents awake are paired by lot, walk to `place` and
    talk about their work, `messages` messages each."""

    at: Hour
    place: Id
    messages: int = Field(ge=1)


class Social(StrictModel):
    mode: Literal["isolated", "town"]
    silence_minutes: int = Field(ge=1, description="a conversation ends after this much silence")
    skills_shareable: bool
    exchange: Exchange | None = None


class ClockSettings(StrictModel):
    """Simulated seconds per real second while some resident is busy and while none is, and
    the longest a resident waits without being told anything, in simulated minutes."""

    speed_active: float = Field(gt=0)
    speed_idle: float = Field(gt=0)
    idle_minutes: int = Field(ge=1)


class DayHours(StrictModel):
    """The fixed hours of a day: nobody wakes before `wake_earliest` nor goes to bed before
    `earliest_sleep`; at `forced_sleep`, after midnight, whoever is still up falls asleep; at
    `checkpoint` the day's state is saved."""

    wake_earliest: Hour
    earliest_sleep: Hour
    forced_sleep: Hour
    checkpoint: Hour

    def of_day(self, hour: str) -> int:
        """`hour` in seconds from the midnight that begins the day; an hour earlier than
        `wake_earliest` falls after the next midnight."""
        t = parse_hour(hour)
        return t + DAY if t < parse_hour(self.wake_earliest) else t


class TownConfig(StrictModel):
    currency: str = Field(min_length=1, description="the symbol money is written with")
    start_date: date = Field(description="the date of day 1")
    seed: int = Field(description="seeds the evening pairing of group B")
    places: tuple[Place, ...] = Field(min_length=1)
    travel_minutes: int = Field(ge=1, description="walking time between places without a route")
    routes: tuple[Route, ...] = ()
    residents: tuple[Resident, ...] = Field(min_length=1)
    work: Work
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
        for route in self.routes:
            a, b = route.between
            if a == b or a not in places or b not in places:
                raise ValueError(f"route {a}-{b} must join two different known places")
        workplaces = [place for place in self.places if place.kind == "workplace"]
        if len(workplaces) != 1:
            raise ValueError(f"a town has exactly one workplace, not {len(workplaces)}")
        for resident in self.residents:
            if places.get(resident.home, None) is None or places[resident.home].kind != "home":
                raise ValueError(f"{resident.name}'s home {resident.home} is not a home")
        workplace = workplaces[0]
        wake = parse_hour(self.day.wake_earliest)
        if not parse_hour(self.day.forced_sleep) < parse_hour(self.day.checkpoint) < wake:
            raise ValueError("the hours must run forced_sleep < checkpoint < wake_earliest")
        if wake > parse_hour(workplace.opens or ""):
            raise ValueError("nobody could be up when the workplace opens")
        closes = parse_hour(workplace.closes or "")
        bedtime = self.day.of_day(self.day.earliest_sleep)
        if not closes < bedtime < self.day.of_day(self.day.forced_sleep):
            raise ValueError(
                "the earliest bedtime must come after the workplace closes and before the "
                "forced sleep"
            )
        exchange = self.social.exchange
        if exchange is not None:
            if self.social.mode != "isolated":
                raise ValueError("the evening exchange belongs to the isolated mode")
            if places.get(exchange.place, None) is None or places[exchange.place].kind != "social":
                raise ValueError(f"the exchange place {exchange.place} is not a social place")
            if parse_hour(exchange.at) < closes:
                raise ValueError("the evening exchange must come after the workplace closes")
            if parse_hour(exchange.at) >= bedtime:
                raise ValueError("the earliest bedtime must come after the evening exchange")
        return self

    @property
    def workplace(self) -> Place:
        return next(place for place in self.places if place.kind == "workplace")

    def place(self, place_id: str) -> Place:
        return next(place for place in self.places if place.id == place_id)

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
