"""A small town for the world's tests: three residents (backgrounds from the old town), the
fake work backend of `world.testing`, and a harness that runs the world on a manual clock and
stands in for the residents' runtimes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agent.port import Percept, ToolResult
from world.clock import DAY, ManualClock, parse_hour, settle
from world.config import TownConfig
from world.testing import FakeBackend
from world.world import World

RESIDENTS = (
    {"name": "Mei", "home": "mill-street-house", "purse": 120},
    {"name": "Tomas", "home": "college-flat", "purse": 180},
    {"name": "Aisha", "home": "mill-street-house", "purse": 30},
)


def town_config(
    mode: str = "town",
    *,
    exchange: dict[str, Any] | None = None,
    shareable: bool = True,
    residents: tuple[dict[str, Any], ...] = RESIDENTS,
    **work: Any,
) -> TownConfig:
    return TownConfig.model_validate(
        {
            "currency": "$",
            "start_date": "2001-01-01",
            "seed": 7,
            "places": [
                {
                    "id": "mill-street-house",
                    "name": "the shared house on Mill Street",
                    "kind": "home",
                },
                {"id": "college-flat", "name": "the flat by the college gates", "kind": "home"},
                {"id": "workshop", "name": "the workshop", "kind": "workplace"},
                {"id": "cafe", "name": "the café on the square", "kind": "social"},
                {"id": "park", "name": "the park", "kind": "social"},
            ],
            "travel_minutes": 10,
            "routes": [{"between": ["workshop", "cafe"], "minutes": 5}],
            "residents": list(residents),
            "work": {
                "split": "train",
                "board_size": 3,
                "payment": 20,
                "living_cost": 30,
                "acceptance_runs": 2,
                "claim_expiry_days": 1,
                "shell_timeout_s": 60,
                "acceptance_timeout_s": 600,
            }
            | work,
            "social": {
                "mode": mode,
                "silence_minutes": 10,
                "skills_shareable": shareable,
                "exchange": exchange,
            },
            "clock": {
                "speed_idle": 100,
                "speed_busy_one": 20,
                "speed_busy_all": 10,
                "idle_minutes": 30,
            },
            "day": {
                "forced_sleep": "02:00",
                "checkpoint": "02:30",
                "forced_wake": "07:00",
                "sleep_at_most": "12:00",
            },
        }
    )


B_EXCHANGE = {"at": "19:00", "place": "cafe", "messages": 3}


def at(hour: str, day: int = 1) -> int:
    """Simulated time of `hour` on calendar day `day`."""
    return (day - 1) * DAY + parse_hour(hour)


@dataclass
class Town:
    """The world running on a manual clock, with stand-ins for the runtimes."""

    world: World
    backend: FakeBackend
    checkpoints: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    heard: dict[str, list[Percept]] = field(default_factory=dict)
    _tasks: list[asyncio.Task[Any]] = field(default_factory=list)

    @property
    def clock(self) -> ManualClock:
        assert isinstance(self.world.clock, ManualClock)
        return self.world.clock

    def start(self, until_day: int = 1) -> asyncio.Task[None]:
        async def on_checkpoint(day: int, state: dict[str, Any]) -> None:
            assert self.clock.held
            self.checkpoints.append((day, state))

        runner = asyncio.create_task(self.world.run(until_day, on_checkpoint))
        self._tasks.append(runner)
        return runner

    async def until(self, hour: str, day: int = 1) -> None:
        await self.clock.advance_to(at(hour, day))

    async def call(self, name: str, tool: str, **args: Any) -> ToolResult:
        result = await self.world.ports[name].call(tool, args)
        await settle()
        return result

    def take(self, name: str) -> list[str]:
        return [percept.text for percept in self.world.ports[name].pending()]

    def rest(self, *names: str) -> None:
        """Stand in for runtimes that only ever wait, keeping what they hear."""

        async def resting(name: str) -> None:
            while True:
                self.heard.setdefault(name, []).extend(await self.world.ports[name].wait())

        for name in names or tuple(self.world.residents):
            self._tasks.append(asyncio.create_task(resting(name)))

    def kinds(self) -> list[str]:
        return [entry["kind"] for entry in self.world.log.entries()]

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


def make_agent_dirs(root: Path, config: TownConfig) -> None:
    for resident in config.residents:
        (root / "agents" / resident.name / "skills").mkdir(parents=True, exist_ok=True)
        (root / "agents" / resident.name / "memory").mkdir(parents=True, exist_ok=True)


@pytest.fixture
async def make_town(tmp_path):
    towns: list[Town] = []

    def make(
        config: TownConfig | None = None, backend: FakeBackend | None = None, root: Path = tmp_path
    ) -> Town:
        config = config or town_config()
        make_agent_dirs(root, config)
        backend = backend or FakeBackend()
        town = Town(World(config, root, backend, clock=ManualClock()), backend)
        towns.append(town)
        return town

    yield make
    for town in towns:
        await town.close()


async def awake_at(town: Town, hour: str = "07:00", day: int = 1) -> None:
    """Start the town and let the residents wake; their first percepts are taken."""
    town.start(until_day=day + 5)
    await town.until(hour, day)
    for name in town.world.residents:
        town.take(name)
