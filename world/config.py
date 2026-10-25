"""The configuration of a town: its places, its residents, its work, its social life, its clock
and the few fixed hours of its night.

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
    Every place, the workplace included, can be visited and used at any hour."""

    id: Id
    name: str = Field(min_length=1)
    kind: Literal["home", "workplace", "social"]


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
    """The work at the workplace. `split` names the task pool posted at every midnight; a claim
    made on a calendar day runs out at the midnight that ends the day `claim_expiry_days` days
    later."""

    split: str = Field(min_length=1)
    payment: int = Field(ge=1)
    living_cost: int = Field(ge=0)
    acceptance_runs: int = Field(ge=1, description="acceptance runs per task per resident per day")
    claim_expiry_days: int = Field(ge=0)
    shell_timeout_s: int = Field(ge=1)
    acceptance_timeout_s: int = Field(ge=1)


class Exchange(StrictModel):
    """Group B's evening: at `at` every resident is paired by lot (whoever is asleep is woken
    for it), walks to `place` and talks about its work, `messages` messages each."""

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
    """The only fixed hours of a day, all after midnight: at `forced_sleep` whoever is still up
    falls asleep, to wake at `forced_wake`; at `checkpoint`, between the two, the day's state is
    saved. A lived day runs from one checkpoint to the next. `sleep_at_most` is not an hour but
    the longest one sleep may last, written the same way and so less than a day; it is at least
    the forced sleep's span."""

    forced_sleep: Hour
    checkpoint: Hour
    forced_wake: Hour
    sleep_at_most: Hour

    def of_day(self, hour: str) -> int:
        """`hour` in seconds from the midnight that begins the lived day; an hour earlier than
        the checkpoint falls after the next midnight."""
        t = parse_hour(hour)
        return t + DAY if t < parse_hour(self.checkpoint) else t


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
        day = self.day
        forced, checkpoint, wake, longest = map(
            parse_hour, (day.forced_sleep, day.checkpoint, day.forced_wake, day.sleep_at_most)
        )
        if not forced < checkpoint < wake:
            raise ValueError("the hours must run forced_sleep < checkpoint < forced_wake")
        if longest < wake - forced:
            raise ValueError("sleep_at_most must last at least from forced_sleep to forced_wake")
        exchange = self.social.exchange
        if exchange is not None:
            if self.social.mode != "isolated":
                raise ValueError("the evening exchange belongs to the isolated mode")
            if places.get(exchange.place, None) is None or places[exchange.place].kind != "social":
                raise ValueError(f"the exchange place {exchange.place} is not a social place")
            if day.of_day(exchange.at) >= day.of_day(day.forced_sleep):
                raise ValueError("the evening exchange must come before the forced sleep")
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
