"""A small town for the world's tests: three residents (backgrounds from the old town), two homes,
a shop with a few goods of every kind and effect, the fake work backend of `world.testing`, and a
harness that runs the world on a manual clock and stands in for the residents' runtimes. The
test town has ratings on unless a test turns them off, so that the rating tests keep their
setting; the real town has them off."""

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


GOODS = (
    {"id": "groceries", "name": "groceries", "price": 12, "sold_at": ["store"],
     "kind": "consumable", "uses": 3, "per_day": 1, "effect": "food", "nourishment": 60},
    {"id": "meal", "name": "a meal at the café", "price": 10, "sold_at": ["cafe"],
     "kind": "immediate", "effect": "food", "nourishment": 60},
    {"id": "bicycle", "name": "a bicycle", "price": 50, "sold_at": ["store"],
     "kind": "durable", "effect": "travel", "factor": 0.5},
    {"id": "phone", "name": "a phone", "price": 40, "sold_at": ["store"],
     "kind": "durable", "effect": "messaging", "fee_per_day": 2},
    {"id": "coat", "name": "a coat", "price": 30, "sold_at": ["store"],
     "kind": "durable", "effect": "appearance", "phrase": "in a new coat"},
)  # fmt: skip
"""The test town's catalogue: a good of each kind and each effect."""


def town_config(
    mode: str = "town",
    *,
    exchange: dict[str, Any] | None = None,
    shareable: bool = True,
    ratings: bool = True,
    residents: tuple[dict[str, Any], ...] = RESIDENTS,
    goods: tuple[dict[str, Any], ...] = GOODS,
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
                    "rent": 20,
                    "rooms": 3,
                    "comfort": 0.9,
                },
                {
                    "id": "college-flat",
                    "name": "the flat by the college gates",
                    "kind": "home",
                    "rent": 30,
                    "rooms": 6,
                    "comfort": 1.0,
                },
                {"id": "workshop", "name": "the workshop", "kind": "workplace"},
                {"id": "cafe", "name": "the café on the square", "kind": "social"},
                {"id": "park", "name": "the park", "kind": "social"},
                {"id": "store", "name": "the store", "kind": "shop"},
            ],
            "travel_minutes": 10,
            "routes": [{"between": ["workshop", "cafe"], "minutes": 5}],
            "residents": list(residents),
            "work": {
                "split": "train",
                "board_size": 3,
                "payment": 20,
                "acceptance_runs": 2,
                "claim_expiry_days": 1,
                "shell_timeout_s": 60,
                "acceptance_timeout_s": 600,
            }
            | work,
            "goods": list(goods),
            "social": {
                "mode": mode,
                "silence_minutes": 10,
                "skills_shareable": shareable,
                "ratings": ratings,
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


def stocked(town: Town, days: int = 3) -> None:
    """Give every resident a stock of groceries for `days`, so that a test that crosses midnight
    on its way to something else is not about hunger."""
    for r in town.world.residents.values():
        r.living.things["groceries"] = days
