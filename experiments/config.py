"""An experiment: one YAML file naming everything a society run is made of."""

from pathlib import Path

from pydantic import Field, PositiveFloat, model_validator

from core.agent import AgentSeed, CognitionConfig
from core.agent.evolution import EvolutionConfig
from core.environment import Conditions, EnvironmentConfig, PlaceKind
from core.interaction import clock_of, time_at
from infrastructure.config import StrictModel
from infrastructure.llm import LLMConfig
from runtime.simulation import SimulationConfig
from tasks.coding import Isolation

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TasksConfig(StrictModel):
    """The coding task bank, a directory relative to the project root or an absolute one, which
    may start with `~`; how many seconds each check of a delivery may run; and how delivered
    code is separated from the machine (`tasks.coding.Isolation`): in a bubblewrap sandbox, or,
    as a choice named here for machines without bubblewrap, not at all."""

    bank: str = "tasks/coding/bank"
    timeout: PositiveFloat = 5.0
    isolation: Isolation = Isolation.BUBBLEWRAP

    @property
    def bank_path(self) -> Path:
        return PROJECT_ROOT / Path(self.bank).expanduser()


class ExperimentConfig(StrictModel):
    """Everything a run is made of. The agents must be exactly the residents of the homes,
    every intervention, and every enactment of a meeting's answer, must leave the conditions
    valid, no place may close after the day ends, since whoever is still out goes home then,
    and a meeting must be at a social place that stays open, from the start of its slot, for
    as long as its conversation and the answers after it can last."""

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
        for intervention in self.simulation.changes:
            Conditions.model_validate(conditions | intervention.conditions)
        places = {place.id: place for place in self.environment.places}
        calendar, scenes = self.simulation.calendar, self.simulation.scenes
        for meeting in self.simulation.meetings:
            for changes in meeting.enacts.values():
                Conditions.model_validate(conditions | changes)
            place = places.get(meeting.place)
            if place is None or place.kind is not PlaceKind.SOCIAL:
                raise ValueError(f"meeting on day {meeting.day}: no social place {meeting.place}")
            start = dict(calendar.slot_times(1))[meeting.at]
            last = start + scenes.conversation_turns * scenes.turn_minutes  # the answers
            opens = clock_of(start)
            closes = place.closing(opens) if place.is_open(opens) else opens
            if closes is not None and time_at(1, closes) <= last:
                raise ValueError(
                    f"meeting on day {meeting.day}: {meeting.place} is not open from {opens} "
                    f"until after {clock_of(last)}, when its answers may be given"
                )
        end = self.simulation.calendar.day_end
        for place in self.environment.places:
            if late := [closes for _, closes in place.spans() if closes > end]:
                raise ValueError(f"{place.id} closes at {late[-1]}, after the day ends at {end}")
        return self
