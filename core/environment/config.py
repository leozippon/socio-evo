"""Configuration of reality at the start of a run."""

from collections import Counter

from pydantic import Field, PositiveFloat, PositiveInt, model_validator

from core.environment.conditions import Conditions
from core.environment.world import Place
from infrastructure.config import StrictModel


class EnvironmentConfig(StrictModel):
    """The town, the initial conditions and the constants of society.

    Every agent lives in exactly one home among `places` and starts there with
    `initial_balance` credits. A rating's weight in esteem halves every
    `esteem_half_life_days`; an unclaimed task leaves the board after
    `task_shelf_life_days` days on it.
    """

    places: tuple[Place, ...] = Field(min_length=1)
    conditions: Conditions
    initial_balance: int
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
        return self

    @property
    def homes(self) -> dict[str, str]:
        """The id of each resident's home."""
        return {agent: place.id for place in self.places for agent in place.residents}
