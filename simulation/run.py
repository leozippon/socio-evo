"""Running one town: `run` creates or resumes a run directory, builds the world and one runtime per
resident around one model client, and lives the days until a day's checkpoint.

Everything that can be checked is checked before anything is written: the backgrounds, the
model client and its key, the task split and its images, and on resumption the configuration
frozen in the run. A new run then freezes the configuration, creates each resident's directory
from its background (memory/town.md seeded with the town's rules as the world tells them to that
resident, memory/people.md with the people it knows already, work.md with a heading), makes it a
git repository, and saves the world's starting state as day 0.

Saving day N commits every agent directory at the simulated moment and tags it `day-NN`, then
writes the world's state to `checkpoints/day-NN.json`, so that a checkpoint always has its tags.
The world hands over its state at each daily checkpoint, with every resident asleep and the
clock held. Resuming restores the latest checkpoint into a new world, whose log continues, and
resets every agent directory to that day's tag: what the lost day added to the files, the
session and the trace is gone, and stays in the world log.

A run ends completed after its last day; interrupted after `until_day` short of it, or on
SIGINT or SIGTERM; failed on any error, which is raised. A resident's runtime that ends fails
the run, since the checkpoint would wait for it forever. Every way out writes the status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agent.directory import AgentDirectory
from agent.runtime import Runtime
from infrastructure.config import load_config
from infrastructure.git import Repository
from infrastructure.llm import StreamingClient, create_client
from infrastructure.storage import RunDirectory, RunStatus, day_tag, read_jsonl
from simulation.config import PROJECT_ROOT, ExperimentConfig
from simulation.dry_run import DryRunModel
from world.backend import Backend, SwebenchBackend
from world.clock import tell_moment
from world.config import TownConfig
from world.rules import Rules
from world.testing import FakeBackend
from world.world import OnCheckpoint, World

log = logging.getLogger("simulation")

DRY_RUN_TASKS = 56
"""The tasks of a dry run's board, as many as the training pool."""
DRY_RUN_SPEEDS = {"speed_idle": 10_000.0, "speed_busy_one": 600.0, "speed_busy_all": 600.0}
"""A dry run's clock: a day in seconds."""


async def run(
    config: ExperimentConfig,
    runs_root: Path,
    *,
    resume: bool = False,
    until_day: int | None = None,
    dry_run: bool = False,
) -> tuple[Path, RunStatus]:
    """Create, or resume, the run of `config` in `runs_root/<name>` and live it until the
    checkpoint of `until_day` (the last day if None). A dry run is the run of `as_dry_run(config)`
    on the dry-run model and the fake backend. Returns the run's root and its final status;
    raises, with the run marked failed, on any error after the run directory exists."""
    if dry_run:
        config = as_dry_run(config)
    until = config.days if until_day is None else until_day
    if not 1 <= until <= config.days:
        raise ValueError(f"until_day must be from 1 to {config.days}, not {until}")
    backgrounds = {
        r.name: r.background_path.read_text(encoding="utf-8").strip() + "\n"
        for r in config.residents
    }
    client = _client(config, dry_run)
    backend: Backend = FakeBackend(DRY_RUN_TASKS) if dry_run else SwebenchBackend()
    backend.require_images(backend.load_split(config.town.work.split))
    revision = code_revision()
    if resume:
        directory = RunDirectory.open(runs_root / config.name)
        if load_config(directory.config_path, ExperimentConfig) != config:
            raise ValueError(f"the configuration differs from the one frozen in {directory.root}")
        day = directory.latest_checkpoint()
        if day is None:
            raise FileNotFoundError(f"{directory.root} has no checkpoint to resume from")
        if day >= until:
            raise ValueError(f"{directory.root} has already saved day {day}")
    else:
        directory = RunDirectory.create(
            runs_root, config.name, config=config, code_revision=revision
        )

    status = RunStatus.FAILED
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    assert task is not None
    with _logging(directory.run_log_path):
        try:
            for sign in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sign, task.cancel)
            if resume:
                directory.update_manifest(status=RunStatus.RUNNING, ended_at=None)
                created = directory.read_manifest().code_revision
                log.info("resuming %s from day %d at %s", directory.root, day, revision)
                if created != revision:
                    log.warning("the run was created at %s", created)
                world = _resume(directory, config, backend, day)
            else:
                log.info("created %s at %s", directory.root, revision)
                world = _create(directory, config, backend, backgrounds)
            runtimes = {
                r.name: Runtime(
                    AgentDirectory(
                        directory.agent_dir(r.name), skills_writable=config.skills_writable
                    ),
                    world.ports[r.name],
                    client,
                    config.runtime,
                )
                for r in config.residents
            }
            await _live(world, runtimes, until, _Checkpoints(directory, config.town))
            status = RunStatus.COMPLETED if until == config.days else RunStatus.INTERRUPTED
        except asyncio.CancelledError:
            status = RunStatus.INTERRUPTED
        except BaseException:
            log.exception("the run failed")
            raise
        finally:
            for sign in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sign)
            directory.update_manifest(status=status, ended_at=datetime.now(UTC))
            log.info("%s %s", directory.root, status.value)
    return directory.root, status


