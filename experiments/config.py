"""An experiment: one YAML file naming everything a society run is made of."""

from itertools import pairwise
from pathlib import Path

from pydantic import Field, PositiveFloat, model_validator

from core.agent import AgentSeed, CognitionConfig
from core.agent.evolution import EvolutionConfig
from core.environment import Conditions, EnvironmentConfig
from core.interaction import time_at
from infrastructure.config import StrictModel
from infrastructure.llm import LLMConfig
from runtime.simulation import SimulationConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TasksConfig(StrictModel):
    """The coding task bank, a directory relative to the project root or an absolute one, which
    may start with `~`, and how many seconds each check of a delivery may run."""

    bank: str = "tasks/coding/bank"
    timeout: PositiveFloat = 5.0

    @property
    def bank_path(self) -> Path:
        return PROJECT_ROOT / Path(self.bank).expanduser()


class ExperimentConfig(StrictModel):
    """Everything a run is made of. The agents must be exactly the residents of the homes,
    every intervention must leave the conditions valid, and places may open or close only
    where no slot is under way, since agents move only when a slot starts."""

    name: str = Field(pattern=r"^[\w.-]+$")
    llm: LLMConfig
    agents: tuple[AgentSeed, ...] = Field(min_length=1)
    cognition: CognitionConfig = CognitionConfig()
    evolution: EvolutionConfig = EvolutionConfig()
    environment: EnvironmentConfig
    tasks: TasksConfig = TasksConfig()
    simulation: SimulationConfig

    @model_validator(mode="after")
    def _consistent(self) -> "ExperimentConfig":
        names = [seed.profile.name for seed in self.agents]
        residents = self.environment.homes
        if len(set(names)) != len(names) or set(names) != residents.keys():
            raise ValueError(f"agents {names} are not exactly the residents {list(residents)}")
        conditions = self.environment.conditions.model_dump()
        for intervention in self.simulation.interventions:
            Conditions.model_validate(conditions | intervention.conditions)
        calendar = self.simulation.calendar
        starts = [time for _, time in calendar.slot_times(1)] + [calendar.end(1)]
        for place in self.environment.places:
            for clock in (clock for span in place.spans() for clock in span):
                if any(start < time_at(1, clock) < end for start, end in pairwise(starts)):
                    raise ValueError(f"{place.id} opens or closes at {clock}, within a slot")
        return self
