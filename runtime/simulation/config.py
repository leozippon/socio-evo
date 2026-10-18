"""What a run does, day by day: duration, calendar, scenes, checkpoints, interventions."""

from typing import Annotated, Any, Literal

from pydantic import Discriminator, Field, JsonValue, PositiveInt, Tag, model_validator

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


Answer = Annotated[str, Field(pattern=r"^[A-Za-z]+$", max_length=20)]
"""An answer to a meeting's question: one short word."""


class Meeting(StrictModel):
    """On `day`, from the start of the slot named `at`, a meeting at the social place `place`
    on `question`, to be answered with one of `options`, at least two distinct short words.
    `enacts` gives, for an answer, the conditions it changes when it carries, as an
    intervention would; an answer without an enactment leaves things as they are. The
    meeting is announced to everyone at the start of its day, held at its slot as a
    conversation of those present and then an answer from each one still there, and its
    count announced at the end of the day; an answer given by more than half of those asked
    carries and its enactment takes effect at the start of the next day."""

    day: PositiveInt
    at: str
    kind: Literal["meeting"]
    place: str
    question: str = Field(min_length=1)
    options: tuple[Answer, ...] = Field(min_length=2)
    enacts: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _answers(self) -> "Meeting":
        if len(set(self.options)) != len(self.options):
            raise ValueError(f"the meeting on day {self.day} repeats an answer: {self.options}")
        if unknown := sorted(self.enacts.keys() - set(self.options)):
            raise ValueError(f"the meeting on day {self.day} enacts answers it lacks: {unknown}")
        return self

    @property
    def id(self) -> str:
        """The meeting's name in the log: that of its conversation."""
        return f"day-{self.day:04d}/{self.at}/{self.place}"


def _kind(value: Any) -> str:
    kind = value.get("kind") if isinstance(value, dict) else getattr(value, "kind", None)
    return kind or "change"


Planned = Annotated[
    Annotated[Intervention, Tag("change")] | Annotated[Meeting, Tag("meeting")],
    Discriminator(_kind),
]
"""What an experiment plans for a day: a change of conditions or an announcement, or, with
`kind: meeting`, a meeting."""


class SimulationConfig(StrictModel):
    """A run of `days` days. New jobs are posted at the start of each slot named in
    `postings`. A checkpoint is written at the end of every day divisible by `checkpoint_days`
    and of the last day run. An intervention must fall on a day of the run, at the day start,
    a slot start or the day end, since a slot's scenes play to the end before anything else
    happens, and a meeting on a day of the run, at a slot of the calendar, with no other
    meeting at the same slot and place; a conversation must fit within the shortest slot, and
    a work session's rounds must be at least a minute apart. The run fails once more than
    `max_lapse_share` of its decisions and night steps have lapsed for want of a valid reply
    (see `Simulation`)."""

    scheduling: Literal["scenes", "independent"] = "scenes"
    grading_minutes: int = Field(default=20, ge=5, le=120, multiple_of=5)
    days: PositiveInt
    calendar: Calendar
    postings: tuple[str, ...] = Field(min_length=1)
    scenes: SceneConfig = SceneConfig()
    checkpoint_days: PositiveInt = 1
    interventions: tuple[Planned, ...] = ()
    max_lapse_share: float = Field(default=0.01, ge=0, le=1)

    @model_validator(mode="after")
    def _fits(self) -> "SimulationConfig":
        calendar = self.calendar
        if self.scheduling == "independent":
            if calendar.day_start != "07:00" or calendar.day_end != "22:00":
                raise ValueError("independent scheduling requires 07:00–22:00 days")
            if self.meetings:
                raise ValueError("scripted meetings use the legacy scenes scheduler")
        moments = [calendar.day_start, *(slot.start for slot in calendar.slots), calendar.day_end]
        slots = [slot.name for slot in calendar.slots]
        for intervention in self.interventions:
            day, at = intervention.day, intervention.at
            if day > self.days:
                raise ValueError(f"intervention on day {day} is after the last day {self.days}")
            if isinstance(intervention, Meeting):
                if at not in slots:
                    raise ValueError(f"meeting on day {day} at {at!r}, not a slot: {slots}")
            elif at is not None and at not in moments:
                raise ValueError(
                    f"intervention on day {day} at {at} can take effect only at the day start, "
                    f"a slot start or the day end: {', '.join(moments)}"
                )
        held = [meeting.id for meeting in self.meetings]
        if len(set(held)) != len(held):
            raise ValueError(f"two meetings at one slot and place: {held}")
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

    @property
    def changes(self) -> tuple[Intervention, ...]:
        """The interventions that change conditions or announce something."""
        return tuple(i for i in self.interventions if isinstance(i, Intervention))

    @property
    def meetings(self) -> tuple[Meeting, ...]:
        return tuple(i for i in self.interventions if isinstance(i, Meeting))
