"""The world through a real workspace: a claim, commands and files in the container, the night's
closing with the changes kept, their reapplication the next morning at home, and an official
verdict. Skipped unless `tasks.swebench` imports, Docker runs and the task's image is pulled."""

from __future__ import annotations

import asyncio
import shutil
import subprocess

import pytest

from tests.world.conftest import RESIDENTS, Town, make_agent_dirs, opening, stocked, town_config
from world.backend import SwebenchBackend
from world.clock import ManualClock
from world.world import World

pytestmark = pytest.mark.docker
INSTANCE = "django__django-11276"


class OneTask(SwebenchBackend):
    """The real backend with a board of one task."""

    def __init__(self, task) -> None:
        self.task = task

    def load_split(self, name: str):
        return [self.task]


def pulled_task():
    try:
        from tasks.swebench.dataset import load_split
        from tasks.swebench.images import local
    except ImportError as error:
        pytest.skip(f"tasks.swebench does not import: {error}")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode != 0:
        pytest.skip("Docker is not running")
    task = next(task for task in load_split("train") if task.instance_id == INSTANCE)
    if not local(task.image):
        pytest.skip(f"{task.image} is not pulled")
    return task


async def test_a_resident_works_a_real_task_across_a_night(tmp_path):
    task = pulled_task()
    config = town_config(residents=(dict(RESIDENTS[0], purse=50),))
    make_agent_dirs(tmp_path, config)
    town = Town(World(config, tmp_path, OneTask(task), clock=ManualClock()), None)
    opening(town.world)
    try:
        town.start(until_day=3)
        stocked(town)
        await town.until("07:00")
        await town.call("Mei", "go", place="workshop")
        await town.until("09:00")
        claimed = await town.call("Mei", "claim_task", task=1)
        assert claimed.text.startswith("You sat down to work and claimed task 1, in django/django")
        status = await town.call("Mei", "shell", command="git status --short && echo done")
        assert status.text.endswith("done\nExit code 0.")
        await town.call("Mei", "write_repo_file", path="probe_note.txt", content="kept\n")
        assert (await town.call("Mei", "read_repo_file", path="probe_note.txt")).text == "kept\n"
        await town.call("Mei", "leave_work")
        town.rest()
        await town.until("02:30", day=2)
        async with asyncio.timeout(300):  # the checkpoint closes the container in real time
            while not town.checkpoints:
                await asyncio.sleep(0.2)
        assert town.world.board.claims["Mei"].workspace is None
        assert "+kept" in town.world.board.claims["Mei"].diff

        await town.until("08:50", day=2)
        await town.call("Mei", "go", place="workshop")
        await town.until("09:00", day=2)  # back at the workshop: the workspace opens again
        reopened = await town.call("Mei", "read_repo_file", path="probe_note.txt")
        assert reopened.text == "You sat down to work. It is 09:00.\nkept\n"
        verdict = await town.call("Mei", "submit")
        assert verdict.text.startswith("Not accepted: ")
        assert "test_" not in verdict.text and "::" not in verdict.text
    finally:
        await town.close()
        opened = [claim.workspace for claim in town.world.board.claims.values()]
        for workspace in [*filter(None, opened), *town.world.board.orphans]:
            await workspace.close()
