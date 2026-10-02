"""Run an experiment: one independent society run per seed.

    python -m experiments.run CONFIG --seeds 0 1 2 [--runs-root runs] [--resume]
                                     [--until-day N] [--dry-run]

Each seed runs in `<runs-root>/<experiment>/seed-NNNN`, with every model call recorded in
its `llm_calls.jsonl`. Creating a run that exists fails; `--resume` continues a run from its
latest checkpoint and requires the configuration frozen in it. `--until-day` stops after
that day, leaving the run interrupted and resumable. `--dry-run` replaces the model with the
scripted responder of `experiments.dry_run` and runs as experiment `<experiment>-dry-run`.
"""

import argparse
import asyncio
import logging
import signal
from collections.abc import Sequence
from pathlib import Path

from experiments.config import PROJECT_ROOT, ExperimentConfig
from experiments.dry_run import DryRunResponder
from infrastructure.config import load_config
from infrastructure.git import Repository
from infrastructure.llm import LLMClient, RecordingClient, create_client
from infrastructure.storage import RunDirectory, RunStatus
from runtime.simulation import Setup, Simulation
from tasks.coding import CodingTaskProvider

log = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m experiments.run", description="Run an experiment, one run per seed."
    )
    parser.add_argument("config", type=Path, help="experiment configuration (YAML)")
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--resume", action="store_true", help="continue existing runs")
    parser.add_argument("--until-day", type=int, help="stop after this day")
    parser.add_argument("--dry-run", action="store_true", help="use the scripted responder")
    args = parser.parse_args(argv)
    if args.until_day is not None and args.until_day < 1:
        parser.error("--until-day must be at least 1")
    logging.basicConfig(format="%(asctime)s %(message)s")
    logging.getLogger("runtime").setLevel(logging.INFO)

    config = load_config(args.config, ExperimentConfig)
    if args.dry_run:
        scripted = config.llm.model_copy(update={"backend": "scripted"})
        config = config.model_copy(update={"name": f"{config.name}-dry-run", "llm": scripted})
    for seed in args.seeds:
        root, status = asyncio.run(
            run(config, seed, args.runs_root, resume=args.resume, until_day=args.until_day)
        )
        print(f"{root}: {status}")


async def run(
    config: ExperimentConfig, seed: int, runs_root: Path, *, resume: bool, until_day: int | None
) -> tuple[Path, RunStatus]:
    """Create, or resume, the run of `config` with `seed` and run it. Its parts are built
    before a new run directory exists, so a configuration error leaves nothing behind. A
    termination signal cancels the run like a keyboard interrupt: it is marked interrupted."""
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    revision = code_revision()
    root = RunDirectory.root_of(runs_root, config.name, seed)
    parts = setup(config, seed, RunDirectory(root).llm_calls_path)
    if resume:
        directory = RunDirectory.open(root)
        if load_config(directory.config_path, ExperimentConfig) != config:
            raise ValueError(f"the configuration differs from the one frozen in {root}")
        created = directory.read_manifest().code_revision
        if created != revision:
            log.warning("%s was created at %s and resumes at %s", root, created, revision)
        simulation = Simulation.resume(directory, parts)
    else:
        directory = RunDirectory.create(
            runs_root, config.name, seed, config=config, code_revision=revision
        )
        simulation = Simulation.create(directory, parts)
    return root, await simulation.run(until_day)


def setup(config: ExperimentConfig, seed: int, llm_calls: Path) -> Setup:
    """The parts of the run of `config` with `seed`, recording model calls in `llm_calls`."""
    return Setup(
        simulation=config.simulation,
        environment=config.environment,
        agents=config.agents,
        cognition=config.cognition,
        evolution=config.evolution,
        provider=CodingTaskProvider(config.tasks.bank_path, timeout=config.tasks.timeout),
        client=RecordingClient(agent_client(config, seed), llm_calls),
    )


def agent_client(config: ExperimentConfig, seed: int) -> LLMClient:
    """The model the agents of the run of `config` with `seed` answer through: the configured
    backend, or the dry-run responder if that backend is scripted."""
    responder = DryRunResponder(config, seed) if config.llm.backend == "scripted" else None
    return create_client(config.llm, responder)


def code_revision() -> str:
    """The project's git commit, suffixed `-dirty` if the work tree has changes."""
    repository = Repository(PROJECT_ROOT)
    return repository.head() + ("-dirty" if repository.has_changes() else "")


if __name__ == "__main__":
    main()
