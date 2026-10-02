"""Physical truth: the places of the town and where each agent is."""

from collections.abc import Iterable
from enum import StrEnum

from pydantic import Field, model_validator

from core.environment.rejection import Rejected
from infrastructure.config import StrictModel


class PlaceKind(StrEnum):
    HOME = "home"
    WORK = "work"
    SOCIAL = "social"


class Place(StrictModel):
    """A place in the town at map position (`x`, `y`). A home names the agents living there."""

    id: str = Field(min_length=1)
    kind: PlaceKind
    name: str
    description: str
    x: float
    y: float
    residents: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _only_homes_have_residents(self) -> "Place":
        if self.residents and self.kind != PlaceKind.HOME:
            raise ValueError(f"place {self.id!r} has residents but is not a home")
        return self


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

    def move(self, agent: str, place: str) -> str:
        """Put `agent` at `place` and return where it was; raises Rejected for an unknown place."""
        if place not in self.places:
            raise Rejected(f"there is no place called {place!r}")
        origin = self.locations[agent]
        self.locations[agent] = place
        return origin
