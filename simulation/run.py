"""Running one town: `run` creates or resumes a run directory, builds the world and one runtime per
resident around one model client, and lives the days until a day's checkpoint.

Everything that can be checked is checked before anything is written: the backgrounds, the
model client and its key, that the model answers a small request, the task split and its
images, and on resumption the configuration frozen in the run, which must be the one given. A
new run then freezes the configuration, creates each resident's directory from its background,
with its memory and skills empty, makes it a git repository, and saves the world's starting
state as day 0.

Every runtime shares the one client. A resident's requests name, as their replica, its place in
the configuration's list of residents, which is frozen with the run: on a server of several
replicas each resident is always served by the same one, and the residents are spread evenly.

Saving day N commits every agent directory at the simulated moment and tags it `day-NN`, then
writes the world's state to `checkpoints/day-NN.json`, so that a checkpoint always has its tags.
A tag left by a save that was killed before its checkpoint is moved when the day is lived again.
The world hands over its state at each daily checkpoint, with every resident asleep and the
clock held. Resuming restores the latest checkpoint into a new world, whose log continues, and
resets every agent directory to that day's tag: what the lost day added to the files, the
session and the trace is gone, and stays in the world log.

A run ends completed after its last day; interrupted after `until_day` short of it, or on
SIGINT or SIGTERM; failed on any error, which is raised. A resident's runtime that ends fails
the run, since the checkpoint would wait for it forever; so does a model that stops answering,
since the runtime gives up after a run of lapses, each of which `run.log` records as a warning.
While the run runs, its manifest records the id of its process, the one a stop signals; every
way out writes the status and clears the id.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agent.directory import AgentDirectory
from agent.runtime import Runtime
from infrastructure.config import load_config
from infrastructure.git import Repository
from infrastructure.llm import (
    LLMCallError,
    LLMError,
    LLMRequest,
    Message,
    Sampling,
    StreamingClient,
    create_client,
)
from infrastructure.storage import RunDirectory, RunStatus, day_tag
from simulation.config import PROJECT_ROOT, ExperimentConfig
from simulation.dry_run import DryRunModel
from world.backend import Backend, SwebenchBackend
from world.clock import tell_moment
from world.config import TownConfig
from world.log import counted_move, lived_days
from world.testing import FakeBackend
from world.world import OnCheckpoint, World

log = logging.getLogger("simulation")

DRY_RUN_TASKS = 250
"""A dry run's pool of tasks: more than a 28-day run of the town draws."""
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
    await _check_model(client, config)
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
            running = directory.update_manifest(
                status=RunStatus.RUNNING, ended_at=None, pid=os.getpid()
            )
            if resume:
                created = running.code_revision
                log.info("resuming %s from day %d at %s", directory.root, day, revision)
                if created != revision:
                    log.warning("the run was created at %s", created)
                world = _resume(directory, config, backend, day)
            else:
                log.info("created %s at %s", directory.root, revision)
                world = _create(directory, config, backend, backgrounds)
            runtimes = {
                r.name: Runtime(
                    AgentDirectory(directory.agent_dir(r.name)),
                    world.ports[r.name],
                    client,
                    config.runtime,
                    replica=index,
                )
                for index, r in enumerate(config.residents)
            }
            checkpoints = _Checkpoints(
                directory, config.town, lambda: world.treasury_told(world.treasury.yesterday)
            )
            await _live(world, runtimes, until, checkpoints)
            status = RunStatus.COMPLETED if until == config.days else RunStatus.INTERRUPTED
        except asyncio.CancelledError:
            status = RunStatus.INTERRUPTED
        except BaseException:
            log.exception("the run failed")
            raise
        finally:
            for sign in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sign)
            directory.update_manifest(status=status, ended_at=datetime.now(UTC), pid=None)
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


async def _check_model(client: StreamingClient, config: ExperimentConfig) -> None:
    """Fail fast, with LLMCallError, unless the model answers one small request at the
    residents' reasoning effort, sent to the last of the replicas the configuration counts,
    which a server with fewer refuses."""
    request = LLMRequest(
        messages=(Message(role="user", content="Say yes."),),
        reasoning_effort=config.runtime.reasoning_effort,
        sampling=Sampling(max_tokens=16),
        replica=config.llm.replicas - 1,
    )
    try:
        await client.stream(request)
    except LLMError as error:
        raise LLMCallError(
            f"the model {config.llm.model} at {config.llm.base_url} did not answer a test "
            f"request: {error}"
        ) from error


def _create(
    directory: RunDirectory, config: ExperimentConfig, backend: Backend, backgrounds: dict[str, str]
) -> World:
    """The world of a new run, with every agent directory created and day 0 saved."""
    for name, background in backgrounds.items():
        path = directory.agent_dir(name)
        AgentDirectory.create(path, background=background)
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
        repository.tag(day_tag(day), force=True)
    path = directory.checkpoint_path(day)
    staging = path.with_suffix(".json.tmp")
    staging.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(staging, path)


class _Checkpoints:
    """The world's `on_checkpoint`: saves the day and logs what it came to, from the day's
    entries in the world log, with the treasury's day as `World.treasury_told` tells it
    (`treasury`). The moves are counted as `world.log.counted_move` names them: sales, dishes and
    gifts."""

    COUNTED = (
        "task_arrived",
        "claim",
        "assign",
        "submission",
        "accepted",
        "sale",
        "dish",
        "examination",
        "treatment",
        "announcement",
        "grant",
        "speech",
        "gift",
        "journal",
        "illness",
        "forced_sleep",
        "bedridden",
    )

    def __init__(
        self, directory: RunDirectory, town: TownConfig, treasury: Callable[[], str]
    ) -> None:
        self._directory, self._town, self._treasury = directory, town, treasury
        self._started = time.monotonic()

    async def __call__(self, day: int, state: dict[str, Any]) -> None:
        _save(self._directory, self._town, day, state)
        counts: Counter[str | None] = Counter()
        for entry in lived_days(self._directory.world_log_path).closed[day].entries:
            counts[entry["kind"]] += 1
            if entry["kind"] == "move":
                counts[counted_move(entry["payload"])] += 1
            counts["accepted"] += entry["kind"] == "verdict" and entry["payload"]["resolved"]
            counts["journal"] += entry["kind"] == "sleep" and bool(entry["payload"]["journal"])
        took = timedelta(seconds=round(time.monotonic() - self._started))
        counted = ", ".join(f"{counts[kind]} {kind}" for kind in self.COUNTED)
        log.info("saved day %d after %s: %s. %s", day, took, counted, self._treasury())
        self._started = time.monotonic()


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
    """The simulation's log, at level INFO, and the runtimes' warnings (their lapses) written to
    `path` as well."""
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    loggers = (log, logging.getLogger("agent"))
    for logger in loggers:
        logger.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        yield
    finally:
        for logger in loggers:
            logger.removeHandler(handler)
        handler.close()
