"""Configuration of reality at the start of a run."""

from collections import Counter
from typing import Literal

from pydantic import Field, NonNegativeInt, PositiveFloat, PositiveInt, model_validator

from core.environment.conditions import Conditions
from core.environment.world import Establishment, Place
from core.interaction import Setting
from infrastructure.config import StrictModel


class Circumstances(StrictModel):
    """One resident's own circumstances: a starting balance in place of the town's, and an
    obligation charged every evening together with the living cost."""

    initial_balance: int | None = None
    obligation: NonNegativeInt = 0


class EnvironmentConfig(StrictModel):
    """The town, the initial conditions and the constants of society.

    `setting` is the world the town is set in: its name, its backdrop, its money and the date
    of day 1 (see `core.interaction.Setting`); left out, it is a nameless town of crowns whose
    day 1 is a Monday. It belongs here, with the places, because reality is its first reader,
    telling every amount and every day in its events by it, and everything else that tells the
    town to a resident (the runtime's setting and situations, the probes) reads it from the
    environment; the composition layer hands the same setting to each agent for its own
    memories and to its history for the dates of its commits.

    Every agent lives in exactly one home among `places` and starts there with
    `initial_balance` in the town's money, unless its `circumstances` say otherwise. A rating's
    weight in esteem halves every `esteem_half_life_days`; an unclaimed task leaves the board
    after `task_shelf_life_days` days on it.
    """

    setting: Setting = Setting()
    places: tuple[Place, ...] = Field(min_length=1)
    conditions: Conditions
    initial_balance: int
    circumstances: dict[str, Circumstances] = {}
    esteem_half_life_days: PositiveFloat
    task_shelf_life_days: PositiveInt | None
    posting_mode: Literal["append", "replenish"] = "append"
    replacement_timing: Literal["morning", "immediate"] = "morning"
    strict_acceptance: bool = False

    @model_validator(mode="after")
    def _unique_places_and_residents(self) -> "EnvironmentConfig":
        firms = [
            (place.id, place.establishment)
            for place in self.places
            if place.establishment is not None
        ]
        for what, names in (
            ("place id", [place.id for place in self.places]),
            ("resident", [agent for place in self.places for agent in place.residents]),
            ("position holder", [p for _, firm in firms for p in (firm.foreman, *firm.staff)]),
        ):
            if repeated := sorted(name for name, count in Counter(names).items() if count > 1):
                raise ValueError(f"repeated {what}s: {repeated}")
        if strangers := sorted(self.circumstances.keys() - self.homes.keys()):
            raise ValueError(f"circumstances of people who live nowhere: {strangers}")
        for place, firm in firms:
            if strangers := sorted({firm.foreman, *firm.staff} - self.homes.keys()):
                raise ValueError(f"{place} employs people who live nowhere: {strangers}")
        return self

    @property
    def establishments(self) -> dict[str, "Establishment"]:
        """The establishment of each work place that is one, by place id."""
        return {p.id: p.establishment for p in self.places if p.establishment is not None}

    @property
    def homes(self) -> dict[str, str]:
        """The id of each resident's home."""
        return {agent: place.id for place in self.places for agent in place.residents}

    def starting_balance(self, agent: str) -> int:
        own = self.circumstances.get(agent, Circumstances()).initial_balance
        return self.initial_balance if own is None else own

    def obligation(self, agent: str) -> int:
        return self.circumstances.get(agent, Circumstances()).obligation
