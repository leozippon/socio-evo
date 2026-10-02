"""What a run does, day by day: duration, calendar, scenes, checkpoints, interventions."""

from pydantic import Field, JsonValue, PositiveInt, model_validator

from core.interaction import time_at
from infrastructure.config import StrictModel
from runtime.scenes import SceneConfig
from runtime.scheduler import Calendar, Clock


class Intervention(StrictModel):
    """On `day` at `at` (the start of that day if unset), turn the `conditions` knobs and/or
    make an `announcement` that every agent witnesses."""

    day: PositiveInt
    at: Clock | None = None
    conditions: dict[str, JsonValue] = Field(default_factory=dict)
    announcement: str | None = None

    @model_validator(mode="after")
    def _does_something(self) -> "Intervention":
        if not self.conditions and self.announcement is None:
            raise ValueError("an intervention changes conditions, announces something or both")
        return self

    def time(self, calendar: Calendar) -> int:
        return time_at(self.day, self.at or calendar.day_start)


class SimulationConfig(StrictModel):
    """A run of `days` days. A checkpoint is written at the end of every day divisible by
    `checkpoint_days` and of the last day run. An intervention must fall within its day,
    and the longest scene within the shortest slot."""

    days: PositiveInt
    calendar: Calendar
    scenes: SceneConfig = SceneConfig()
    checkpoint_days: PositiveInt = 1
    interventions: tuple[Intervention, ...] = ()

    @model_validator(mode="after")
    def _fits(self) -> "SimulationConfig":
        calendar = self.calendar
        for intervention in self.interventions:
            day, time = intervention.day, intervention.time(calendar)
            if day > self.days or not calendar.start(day) <= time <= calendar.end(day):
                raise ValueError(
                    f"intervention on day {day} at {intervention.at} is outside the run"
                )
        if self.scenes.longest > calendar.shortest_slot():
            raise ValueError(
                f"scenes may last {self.scenes.longest} minutes, longer than the shortest slot "
                f"({calendar.shortest_slot()} minutes)"
            )
        return self
