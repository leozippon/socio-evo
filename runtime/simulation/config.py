"""What a run does, day by day: duration, calendar, scenes, checkpoints, interventions."""

from pydantic import Field, JsonValue, PositiveInt, model_validator

from core.interaction import time_at
from infrastructure.config import StrictModel
from runtime.scenes import SceneConfig
from runtime.scheduler import Calendar, Clock


class Intervention(StrictModel):
    """On `day` at `at` (the start of that day if unset), turn the `conditions` knobs and/or
    make an `announcement` that every agent witnesses. It takes effect before anything else
    happens at that time."""

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
    """A run of `days` days. New jobs are posted at the start of each slot named in
    `postings`. A checkpoint is written at the end of every day divisible by `checkpoint_days`
    and of the last day run. An intervention must fall on a day of the run, at the day start,
    a slot start or the day end, since a slot's scenes play to the end before anything else
    happens; a conversation must fit within the shortest slot, and a work session's rounds
    must be at least a minute apart."""

    days: PositiveInt
    calendar: Calendar
    postings: tuple[str, ...] = Field(min_length=1)
    scenes: SceneConfig = SceneConfig()
    checkpoint_days: PositiveInt = 1
    interventions: tuple[Intervention, ...] = ()

    @model_validator(mode="after")
    def _fits(self) -> "SimulationConfig":
        calendar = self.calendar
        moments = [calendar.day_start, *(slot.start for slot in calendar.slots), calendar.day_end]
        for intervention in self.interventions:
            day, at = intervention.day, intervention.at
            if day > self.days:
                raise ValueError(f"intervention on day {day} is after the last day {self.days}")
            if at is not None and at not in moments:
                raise ValueError(
                    f"intervention on day {day} at {at} can take effect only at the day start, "
                    f"a slot start or the day end: {', '.join(moments)}"
                )
        slots = [slot.name for slot in calendar.slots]
        if unknown := sorted(set(self.postings) - set(slots)):
            raise ValueError(f"jobs are posted in slots the calendar does not have: {unknown}")
        if len(set(self.postings)) != len(self.postings):
            raise ValueError(f"jobs are posted twice in a slot: {list(self.postings)}")
        shortest = calendar.shortest_slot()
        if self.scenes.conversation_minutes > shortest:
            raise ValueError(
                f"conversations may last {self.scenes.conversation_minutes} minutes, longer "
                f"than the shortest slot ({shortest} minutes)"
            )
        if self.scenes.work_rounds > shortest:
            raise ValueError(f"{self.scenes.work_rounds} work rounds do not fit {shortest} minutes")
        return self
