"""The configuration of one run: the model endpoint, the runtime's numbers, the town, the
residents' backgrounds, the group's access to skills and the number of days.

The groups differ in `town.social` (mode, evening exchange, whether skills can be passed on) and
in `skills_writable` (false in group D, whose residents can neither write nor receive skills).
`town.seed` is the run's one seed. `llm.base_url` may name an environment variable as
`${NAME}`; it is expanded when the client is built, so that the frozen configuration does not
depend on where the server runs.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, PositiveInt, model_validator

from agent.runtime import RuntimeConfig
from infrastructure.config import StrictModel
from infrastructure.llm import LLMConfig
from world.config import Name, TownConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Resident(StrictModel):
    """A resident's identity: its name and its background file, relative to the project root
    (or absolute), written in the second person."""

    name: Name
    background: Path

    @property
    def background_path(self) -> Path:
        return PROJECT_ROOT / self.background


class ExperimentConfig(StrictModel):
    name: str = Field(pattern=r"^[\w.-]+$", description="the run directory's name")
    llm: LLMConfig
    runtime: RuntimeConfig
    town: TownConfig
    residents: tuple[Resident, ...] = Field(min_length=1)
    skills_writable: bool
    days: PositiveInt

    @model_validator(mode="after")
    def _consistent(self) -> ExperimentConfig:
        names = [resident.name for resident in self.residents]
        town = [resident.name for resident in self.town.residents]
        if len(set(names)) != len(names) or set(names) != set(town):
            raise ValueError(f"residents {names} are not exactly the town's residents {town}")
        if not self.skills_writable and self.town.social.skills_shareable:
            raise ValueError("residents who cannot write skills cannot be passed skills either")
        return self
