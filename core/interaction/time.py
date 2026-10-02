"""Simulated time: an integer count of minutes since 00:00 on day 1."""

import re
from typing import Annotated

from pydantic import Field

MINUTES_PER_DAY = 24 * 60

SimTime = Annotated[int, Field(ge=0)]
"""Field type for a simulated time; validation rejects negative values."""

_CLOCK = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")


def day_of(time: int) -> int:
    """The 1-based day number of `time`."""
    return _split(time)[0]


def clock_of(time: int) -> str:
    """The time of day of `time` as 24-hour `HH:MM`."""
    minute = _split(time)[1]
    return f"{minute // 60:02d}:{minute % 60:02d}"


def time_at(day: int, clock: str) -> int:
    """The time at `clock` (24-hour `HH:MM`) on 1-based `day`."""
    match = _CLOCK.fullmatch(clock)
    if day < 1 or match is None:
        raise ValueError(f"no simulated time on day {day} at {clock!r}")
    return (day - 1) * MINUTES_PER_DAY + int(match[1]) * 60 + int(match[2])


def format_time(time: int) -> str:
    """`time` for people, e.g. `Day 3 09:00`."""
    return f"Day {day_of(time)} {clock_of(time)}"


def _split(time: int) -> tuple[int, int]:
    if time < 0:
        raise ValueError(f"negative simulated time {time}")
    day, minute = divmod(time, MINUTES_PER_DAY)
    return day + 1, minute
