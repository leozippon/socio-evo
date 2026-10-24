"""A run directory written by a real world living a day, for the viewer's tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from infrastructure.storage import RunDirectory
from simulation.config import ExperimentConfig
from tests.world.conftest import Town, make_agent_dirs, town_config
from world.clock import ManualClock
from world.testing import FakeBackend
from world.world import World


def new_town(root: Path, backend: FakeBackend | None = None) -> tuple[RunDirectory, Town]:
    config = town_config()
    run = RunDirectory(root / "town")
    if not run.root.exists():
        frozen = ExperimentConfig.model_validate(
            {
                "name": "town",
                "llm": {"backend": "scripted", "base_url": "-", "api_key_env": "-", "model": "-"},
                "runtime": {},
                "town": config.model_dump(mode="json"),
                "residents": [
                    {"name": r.name, "background": f"experiments/residents/{r.name.lower()}.md"}
                    for r in config.residents
                ],
                "skills_writable": True,
                "days": 2,
            }
        )
        run = RunDirectory.create(root, "town", config=frozen, code_revision="test")
    make_agent_dirs(run.root, config)
    backend = backend or FakeBackend()
    return run, Town(World(config, run.root, backend, clock=ManualClock()), backend)


async def live_a_day(town: Town, midway: Callable[[], Any] = lambda: None) -> None:
    """Day 1 and the morning of day 2: Mei works, talks, gives and is paid; Tomas fails a task
    and keeps it until it runs out; Aisha stays home and is put to sleep at the forced hour."""
    skills = town.world.residents["Mei"].agent_dir / "skills"
    (skills / "triage.md").write_text("Read the traceback first.\n")
    town.start(until_day=3)
    await town.until("07:00")
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    await town.call("Mei", "start_work")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    await town.until("09:30")
    await town.call("Tomas", "say", text="How is it going?")
    await town.until("09:32")
    await town.call("Mei", "say", text="Nearly done.", to=["Tomas"])
    await town.call("Mei", "give_money", to="Tomas", amount=5)
    await town.call("Mei", "share_skill", to="Tomas", skill="triage")
    await town.until("09:35")
    await town.call("Mei", "leave_conversation")
    midway()
    await town.until("10:00")
    await town.call("Mei", "submit")
    await town.call("Tomas", "start_work")
    await town.call("Tomas", "claim_task", task=2)
    await town.call("Tomas", "write_repo_file", path="a.py", content="half\n")
    await town.call("Tomas", "submit")
    await town.until("10:30")
    await town.call("Mei", "leave_work")
    await town.call("Mei", "go", place="mill-street-house")
    await town.until("22:00")
    await town.call("Tomas", "go", place="college-flat")
    await town.call("Mei", "sleep", until="07:00", journal="I fixed task 1.")
    await town.call("Mei", "rate", resident="Tomas", score=4, reason="Good company.")
    await town.until("23:00")
    await town.call("Tomas", "sleep", until="08:00", journal="Task 2 is hard.")
    town.rest()
    await town.until("18:05", day=2)
