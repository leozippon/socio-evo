"""Physical truth: the places of the town, the establishments among them, and where each agent
is."""

from collections.abc import Iterable
from enum import StrEnum

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from core.environment.rejection import Rejected
from core.environment.society.work import Trade
from core.interaction import time_at
from infrastructure.config import StrictModel


class PlaceKind(StrEnum):
    HOME = "home"
    WORK = "work"
    SOCIAL = "social"


class Postings(StrictModel):
    """How many one-part and two-part tasks a posting puts on an establishment's sheet."""

    one_part: NonNegativeInt
    two_part: NonNegativeInt


class Establishment(StrictModel):
    """A firm at a work place: its `foreman`, fixed for the run; its `staff` at the start;
    the `wage` paid to each member of staff at the end of every day it was at the firm; its
    `positions`, the foreman's included, so that it has a place to fill while they exceed its
    people; and its own `postings` per posting, the conditions' counts when none are given."""

    foreman: str
    staff: tuple[str, ...] = ()
    wage: NonNegativeInt
    positions: PositiveInt
    postings: Postings | None = None

    @model_validator(mode="after")
    def _people_fit_positions(self) -> "Establishment":
        people = (self.foreman, *self.staff)
        if len(set(people)) != len(people):
            raise ValueError(f"the foreman {self.foreman} and staff {list(self.staff)} repeat")
        if self.positions < len(people):
            raise ValueError(
                f"{self.positions} positions do not hold the foreman and {len(self.staff)} staff"
            )
        return self


class Place(StrictModel):
    """A place in the town at map position (`x`, `y`). A home names the agents living there
    and is always open; another place may be open only during `hours`, spans written
    `HH:MM-HH:MM` in the order of the day, each from its opening to its closing time. A work
    place may be an `establishment` of a `trade`, with a job sheet of its own."""

    id: str = Field(min_length=1)
    kind: PlaceKind
    name: str
    description: str
    x: float
    y: float
    residents: tuple[str, ...] = ()
    hours: tuple[str, ...] = ()
    trade: Trade | None = None
    establishment: Establishment | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "Place":
        if self.residents and self.kind != PlaceKind.HOME:
            raise ValueError(f"place {self.id!r} has residents but is not a home")
        if self.hours and self.kind == PlaceKind.HOME:
            raise ValueError(f"home {self.id!r} has opening hours")
        if (self.trade is None) != (self.establishment is None):
            raise ValueError(f"place {self.id!r} needs a trade and an establishment, or neither")
        if self.establishment is not None and self.kind != PlaceKind.WORK:
            raise ValueError(f"establishment {self.id!r} is not a work place")
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

    def closing(self, clock: str) -> str | None:
        """When the place next closes after `clock`, at which it is open; None if it never
        closes."""
        return next((closes for opens, closes in self.spans() if opens <= clock < closes), None)


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

    def open_after(self, kind: PlaceKind, clock: str) -> bool:
        """Whether a place of `kind` is open after `clock` (`HH:MM`) on the same day; one
        without hours of its own is open until the day ends."""
        return any(
            not place.hours or any(closes > clock for _, closes in place.spans())
            for place in self.places.values()
            if place.kind is kind
        )

    def move(self, agent: str, place: str, clock: str, *, allow_closed: bool = False) -> str:
        """Put `agent` at `place` at `clock` and return where it was; raises Rejected for an
        unknown place or one closed at `clock`. `allow_closed` records physical arrival
        outside a venue without implying admission; legacy callers leave it false."""
        if place not in self.places:
            raise Rejected(f"There is no place called {place!r} in town.")
        if not allow_closed and not self.places[place].is_open(clock):
            name = self.places[place].name
            raise Rejected(f"{name[:1].upper()}{name[1:]} is closed at {clock}.")
        origin = self.locations[agent]
        self.locations[agent] = place
        return origin
