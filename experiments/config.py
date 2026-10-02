"""An experiment: one YAML file naming everything a society run is made of."""

from pathlib import Path

from pydantic import Field, PositiveFloat, model_validator

from core.agent import AgentSeed, CognitionConfig
from core.agent.evolution import EvolutionConfig
from core.environment import Conditions, EnvironmentConfig
from infrastructure.config import StrictModel
from infrastructure.llm import LLMConfig
from runtime.simulation import SimulationConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TasksConfig(StrictModel):
    """The coding task bank, a directory relative to the project root, and how many seconds
    each check of a delivery may run."""

    bank: str = "tasks/coding/bank"
    timeout: PositiveFloat = 5.0

    @property
    def bank_path(self) -> Path:
        return PROJECT_ROOT / self.bank


class ExperimentConfig(StrictModel):
    """Everything a run is made of. The agents must be exactly the residents of the homes,
    and every intervention must leave the conditions valid."""

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
        return self
