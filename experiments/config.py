"""An experiment: one YAML file naming everything a society run is made of."""

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, PositiveFloat, model_validator

from core.agent import AgentSeed, CognitionConfig
from core.agent.evolution import EvolutionConfig
from core.environment import Conditions, EnvironmentConfig, PlaceKind, Trade
from core.interaction import clock_of, time_at
from infrastructure.config import StrictModel
from infrastructure.llm import LLMConfig
from runtime.simulation import SimulationConfig
from tasks.coding import Isolation

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TasksConfig(StrictModel):
    """The task bank of each trade the town has work of (`banks`, by trade), each a directory
    relative to the project root or an absolute one, which may start with `~`; how many
    seconds each check of a delivery may run; and how delivered work is separated from the
    machine (`tasks.sandbox.Isolation`): in a bubblewrap sandbox, or, as a choice named here
    for machines without bubblewrap, not at all. A configuration frozen before the town had
    trades names one `bank`, the programming trade's, which loads as `banks` of that trade
    alone."""

    provider: Literal["coding", "swebench"] = "coding"
    instances: tuple[str, ...] = ()
    community: bool = False
    repository_guidance: bool = False
    strict_http_cache: bool = False
    evaluation_preflight: bool = False
    http_cache: str | None = None
    dataset_variant: Literal["lite", "verified"] = "verified"
    solo_deadline_days: int = Field(default=2, ge=1)
    joint_deadline_days: int = Field(default=2, ge=1)
    command_seconds: int = Field(default=60, ge=1, le=300)
    evaluation_seconds: int = Field(default=600, ge=60, le=1800)
    banks: dict[Trade, str] = Field(default={Trade.PROGRAMMING: "tasks/coding/bank"}, min_length=1)
    timeout: PositiveFloat = 5.0
    isolation: Isolation = Isolation.BUBBLEWRAP

    @model_validator(mode="before")
    @classmethod
    def _one_bank_is_the_programming_banks(cls, data: Any) -> Any:
        if isinstance(data, dict) and "bank" in data:
            if "banks" in data:
                raise ValueError("name the banks by trade under `banks`, or one `bank` alone")
            data = {**data, "banks": {Trade.PROGRAMMING: data["bank"]}}
            del data["bank"]
        return data

    @model_validator(mode="after")
    def _guidance_needs_repository_provider(self):
        if self.repository_guidance and self.provider != "swebench":
            raise ValueError("repository_guidance requires the swebench provider")
        if self.evaluation_preflight and not self.strict_http_cache:
            raise ValueError("evaluation_preflight requires strict_http_cache")
        if (self.evaluation_preflight or self.strict_http_cache) and self.provider != "swebench":
            raise ValueError("offline evaluation readiness requires the swebench provider")
        return self

    @property
    def http_cache_path(self) -> Path | None:
        return PROJECT_ROOT / Path(self.http_cache).expanduser() if self.http_cache else None

    @property
    def bank_path(self) -> Path:
        """Legacy single programming-bank path, including SWE-bench dataset JSON."""
        return self.bank_paths[Trade.PROGRAMMING]

    @property
    def bank_paths(self) -> dict[Trade, Path]:
        return {trade: PROJECT_ROOT / Path(bank).expanduser() for trade, bank in self.banks.items()}


class ExperimentConfig(StrictModel):
    """Everything a run is made of. The agents must be exactly the residents of the homes,
    every intervention, and every enactment of a meeting's answer, must leave the conditions
    valid and post only trades the town has a bank of, no place may close after the day ends,
    since whoever is still out goes home then, and a meeting must be at a social place that
    stays open, from the start of its slot, for as long as its conversation and the answers
    after it can last."""

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
        if self.tasks.provider == "swebench":
            if set(self.tasks.banks) != {Trade.PROGRAMMING}:
                raise ValueError("SWE-bench pilot requires only the programming bank")
            if (not self.tasks.instances and not self.tasks.community) or len(
                set(self.tasks.instances)
            ) != len(self.tasks.instances):
                raise ValueError("SWE-bench requires distinct configured instance IDs")
            if self.environment.conditions.two_part_tasks and not self.tasks.community:
                raise ValueError("SWE-bench pilot supports single-part jobs only")
            if self.tasks.instances and self.environment.conditions.one_part_tasks > len(
                self.tasks.instances
            ):
                raise ValueError("not enough SWE-bench issues for distinct postings")
        if (
            self.simulation.scheduling in ("independent", "activities", "realtime")
            and not self.tasks.community
        ):
            raise ValueError("independent scheduling currently requires community repository tasks")
        if self.tasks.community:
            if self.tasks.provider != "swebench" or not self.environment.strict_acceptance:
                raise ValueError("community work requires SWE-bench and strict acceptance")
            if self.environment.establishments:
                raise ValueError("community work currently uses the shared public board")
        if self.environment.posting_mode == "replenish":
            if self.simulation.postings != ("morning",):
                raise ValueError("replenishment runs post only in the morning")
            if self.environment.task_shelf_life_days is not None:
                raise ValueError("replenishment requires persistent unclaimed notices")
        names = [seed.profile.name for seed in self.agents]
        residents = self.environment.homes
        if len(set(names)) != len(names) or set(names) != residents.keys():
            raise ValueError(f"agents {names} are not exactly the residents {list(residents)}")
        conditions = self.environment.conditions.model_dump()
        self._posts_only_its_trades(self.environment.conditions)
        for intervention in self.simulation.changes:
            self._posts_only_its_trades(
                Conditions.model_validate(conditions | intervention.conditions)
            )
        places = {place.id: place for place in self.environment.places}
        calendar, scenes = self.simulation.calendar, self.simulation.scenes
        for meeting in self.simulation.meetings:
            for changes in meeting.enacts.values():
                self._posts_only_its_trades(Conditions.model_validate(conditions | changes))
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

    def _posts_only_its_trades(self, conditions: Conditions) -> None:
        for place in self.environment.places:
            if place.trade is not None and place.trade not in self.tasks.banks:
                raise ValueError(
                    f"{place.id} is an establishment of {place.trade.value}, of which the town "
                    f"has no bank (tasks.banks names {[t.value for t in self.tasks.banks]})"
                )
        if unknown := sorted(conditions.trade_mix.keys() - self.tasks.banks.keys()):
            raise ValueError(
                f"the trade mix posts {[trade.value for trade in unknown]}, of which the town "
                f"has no bank (tasks.banks names {[trade.value for trade in self.tasks.banks]})"
            )
