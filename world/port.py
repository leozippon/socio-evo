"""A resident's port: its reach into the world, as `agent.port.WorldPort` declares it, its inbox,
and the percepts that reach it while its runtime waits: whatever the world delivers to it, the
hour within its idle interval or once the minutes it asked to wait are over, and that a wait was
cut short; what is told to it while it sleeps is held until it wakes.
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING, Any

from agent.port import Percept, ToolResult, ToolSpec
from world.clock import clock_time
from world.events import Sleep
from world.telling import counted

if TYPE_CHECKING:
    from world.world import Resident, World


class ResidentPort:
    """One resident's reach into the world: `agent.port.WorldPort`, and the owner of its inbox.

    `wait` returns as soon as a percept is pending. While the resident is awake it is told
    something within the idle interval of simulated time (or within the minutes it asked to
    wait, and if something else ends that wait sooner, that it did); while it sleeps nothing
    reaches it until it wakes, and what was told to it meanwhile is held and delivered with the
    wake-up. A resident in bed whose runtime waits with nothing pending falls asleep."""

    def __init__(self, world: World, resident: Resident) -> None:
        self._world = world
        self._resident = resident
        self._inbox: list[Percept] = []
        self.held: list[Percept] = []
        self._arrived = asyncio.Event()
        self._interrupt = asyncio.Event()
        self.waiting = False

    def rules(self) -> str:
        """The rules as they stand: who lives where now, and so one's own home and rent."""
        return self._world.rules.text(self._resident.name, self._world.homes())

    def tool_specs(self) -> list[ToolSpec]:
        """The tools the resident's event offers at its place now (`World.usable`)."""
        return self._world.usable(self._resident)

    def knows(self, name: str) -> bool:
        return self._world.knows(self._resident, name)

    @property
    def asleep(self) -> bool:
        return self._resident.suspended

    def situation(self) -> str:
        return self._world.situation(self._resident)

    def sim_time(self) -> int:
        return self._world.clock.now()

    def set_busy(self, busy: bool) -> None:
        self._world.clock.set_busy(self._resident.name, busy)

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        return await self._world.call(self._resident, name, args)

    def pending(self) -> list[Percept]:
        taken, self._inbox = self._inbox, []
        self._arrived.clear()
        self._interrupt.clear()
        return taken

    async def wait(self) -> list[Percept]:
        world, r = self._world, self._resident
        self.waiting = True
        asked, began, armed = r.wait_minutes, world.clock.now(), False
        try:
            if not self._inbox:
                if isinstance(r.base, Sleep) and not r.base.suspended:
                    world.fall_asleep(r)
                if not r.suspended:
                    self._arm_tick()
                    armed = True
            world.rest_changed()
            await self._arrived.wait()
            if asked and (not armed or r.tick is not None):  # news came before the minutes
                self._end_wait(began)
            return self.pending()
        finally:
            self.waiting = False
            r.wait_minutes = None
            self.disarm_tick()
            world.rest_changed()

    @property
    def interrupt(self) -> asyncio.Event:
        return self._interrupt

    @property
    def has_pending(self) -> bool:
        return bool(self._inbox)

    def deliver(self, percept: Percept, interrupt: bool) -> None:
        if self._resident.suspended:
            self.held.append(percept)
            return
        self._inbox.append(percept)
        self._arrived.set()
        if interrupt:
            self._interrupt.set()

    def release(self) -> None:
        """Deliver what was held while the resident slept."""
        held, self.held = self.held, []
        for percept in held:
            self.deliver(percept, False)

    def _arm_tick(self) -> None:
        """Make sure the resident hears something within its idle interval, or within the
        minutes it asked to wait."""
        world, r = self._world, self._resident
        asked = r.wait_minutes
        minutes = asked or world.config.clock.idle_minutes
        r.wait_minutes = None
        r.tick = world.at(world.clock.now() + minutes * 60, partial(self._tick, asked))

    def disarm_tick(self) -> None:
        r = self._resident
        if r.tick is not None:
            r.tick.cancel()
            r.tick = None

    def _end_wait(self, began: int) -> None:
        """The resident's wait for the minutes it asked, begun at `began`, was ended sooner by
        what it has just been told: it is told so, and the time, after that, unless not a minute
        went by, when what it was told came as it began to wait, or before (news that came while
        it was still deciding to wait), and there was no wait to speak of."""
        world, r = self._world, self._resident
        now = world.clock.now()
        if now - began < 60:
            return
        text = f"That ended the wait you began at {clock_time(began)}; it is now {clock_time(now)}."
        world.record(
            "time",
            lambda w: text,
            actor=r,
            audience=[r],
            payload={"waited_minutes": (now - began) // 60, "cut_short": True},
        )

    def _tick(self, asked: int | None) -> None:
        world, r = self._world, self._resident
        r.tick = None
        hour = clock_time(world.clock.now())
        text = (
            f"You waited {counted(asked, 'minute')}; it is now {hour}."
            if asked
            else f"It is now {hour}."
        )
        world.record(
            "time", lambda w: text, actor=r, audience=[r], payload={"waited_minutes": asked}
        )
