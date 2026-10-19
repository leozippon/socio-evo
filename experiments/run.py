"""Run an experiment: one independent society run per seed.

    python -m experiments.run CONFIG --seeds 0 1 2 [--runs-root runs] [--resume]
                                     [--until-day N] [--dry-run]

Each seed runs in `<runs-root>/<experiment>/seed-NNNN`, with every model call recorded in
its `llm_calls.jsonl`. Creating a run that exists fails; `--resume` continues a run from its
latest checkpoint and requires the configuration frozen in it. `--until-day` stops after
that day, leaving the run interrupted and resumable. `--dry-run` replaces the model with the
scripted responder of `experiments.dry_run` and each task bank with the built-in bank of its
trade (`tasks.BUILT_IN`), and runs as experiment `<experiment>-dry-run`; so a dry run needs
neither the model nor a fetched bank.

Before a run is created or resumed, the task bank of every trade it names must exist (each is
built by its trade's fetch, `python -m tasks.coding.fetch`, `tasks.queries.fetch` or
`tasks.calculation.fetch`) and delivered code must run under the configured isolation;
otherwise nothing is created.
"""

import argparse
import asyncio
import logging
import signal
from collections.abc import Sequence
from pathlib import Path

from core.agent.evolution import Evolver
from core.environment import Trade
from experiments.config import PROJECT_ROOT, ExperimentConfig
from experiments.dry_run import DryRunResponder
from infrastructure.config import load_config
from infrastructure.git import Repository
from infrastructure.llm import LLMClient, RecordingClient, create_client
from infrastructure.storage import RunDirectory, RunStatus
from runtime.simulation import Setup, Simulation
from tasks import BUILT_IN, PROVIDERS
from tasks.coding import Check, run_checks

log = logging.getLogger(__name__)

PROBE = Check.model_validate("len('ready') == 5")
"""A check any sandbox runs, to find out before a run whether delivered code can be run."""
FETCH = {
    Trade.PROGRAMMING: "tasks.coding.fetch",
    Trade.QUERIES: "tasks.queries.fetch",
    Trade.CALCULATION: "tasks.calculation.fetch",
}
"""The module that builds each trade's banks."""


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
        config = as_dry_run(config)
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
    if resume and config.tasks.provider == "swebench" and not config.tasks.community:
        raise ValueError("SWE-bench town pilot cannot resume a partial day; start a new run")
    revision = code_revision()
    root = RunDirectory.root_of(runs_root, config.name, seed)
    parts = setup(config, seed, RunDirectory(root).llm_calls_path)
    if config.tasks.provider != "swebench":
        await run_checks("", (PROBE,), isolation=config.tasks.isolation)
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
    try:
        return root, await simulation.run(until_day)
    finally:
        if simulation.activity_engine is not None:
            await simulation.activity_engine.close()
        await close_providers(parts)


def as_dry_run(config: ExperimentConfig) -> ExperimentConfig:
    """`config` answered by the scripted responder, each of its banks replaced by the
    built-in bank of the same trade, as experiment `<name>-dry-run`."""
    if config.tasks.provider == "swebench":
        raise ValueError("The scripted dry-run responder does not implement repository repairs")
    scripted = config.llm.model_copy(update={"backend": "scripted"})
    banks = {t: BUILT_IN[t].relative_to(PROJECT_ROOT).as_posix() for t in config.tasks.banks}
    tasks = config.tasks.model_copy(update={"banks": banks})
    return config.model_copy(
        update={"name": f"{config.name}-dry-run", "llm": scripted, "tasks": tasks}
    )


def setup(config: ExperimentConfig, seed: int, llm_calls: Path) -> Setup:
    """The parts of the run of `config` with `seed`, recording model calls in `llm_calls`.

    Raises FileNotFoundError, naming the command that builds it, if a task bank is missing.
    """
    tasks = config.tasks
    for trade, path in tasks.bank_paths.items():
        if tasks.provider == "swebench":
            if not path.is_file():
                raise FileNotFoundError(f"SWE-bench dataset is missing: {path}")
            continue
        if not path.is_dir():
            raise FileNotFoundError(
                f"the {trade.value} bank {path} is missing; it is built by "
                f"`python -m {FETCH[trade]}` (see {FETCH[trade].replace('.', '/')}.py)"
            )
    return Setup(
        simulation=config.simulation,
        environment=config.environment,
        agents=config.agents,
        cognition=config.cognition,
        evolver=Evolver(config.evolution),
        providers=task_providers(config, llm_calls.parent),
        client=RecordingClient(agent_client(config, seed), llm_calls),
    )


def task_providers(config: ExperimentConfig, run_root: Path):
    if config.tasks.provider == "swebench":
        from tasks.swebench.provider import SWEbenchTaskProvider

        provider = SWEbenchTaskProvider(
            config.tasks.bank_path,
            config.tasks.instances,
            run_root / "repositories",
            command_seconds=config.tasks.command_seconds,
            evaluation_seconds=config.tasks.evaluation_seconds,
            community=config.tasks.community,
            repository_guidance=config.tasks.repository_guidance,
            strict_http_cache=config.tasks.strict_http_cache,
            evaluation_preflight=config.tasks.evaluation_preflight,
            http_cache=config.tasks.http_cache_path,
            independent_workspaces=config.simulation.scheduling in ("activities", "realtime"),
            solo_deadline_days=config.tasks.solo_deadline_days,
            joint_deadline_days=config.tasks.joint_deadline_days,
        )
        if config.tasks.community:
            required = (
                config.environment.conditions.one_part_tasks
                + config.environment.conditions.two_part_tasks
            )
            if len(provider.rows) < required:
                raise ValueError(f"community needs at least {required} distinct repository issues")
        return {Trade.PROGRAMMING: provider}
    return {
        trade: PROVIDERS[trade](
            path, timeout=config.tasks.timeout, isolation=config.tasks.isolation
        )
        for trade, path in config.tasks.bank_paths.items()
    }


async def close_providers(parts: Setup) -> None:
    for provider in parts.providers.values():
        if hasattr(provider, "close"):
            await provider.close()


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