def as_dry_run(config: ExperimentConfig) -> ExperimentConfig:
    """`config` as experiment `<name>-dry-run`, answered by the dry-run model, on a clock that
    lives a day in seconds."""
    town = config.town
    return config.model_copy(
        update={
            "name": f"{config.name}-dry-run",
            "llm": config.llm.model_copy(update={"backend": "scripted"}),
            "town": town.model_copy(update={"clock": town.clock.model_copy(update=DRY_RUN_SPEEDS)}),
        }
    )


def code_revision() -> str:
    """The project's git commit, suffixed `-dirty` if the work tree has changes."""
    repository = Repository(PROJECT_ROOT)
    return repository.head() + ("-dirty" if repository.has_changes() else "")


def _client(config: ExperimentConfig, dry_run: bool) -> StreamingClient:
    """The model client every runtime shares: the dry-run model, or the configured endpoint."""
    if dry_run:
        return create_client(config.llm, DryRunModel(config.town))
    return create_client(config.llm)


def _create(
    directory: RunDirectory, config: ExperimentConfig, backend: Backend, backgrounds: dict[str, str]
) -> World:
    """The world of a new run, with every agent directory created and day 0 saved."""
    rules = Rules(config.town)
    for name, background in backgrounds.items():
        path = directory.agent_dir(name)
        AgentDirectory.create(
            path,
            background=background,
            town=rules.text(name) + "\n",
            people=rules.people_notes(name),
            work="# Work\n",
            skills_writable=config.skills_writable,
        )
        Repository.init(path, user_name=name, user_email=f"{name.lower()}@town.invalid")
    world = World(config.town, directory.root, backend)
    _save(directory, config.town, 0, world.snapshot())
    return world


def _resume(directory: RunDirectory, config: ExperimentConfig, backend: Backend, day: int) -> World:
    """The world of the run back at the checkpoint of `day`, every agent directory with it."""
    for resident in config.residents:
        Repository(directory.agent_dir(resident.name)).reset_hard(day_tag(day))
    world = World(config.town, directory.root, backend)
    world.restore(json.loads(directory.checkpoint_path(day).read_text(encoding="utf-8")))
    return world


def _save(directory: RunDirectory, town: TownConfig, day: int, state: dict[str, Any]) -> None:
    """Commit and tag every agent directory as of day `day`, then write the checkpoint."""
    t = state["time"]
    moment = datetime.combine(town.start_date, datetime.min.time(), UTC) + timedelta(seconds=t)
    message = f"{day_tag(day)}: {tell_moment(t, town.start_date)}"
    for resident in town.residents:
        repository = Repository(directory.agent_dir(resident.name))
        repository.commit(message, date=moment, allow_empty=True)
        repository.tag(day_tag(day))
    path = directory.checkpoint_path(day)
    staging = path.with_suffix(".json.tmp")
    staging.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(staging, path)


class _Checkpoints:
    """The world's `on_checkpoint`: saves the day and logs what it came to."""

    COUNTED = ("claim", "submission", "accepted", "speech", "gift", "skill_shared", "forced_sleep")

    def __init__(self, directory: RunDirectory, town: TownConfig) -> None:
        self._directory, self._town = directory, town
        self._seen = self._last_seq()
        self._started = time.monotonic()

    async def __call__(self, day: int, state: dict[str, Any]) -> None:
        _save(self._directory, self._town, day, state)
        counts: Counter[str] = Counter()
        for entry in read_jsonl(self._directory.world_log_path):
            if entry["seq"] > self._seen:
                counts[entry["kind"]] += 1
                counts["accepted"] += entry["kind"] == "verdict" and entry["payload"]["resolved"]
        self._seen = self._last_seq()
        purses = {name: saved["purse"] for name, saved in state["residents"].items()}
        took = timedelta(seconds=round(time.monotonic() - self._started))
        counted = ", ".join(f"{counts[kind]} {kind}" for kind in self.COUNTED)
        log.info("saved day %d after %s: %s; purses %s", day, took, counted, purses)
        self._started = time.monotonic()

    def _last_seq(self) -> int:
        path = self._directory.world_log_path
        return max((entry["seq"] for entry in read_jsonl(path)), default=0) if path.exists() else 0


async def _live(
    world: World, runtimes: dict[str, Runtime], until: int, on_checkpoint: OnCheckpoint
) -> None:
    """Run the world until the checkpoint of `until` while every runtime lives; a runtime that
    ends, by an error or otherwise, ends the run with an error."""
    town = asyncio.create_task(world.run(until, on_checkpoint), name="world")
    lives = {asyncio.create_task(rt.run(), name=name): name for name, rt in runtimes.items()}
    try:
        await asyncio.wait({town, *lives}, return_when=asyncio.FIRST_COMPLETED)
        for life, name in lives.items():
            if life.done():
                error = None if life.cancelled() else life.exception()
                raise RuntimeError(f"the runtime of {name} ended") from error
        town.result()
    finally:
        for task in (town, *lives):
            task.cancel()
        await asyncio.gather(town, *lives, return_exceptions=True)


@contextmanager
def _logging(path: Path) -> Iterator[None]:
    """The simulation's log written to `path` as well, at level INFO."""
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        yield
    finally:
        log.removeHandler(handler)
        handler.close()
