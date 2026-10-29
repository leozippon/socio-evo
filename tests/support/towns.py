"""A small town for the world's tests: three residents, programmers at the workshop (the office),
the shopkeeper and the chef that `TRADES` adds for the tests of the store and the café (the
restaurant), and the doctor and the mayor that `CARE` adds for those of the clinic (the hospital)
and the hall; two homes and a park; a catalogue of items with ready food, two ingredients, a
durable of each effect and two dishes; the real town's needs, with no illness unless a test asks
for it; no tax unless a test sets one; a treasury of $1000 that takes the rent from a purse above
$10 and pays the mayor $30 a day; a client paying $50 a task, a fifth of it to a team leader if
the town has one; no task arriving unless a test schedules it (`opening` makes the whole pool
arrive at 08:00 on the first day, as the towns of the world tests' `make_town` have it); the fake
work backend of `world.testing`; and a harness that runs the world on a manual clock and stands
in for the residents' runtimes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.port import Percept, ToolResult
from world.clock import DAY, ManualClock, parse_hour, settle
from world.config import TownConfig
from world.testing import FakeBackend, FakeTask
from world.world import World

RESIDENTS = (
    {"name": "Mei", "home": "mill-street-house", "occupation": "programmer", "purse": 120},
    {"name": "Tomas", "home": "college-flat", "occupation": "programmer", "purse": 180},
    {"name": "Aisha", "home": "mill-street-house", "occupation": "programmer", "purse": 30},
)
TRADES = (
    {"name": "Olga", "home": "college-flat", "occupation": "shopkeeper", "purse": 100},
    {"name": "Jonas", "home": "college-flat", "occupation": "chef", "purse": 100},
)
"""The shopkeeper and the chef, for the tests of the store and the café."""
CARE = (
    {"name": "Lucia", "home": "college-flat", "occupation": "doctor", "purse": 100},
    {"name": "Vera", "home": "college-flat", "occupation": "mayor", "purse": 100},
)
"""The doctor and the mayor, for the tests of the clinic and the hall."""
OCCUPATIONS = (
    {"id": "programmer", "title": "a programmer", "workplace": "workshop"},
    {"id": "team-leader", "title": "the team leader", "workplace": "workshop"},
    {"id": "chef", "title": "the chef", "workplace": "cafe"},
    {"id": "shopkeeper", "title": "the shopkeeper", "workplace": "store"},
    {"id": "doctor", "title": "the doctor", "workplace": "clinic"},
    {"id": "mayor", "title": "the mayor", "workplace": "hall", "duty": "anywhere", "salary": 30},
)

ITEMS = (
    {"id": "bread", "name": "bread", "wholesale": 2, "price": 4, "kind": "consumable",
     "effect": "food", "nourishment": 34},
    {"id": "eggs", "name": "eggs", "wholesale": 1, "price": 2, "kind": "consumable",
     "effect": "food", "nourishment": 0},
    {"id": "vegetables", "name": "vegetables", "wholesale": 2, "price": 3, "kind": "consumable",
     "effect": "food", "nourishment": 0},
    {"id": "bicycle", "name": "a bicycle", "wholesale": 30, "price": 50, "kind": "durable",
     "effect": "travel", "factor": 0.5},
    {"id": "phone", "name": "a phone", "wholesale": 25, "price": 40, "kind": "durable",
     "effect": "messaging", "fee_per_day": 2},
    {"id": "coat", "name": "a coat", "wholesale": 20, "price": 30, "kind": "durable",
     "effect": "appearance", "phrase": "in a new coat"},
    {"id": "omelette", "name": "an omelette", "ingredients": {"eggs": 2, "vegetables": 1},
     "price": 10, "kind": "consumable", "effect": "food", "nourishment": 100, "perishes": True},
    {"id": "soup", "name": "vegetable soup", "ingredients": {"vegetables": 2}, "price": 8,
     "kind": "consumable", "effect": "food", "nourishment": 100, "perishes": True},
)  # fmt: skip
"""The test town's catalogue: ready food, two ingredients and a durable of each effect from the
supplier, and two dishes from the kitchen."""
STOCK = {"bread": 10, "eggs": 10, "vegetables": 10, "bicycle": 1, "phone": 2, "coat": 1}

NEEDS = {
    "satiety": {
        "per_hour": 3.75,
        "bands": [
            {"floor": 65, "name": "well fed"},
            {"floor": 35, "name": "a little hungry"},
            {"floor": 10, "name": "hungry"},
            {"floor": 0, "name": "starving"},
        ],
    },
    "energy": {
        "awake_per_hour": 1.5,
        "work_per_hour": 5,
        "walk_per_minute": 0.1,
        "sleep_per_hour": 12,
        "rested_at_least": 50,
        "bands": [
            {"floor": 65, "name": "fresh"},
            {"floor": 35, "name": "a little tired"},
            {"floor": 15, "name": "tired"},
            {"floor": 0, "name": "exhausted"},
        ],
    },
    "health": {
        "starving": 15,
        "exhausted": 5,
        "poor_home": 2,
        "recovery": 5,
        "illness": {
            "chance": 0,
            "run_down": 0,
            "unwell": 0,
            "poor_home": 0,
            "per_night": 5,
            "nights": 7,
        },  # fmt: skip
        "bands": [
            {"floor": 65, "name": "in good health"},
            {"floor": 35, "name": "run down"},
            {"floor": 10, "name": "unwell", "seen": "looking unwell"},
            {"floor": 0, "name": "gravely ill", "seen": "looking gravely ill"},
        ],
    },
}
"""The test town's needs: the real town's rates and bands, and an illness that never comes."""


def town_config(
    *,
    residents: tuple[dict[str, Any], ...] = RESIDENTS,
    items: tuple[dict[str, Any], ...] = ITEMS,
    needs: dict[str, Any] = NEEDS,
    tax: float = 0,
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
                {"id": "workshop", "name": "the workshop", "kind": "office"},
                {"id": "cafe", "name": "the café on the square", "kind": "restaurant"},
                {"id": "park", "name": "the park", "kind": "social"},
                {"id": "store", "name": "the store", "kind": "store"},
                {"id": "clinic", "name": "the clinic", "kind": "hospital"},
                {"id": "hall", "name": "the hall", "kind": "hall"},
            ],
            "travel_minutes": 10,
            "routes": [{"between": ["workshop", "cafe"], "minutes": 5}],
            "residents": list(residents),
            "occupations": list(OCCUPATIONS),
            "treasury": {"start": 1000, "spares": 10},
            "tax": tax,
            "work": {
                "split": "train",
                "tasks_a_day": 0,
                "arrive_from": "08:00",
                "arrive_until": "18:00",
                "expiry_days": 1,
                "payment": 50,
                "leader_share": 0.2,
                "acceptance_runs": 2,
                "shell_timeout_s": 60,
                "acceptance_timeout_s": 600,
            }
            | work,
            "items": list(items),
            "store": {"stock": STOCK},
            "hospital": {"examination": 10, "treatment": 30, "restores": 25},
            "needs": needs,
            "social": {"silence_minutes": 10},
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
                "delivery": "08:00",
                "sleep_at_most": "12:00",
            },
        }
    )


def backend_of(repos: dict[str, int]) -> FakeBackend:
    """The fake backend with tasks of the repositories given, so many of each, numbered from 1 in
    the order given."""
    backend = FakeBackend(0)
    each = [repo for repo, tasks in repos.items() for _ in range(tasks)]
    backend.tasks = [
        FakeTask(
            f"{repo.replace('/', '__')}-{n}", repo, f"Problem {n} goes wrong.\nDetails of {n}."
        )
        for n, repo in enumerate(each, 1)
    ]
    return backend


def at(hour: str, day: int = 1) -> int:
    """Simulated time of `hour` on calendar day `day`."""
    return (day - 1) * DAY + parse_hour(hour)


def opening(world: World) -> None:
    """Make the whole pool arrive at 08:00 on the first day: a world not yet running whose
    arrivals were none."""
    world.board.schedule = [at("08:00")] * len(world.board.tasks)


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


async def awake_at(town: Town, hour: str = "07:00", day: int = 1) -> None:
    """Start the town and let the residents wake; their first percepts are taken."""
    town.start(until_day=day + 5)
    await town.until(hour, day)
    for name in town.world.residents:
        town.take(name)


def stocked(town: Town, days: int = 3) -> None:
    """Give every resident bread for `days`, three helpings a day, so that a test that crosses
    midnight on its way to something else is not about hunger."""
    for r in town.world.residents.values():
        r.inventory.items["bread"] = days * 3
