"""Physical truth: the places of the town and where each agent is."""

from collections.abc import Iterable
from enum import StrEnum

from pydantic import Field, model_validator

from core.environment.rejection import Rejected
from core.interaction import time_at
from infrastructure.config import StrictModel


class PlaceKind(StrEnum):
    HOME = "home"
    WORK = "work"
    SOCIAL = "social"


class Place(StrictModel):
    """A place in the town at map position (`x`, `y`). A home names the agents living there
    and is always open; another place may be open only during `hours`, spans written
    `HH:MM-HH:MM` in the order of the day, each from its opening to its closing time."""

    id: str = Field(min_length=1)
    kind: PlaceKind
    name: str
    description: str
    x: float
    y: float
    residents: tuple[str, ...] = ()
    hours: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> "Place":
        if self.residents and self.kind != PlaceKind.HOME:
            raise ValueError(f"place {self.id!r} has residents but is not a home")
        if self.hours and self.kind == PlaceKind.HOME:
            raise ValueError(f"home {self.id!r} has opening hours")
        for span in self.hours:
            if len(span.split("-")) != 2:
                raise ValueError(f"opening hours {span!r} of {self.id!r} are not HH:MM-HH:MM")
            for clock in span.split("-"):
                time_at(1, clock)
        clocks = [clock for span in self.spans() for clock in span]
        if clocks != sorted(set(clocks)):
            raise ValueError(f"opening hours of {self.id!r} must follow the day: {self.hours}")
        return self

    def spans(self) -> list[tuple[str, str]]:
        """The opening and closing time of each span of `hours`."""
        return [tuple(span.split("-")) for span in self.hours]

    def is_open(self, clock: str) -> bool:
        """Whether the place is open at `clock` (`HH:MM`); a span includes its opening time."""
        return not self.hours or any(opens <= clock < closes for opens, closes in self.spans())


class World:
    """The places by id and the id of each agent's current place."""

    def __init__(self, places: Iterable[Place], locations: dict[str, str]) -> None:
        self.places = {place.id: place for place in places}
        if unknown := set(locations.values()) - self.places.keys():
            raise ValueError(f"agents are located at unknown places {sorted(unknown)}")
        self.locations = locations

    def occupants(self, place: str) -> list[str]:
        """The agents at `place`."""
        return [agent for agent, here in self.locations.items() if here == place]

    def move(self, agent: str, place: str, clock: str) -> str:
        """Put `agent` at `place` at `clock` and return where it was; raises Rejected for an
        unknown place or one closed at `clock`, also if the agent is already there."""
        if place not in self.places:
            raise Rejected(f"there is no place called {place!r}")
        if not self.places[place].is_open(clock):
            raise Rejected(f"{self.places[place].name} is closed at {clock}")
        origin = self.locations[agent]
        self.locations[agent] = place
        return origin
