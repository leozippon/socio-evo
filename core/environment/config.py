"""Configuration of reality at the start of a run."""

from collections import Counter

from pydantic import Field, NonNegativeInt, PositiveFloat, PositiveInt, model_validator

from core.environment.conditions import Conditions
from core.environment.world import Place
from infrastructure.config import StrictModel


class Circumstances(StrictModel):
    """One resident's own circumstances: a starting balance in place of the town's, and an
    obligation charged every evening together with the living cost."""

    initial_balance: int | None = None
    obligation: NonNegativeInt = 0


class EnvironmentConfig(StrictModel):
    """The town, the initial conditions and the constants of society.

    Every agent lives in exactly one home among `places` and starts there with
    `initial_balance` credits, unless its `circumstances` say otherwise. A rating's weight in
    esteem halves every `esteem_half_life_days`; an unclaimed task leaves the board after
    `task_shelf_life_days` days on it.
    """

    places: tuple[Place, ...] = Field(min_length=1)
    conditions: Conditions
    initial_balance: int
    circumstances: dict[str, Circumstances] = {}
    esteem_half_life_days: PositiveFloat
    task_shelf_life_days: PositiveInt

    @model_validator(mode="after")
    def _unique_places_and_residents(self) -> "EnvironmentConfig":
        for what, names in (
            ("place id", [place.id for place in self.places]),
            ("resident", [agent for place in self.places for agent in place.residents]),
        ):
            if repeated := sorted(name for name, count in Counter(names).items() if count > 1):
                raise ValueError(f"repeated {what}s: {repeated}")
        if strangers := sorted(self.circumstances.keys() - self.homes.keys()):
            raise ValueError(f"circumstances of people who live nowhere: {strangers}")
        return self

    @property
    def homes(self) -> dict[str, str]:
        """The id of each resident's home."""
        return {agent: place.id for place in self.places for agent in place.residents}

    def starting_balance(self, agent: str) -> int:
        own = self.circumstances.get(agent, Circumstances()).initial_balance
        return self.initial_balance if own is None else own

    def obligation(self, agent: str) -> int:
        return self.circumstances.get(agent, Circumstances()).obligation
