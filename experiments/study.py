"""Run a study: the arms of an experimental design, each over the same seeds.

    python -m experiments.study STUDY [--arms ARM ...] [--seeds N ...] [--workers 4]
                                      [--runs-root runs] [--until-day N] [--dry-run]
                                      [--status]

A study file (YAML) names a base experiment configuration, overlays and arms:

    name: trust
    base: ../configs/town.yaml          # relative to the study file
    seeds: [0, 1, 2]
    overlays:
      scarce: {environment: {conditions: {living_cost: 30}}}
      solo: {residents: [Mei]}
    arms:
      selection-scarce: [scarce]

An arm's configuration is the base with its overlays merged in, in order: mappings merge key
by key and anything else is replaced; an overlay's `residents` keeps only the named residents,
leaving the others, their places in their homes and their circumstances out. The arm runs as
experiment `<study>-<arm>`, and its resolved configuration is frozen into each of its runs.

Every arm and seed runs in a process of its own, using `experiments.run`, at most `--workers`
at a time (the model server batches their concurrent requests): a run that does not exist is
created, a completed one skipped, and any other resumed from its latest checkpoint.
`--until-day` stops runs after that day, to be resumed later. A table of every run's state is
printed at the end, or alone with `--status`; the exit status is 1 if a run failed.
`--dry-run` answers with the scripted responder, as experiments `<study>-<arm>-dry-run`.

A seed is matched across arms as far as their rules let it be. The jobs posted at a moment
are drawn from the seed and the moment alone, the k-th job of each size from a generator of
its own, so every arm posts the same jobs with the same clients, wherever it posts them: an
arm that posts fewer posts a prefix of the same stream, and job numbers differ only where the
counts do. Everything else, the lots for simultaneous requests and pairs, the order of turns
and of moves, the discovery of faults, comes from the run's one generator, seeded alike in
every arm, and stays matched only until what residents do makes the arms diverge.
"""

import argparse
import asyncio
import copy
import logging
import multiprocessing
import sys
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, JsonValue, NonNegativeInt, ValidationError, model_validator

from experiments.config import ExperimentConfig
from experiments.run import as_dry_run, run
from infrastructure.config import ConfigError, StrictModel, describe_validation_error, load_config
from infrastructure.storage import RunDirectory


class StudyConfig(StrictModel):
    """A study: arms, each the `base` configuration with the named overlays merged in, run over
    `seeds`."""

    name: str = Field(pattern=r"^[\w.-]+$")
    base: str
    seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)
    overlays: dict[str, dict[str, JsonValue]] = {}
    arms: dict[str, tuple[str, ...]] = Field(min_length=1)

    @model_validator(mode="after")
    def _known_overlays(self) -> "StudyConfig":
        for arm, overlays in self.arms.items():
            if unknown := sorted(set(overlays) - self.overlays.keys()):
                raise ValueError(f"arm {arm} names unknown overlays {unknown}")
        return self


def load_study(path: Path) -> tuple[StudyConfig, dict[str, ExperimentConfig]]:
    """The study at `path` and the configuration of each of its arms; raises ConfigError for
    an invalid study or arm."""
    study = load_config(path, StudyConfig)
    base = yaml.safe_load((path.parent / study.base).read_text(encoding="utf-8"))
    arms = {}
    for arm, names in study.arms.items():
        data = copy.deepcopy(base)
        try:
            for name in names:
                data = overlay(data, study.overlays[name])
            arms[arm] = ExperimentConfig.model_validate({**data, "name": f"{study.name}-{arm}"})
        except ValidationError as error:
            raise ConfigError(f"{path}: arm {arm}: {describe_validation_error(error)}") from error
        except ValueError as error:
            raise ConfigError(f"{path}: arm {arm}: {error}") from error
    return study, arms


