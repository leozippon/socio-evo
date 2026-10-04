"""The calendar: when a day starts and ends, its slots, and the evolution cadences."""

from itertools import pairwise
from typing import Annotated

from pydantic import AfterValidator, Field, PositiveInt, model_validator

from core.agent.evolution import Trigger
from core.interaction import time_at
from infrastructure.config import StrictModel


def _clock(value: str) -> str:
    time_at(1, value)
    return value


Clock = Annotated[str, AfterValidator(_clock)]
"""A time of day as 24-hour `HH:MM`."""


class Slot(StrictModel):
    """A named part of the day, from `start` until the next slot or the end of the day."""

    name: str = Field(pattern=r"^\w+$")
    start: Clock


class Calendar(StrictModel):
    """Each day starts at `day_start`, runs through `slots` in order and ends at `day_end`.

    Weekly evolution is due on every day divisible by `weekly_days`, monthly evolution on
    every day divisible by `monthly_days`; daily evolution is due every day.
    """

    day_start: Clock
    slots: tuple[Slot, ...] = Field(min_length=1)
    day_end: Clock
    weekly_days: PositiveInt = 7
    monthly_days: PositiveInt = 28

    @model_validator(mode="after")
    def _ordered(self) -> "Calendar":
        clocks = [self.day_start, *(slot.start for slot in self.slots), self.day_end]
        if clocks != sorted(set(clocks)):
            raise ValueError("day start, slot starts and day end must strictly increase")
        names = [slot.name for slot in self.slots]
        if len(set(names)) != len(names):
            raise ValueError(f"repeated slot names: {names}")
        return self

    def start(self, day: int) -> int:
        return time_at(day, self.day_start)

    def end(self, day: int) -> int:
        return time_at(day, self.day_end)

    def slot_times(self, day: int) -> list[tuple[str, int]]:
        """Each slot's name and start time on `day`, in order."""
        return [(slot.name, time_at(day, slot.start)) for slot in self.slots]

    def slot_ends(self, day: int) -> dict[str, int]:
        """When each slot ends on `day`: at the next slot's start, the last at the day end."""
        starts = self.slot_times(day)
        return {
            name: end
            for (name, _), end in zip(
                starts, [*(t for _, t in starts[1:]), self.end(day)], strict=True
            )
        }

    def shortest_slot(self) -> int:
        """The length in minutes of the shortest slot."""
        starts = [time for _, time in self.slot_times(1)] + [self.end(1)]
        return min(later - earlier for earlier, later in pairwise(starts))

    def cadences(self, day: int) -> tuple[Trigger, ...]:
        """The evolution triggers due at the end of `day`, daily first."""
        due = [Trigger.DAILY]
        if day % self.weekly_days == 0:
            due.append(Trigger.WEEKLY)
        if day % self.monthly_days == 0:
            due.append(Trigger.MONTHLY)
        return tuple(due)
