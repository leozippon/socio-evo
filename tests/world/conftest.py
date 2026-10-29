"""The world tests' fixture: towns of `tests.support.towns` on a manual clock, closed after the
test."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.towns import Town, make_agent_dirs, opening, town_config
from world.clock import ManualClock
from world.config import TownConfig
from world.testing import FakeBackend
from world.world import World


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
        opening(town.world)
        towns.append(town)
        return town

    yield make
    for town in towns:
        await town.close()