def overlay(data: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """`data` with `changes` merged in: mappings key by key, anything else replaced, and
    `residents` keeping only the residents it names."""
    changes = dict(changes)
    if (kept := changes.pop("residents", None)) is not None:
        data = _only(data, set(kept))
    return _merge(data, changes)


def _merge(base: Any, changes: Any) -> Any:
    if not (isinstance(base, dict) and isinstance(changes, dict)):
        return copy.deepcopy(changes)
    return {**base, **{key: _merge(base.get(key), value) for key, value in changes.items()}}


def _only(data: dict[str, Any], kept: set[str]) -> dict[str, Any]:
    names = {seed["profile"]["name"] for seed in data["agents"]}
    if unknown := sorted(kept - names):
        raise ValueError(f"no residents called {unknown}")
    environment = data["environment"]
    return {
        **data,
        "agents": [seed for seed in data["agents"] if seed["profile"]["name"] in kept],
        "environment": {
            **environment,
            "places": [
                {**place, "residents": [r for r in place.get("residents", []) if r in kept]}
                for place in environment["places"]
            ],
            "circumstances": {
                name: own
                for name, own in environment.get("circumstances", {}).items()
                if name in kept
            },
        },
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m experiments.study", description="Run every arm of a study over seeds."
    )
    parser.add_argument("study", type=Path, help="study file (YAML)")
    parser.add_argument("--arms", nargs="+", help="only these arms")
    parser.add_argument("--seeds", type=int, nargs="+", help="instead of the study's seeds")
    parser.add_argument("--workers", type=int, default=4, help="runs at a time")
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--until-day", type=int, help="stop each run after this day")
    parser.add_argument("--dry-run", action="store_true", help="use the scripted responder")
    parser.add_argument("--status", action="store_true", help="only print the runs' states")
    args = parser.parse_args(argv)
    if args.workers < 1 or (args.until_day is not None and args.until_day < 1):
        parser.error("--workers and --until-day must be at least 1")

    study, configs = load_study(args.study)
    if unknown := sorted(set(args.arms or ()) - configs.keys()):
        parser.error(f"unknown arms {unknown}; the study has {sorted(configs)}")
    configs = {arm: configs[arm] for arm in args.arms or configs}
    if args.dry_run:
        configs = {arm: as_dry_run(config) for arm, config in configs.items()}
    grid = [(arm, seed) for arm in configs for seed in args.seeds or study.seeds]
    failed = [] if args.status else execute(grid, configs, args.runs_root, args)
    print(table(grid, configs, args.runs_root))
    if failed:
        raise SystemExit(1)


def execute(
    grid: Sequence[tuple[str, int]],
    configs: dict[str, ExperimentConfig],
    runs_root: Path,
    args: argparse.Namespace,
) -> list[tuple[str, int]]:
    """Run every arm and seed of `grid` that is not completed, each in a process of its own;
    returns those that failed."""
    pending = [
        (arm, seed) for arm, seed in grid if state(configs[arm], seed, runs_root) != "completed"
    ]
    failed = []
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(args.workers, mp_context=context, max_tasks_per_child=1) as pool:
        futures = {
            pool.submit(
                _run,
                configs[arm].model_dump(mode="json"),
                seed,
                str(runs_root),
                args.until_day,
            ): (arm, seed)
            for arm, seed in pending
        }
        for future in as_completed(futures):
            arm, seed = futures[future]
            try:
                print(f"{arm} seed {seed}: {future.result()}", flush=True)
            except Exception as error:
                print(f"{arm} seed {seed}: failed: {error!r}", file=sys.stderr, flush=True)
                failed.append((arm, seed))
    return failed


def _run(config: dict[str, Any], seed: int, runs_root: str, until_day: int | None) -> str:
    """Create or resume, and run, one run of `config` with `seed`, in this process."""
    logging.basicConfig(format="%(asctime)s %(message)s")
    logging.getLogger("runtime").setLevel(logging.INFO)
    experiment = ExperimentConfig.model_validate(config)
    resume = RunDirectory.root_of(Path(runs_root), experiment.name, seed).exists()
    _, status = asyncio.run(
        run(experiment, seed, Path(runs_root), resume=resume, until_day=until_day)
    )
    return str(status)


def state(config: ExperimentConfig, seed: int, runs_root: Path) -> str:
    """The status of the run of `config` with `seed`, or `not started`."""
    root = RunDirectory.root_of(runs_root, config.name, seed)
    return str(RunDirectory(root).read_manifest().status) if root.exists() else "not started"


def table(
    grid: Sequence[tuple[str, int]], configs: dict[str, ExperimentConfig], runs_root: Path
) -> str:
    """One line per run: arm, seed, status and the last day checkpointed of all its days."""
    rows = [("arm", "seed", "status", "days")]
    for arm, seed in grid:
        config = configs[arm]
        latest = RunDirectory(RunDirectory.root_of(runs_root, config.name, seed))
        checkpoint = latest.latest_checkpoint() if latest.root.exists() else None
        day = 0 if checkpoint is None else int(checkpoint.stem.removeprefix("day-"))
        status = state(config, seed, runs_root)
        rows.append((arm, str(seed), status, f"{day}/{config.simulation.days}"))
    widths = [max(len(row[column]) for row in rows) for column in range(4)]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )


if __name__ == "__main__":
    main()
