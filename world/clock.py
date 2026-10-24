"""Simulated time and how a resident tells it.

Simulated time is an integer count of seconds since 00:00 of day 1. `Clock` advances it in real
time at `speed_active` while any resident is busy (in a model request or a tool execution, as
the runtime reports through `set_busy`) and at `speed_idle` otherwise; `hold` stops it, which
the world does while a checkpoint is written. `ManualClock` has the same interface and moves
only when a test tells it to.

A resident reads a moment by weekday, date and hour ("Tuesday 3 March, 14:05"), never by a day
number: the length of the run is nothing it may infer from the calendar.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta

DAY = 86_400
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip
_HOUR = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


def parse_hour(text: str) -> int:
    """Seconds after midnight of an hour written `HH:MM`; raises ValueError otherwise."""
    match = _HOUR.fullmatch(text)
    if match is None:
        raise ValueError(f"{text!r} is not an hour of the day written HH:MM")
    return int(match[1]) * 3600 + int(match[2]) * 60


def clock_time(t: int) -> str:
    """The hour of `t` as `HH:MM`."""
    seconds = t % DAY
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def calendar_day(t: int) -> int:
    """The 1-based calendar day of `t`."""
    return t // DAY + 1


def tell_date(day: int, start: date) -> str:
    """Calendar day `day` of a town whose day 1 is `start`, e.g. `Tuesday 3 March`."""
    told = start + timedelta(days=day - 1)
    return f"{WEEKDAYS[told.weekday()]} {told.day} {MONTHS[told.month - 1]}"


def tell_moment(t: int, start: date) -> str:
    """`t` as a resident reads it, e.g. `Tuesday 3 March, 14:05`."""
    return f"{tell_date(calendar_day(t), start)}, {clock_time(t)}"


class Clock:
    """Simulated time running in real time at a speed set by load.

    The speed is `speed_active` while any resident is busy, `speed_idle` otherwise, and zero
    while held. Every change of speed re-anchors the clock and wakes the sleepers, which
    re-evaluate how long they still have to wait.
    """

    def __init__(self, start: int, speed_active: float, speed_idle: float) -> None:
        self._active = speed_active
        self._idle = speed_idle
        self._sim = float(start)
        self._real = time.monotonic()
        self._busy: set[str] = set()
        self._held = 0
        self._changed = asyncio.Event()

    @property
    def speed(self) -> float:
        if self._held:
            return 0.0
        return self._active if self._busy else self._idle

    def now(self) -> int:
        return int(self._exact())

    def set(self, t: int) -> None:
        """Move the clock to `t`, as a world does when it starts or is restored."""
        self._sim = float(t)
        self._real = time.monotonic()
        self._notify()

    def set_busy(self, who: str, busy: bool) -> None:
        if (who in self._busy) == busy:
            return
        self._rebase()
        if busy:
            self._busy.add(who)
        else:
            self._busy.discard(who)
        self._notify()

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Stop the clock for the duration of the block."""
        self._rebase()
        self._held += 1
        self._notify()
        try:
            yield
        finally:
            self._rebase()
            self._held -= 1
            self._notify()

    async def sleep_until(self, t: int) -> None:
        """Return once the clock has reached `t`."""
        while (remaining := t - self._exact()) > 0:
            changed, speed = self._changed, self.speed
            try:
                await asyncio.wait_for(changed.wait(), remaining / speed if speed else None)
            except TimeoutError:
                pass

    def _exact(self) -> float:
        return self._sim + (time.monotonic() - self._real) * self.speed

    def _rebase(self) -> None:
        self._sim = self._exact()
        self._real = time.monotonic()

    def _notify(self) -> None:
        self._changed.set()
        self._changed = asyncio.Event()


class ManualClock:
    """A clock for tests: it stands still until `advance` or `advance_to` moves it, and then
    wakes its sleepers in the order of their times, letting the event loop settle after each."""

    def __init__(self, start: int = 0) -> None:
        self._now = start
        self._sleepers: list[tuple[int, int, asyncio.Future[None]]] = []
        self._order = itertools.count()
        self.busy: set[str] = set()
        self.held = 0

    def now(self) -> int:
        return self._now

    def set(self, t: int) -> None:
        self._now = t

    def set_busy(self, who: str, busy: bool) -> None:
        if busy:
            self.busy.add(who)
        else:
            self.busy.discard(who)

    @contextmanager
    def hold(self) -> Iterator[None]:
        self.held += 1
        try:
            yield
        finally:
            self.held -= 1

    async def sleep_until(self, t: int) -> None:
        if t <= self._now:
            return
        future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._sleepers, (t, next(self._order), future))
        await future

    async def advance_to(self, t: int) -> None:
        await settle()
        while self._sleepers and self._sleepers[0][0] <= t:
            due, _, future = heapq.heappop(self._sleepers)
            if future.done():
                continue
            self._now = max(self._now, due)
            future.set_result(None)
            await settle()
        self._now = max(self._now, t)
        await settle()

    async def advance(self, seconds: int) -> None:
        await self.advance_to(self._now + seconds)


async def settle(rounds: int = 50) -> None:
    """Let every task that can run without waiting on time or input run."""
    for _ in range(rounds):
        await asyncio.sleep(0)
