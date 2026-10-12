"""Offline evaluation of a run: probe families on every resident as it stood at the end of
given days."""

import asyncio
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from core.agent import CognitionConfig
from core.agent.evolution import History
from core.environment import EnvironmentConfig, EnvironmentState
from evaluation.config import EvaluationConfig
from evaluation.judge import Judge
from evaluation.probes import FAMILIES, Backdrop, Family, Played, Town, Work
from evaluation.results import AgentResult, Outcome, ProbeResult, result_path, write_result
from evaluation.snapshots import Variant, frozen, version_at
from infrastructure.llm import LLMClient, StructuredOutputError
from infrastructure.storage import RunDirectory
from runtime.simulation import Checkpoint, SimulationConfig

OPEN = 64
"""The most repetitions under way at once, each with its export and scratch town on disk."""
NO_VALID_REPLY = "no_valid_reply"
"""The outcome of a repetition in which the resident or the judge gave no valid reply."""


@dataclass(frozen=True)
class Estimate:
    """What an evaluation costs: the scenes it plays, the fewest and the most decisions it
    asks of the residents' model, and the most questions it puts to the judge."""

    scenes: int
    fewest: int
    most: int
    judged: int


def estimate(config: EvaluationConfig, residents: int, days: int) -> Estimate:
    """The cost of evaluating `residents` residents on `days` days as `config` says."""
    families = [FAMILIES[name] for name in config.families]
    runs = len(config.levels) * config.repetitions * len(config.variants) * residents * days
    return Estimate(
        scenes=runs * len(families),
        fewest=runs * sum(family.calls[0] for family in families),
        most=runs * sum(family.calls[1] for family in families),
        judged=runs * sum(family.calls[2] for family in families),
    )


async def evaluate(
    run: RunDirectory,
    days: Iterable[int],
    config: EvaluationConfig,
    *,
    client: LLMClient,
    judge: LLMClient,
    cognition: CognitionConfig,
    environment: EnvironmentConfig,
    simulation: SimulationConfig,
    overwrite: bool = False,
) -> list[Path]:
    """Play the configured families on every resident of `run` as it stood at the end of each
    of `days`, exported as each configured variant; write one result file per resident, day
    and variant, and return their paths.

    The residents answer through `client` with `cognition` as their prompt limits, in probe
    towns built from the run's `environment` and `simulation` and the checkpoint of the
    evaluated day; free text is judged through `judge`. Each repetition runs on its own fresh
    export and its own scratch town, so nothing reaches an agent repository, the event log or
    another repetition. A repetition in which the resident or the judge gives no valid reply
    within the attempts the client allows is kept as the unscored outcome `no_valid_reply`, with
    the error, since one degenerate reply says nothing about the others; any other failure
    cancels the rest. Everything runs concurrently, bounded by how many calls the clients keep
    in flight.
    Everything is checked before any scene is played: ValueError for no days or no residents,
    a day after the run's latest checkpoint or without a checkpoint of its own, a day a
    history does not reach, a stranger named like a resident, or held-out work or a town that
    a family cannot be played with; FileExistsError for an existing result file unless
    `overwrite`.
    """
    days = sorted(set(days))
    agents = sorted(path.name for path in run.agents_dir.iterdir())
    if not days or not agents:
        raise ValueError(f"nothing to evaluate: days {days}, residents {agents}")
    latest = run.latest_checkpoint()
    if latest is None:
        raise ValueError(f"{run.root} has no checkpoint")
    checkpointed = Checkpoint.model_validate_json(latest.read_text(encoding="utf-8")).day
    if unfinished := [day for day in days if day > checkpointed]:
        raise ValueError(f"days {unfinished} come after the latest checkpoint, day {checkpointed}")
    if missing := [day for day in days if not run.checkpoint_path(day).exists()]:
        raise ValueError(f"days {missing} have no checkpoint to build their town from")
    families = [FAMILIES[name] for name in config.families]
    strangers = {name for family in families for cast in family.strangers for name in cast}
    if clashes := sorted(strangers & set(agents)):
        raise ValueError(f"strangers of the probes share names with residents: {clashes}")
    backdrops = {day: _backdrop(run, day, environment, simulation) for day in days}
    work = Work(
        config.bank, config.work, timeout=config.sandbox_timeout, isolation=config.isolation
    )
    for family in families:
        for backdrop in backdrops.values():
            await family.ready(work, backdrop)
    histories = {agent: History(run.agent_dir(agent)) for agent in agents}
    plan = [
        (day, agent, variant, version_at(histories[agent], day).commit)
        for day in days
        for agent in agents
        for variant in config.variants
    ]
    targets = [result_path(run, agent, day, variant) for day, agent, variant, _ in plan]
    if not overwrite and (existing := [str(path) for path in targets if path.exists()]):
        raise FileExistsError(f"evaluation results exist: {existing}")

    judging, slots = Judge(judge), asyncio.Semaphore(OPEN)

    async def repetition(
        family: Family, day: int, agent: str, commit: str, variant: Variant, level: int, rep: int
    ) -> Outcome:
        surface = rep % family.surfaces
        async with slots:
            with (
                frozen(
                    histories[agent], commit, client, cognition, environment.setting, variant
                ) as resident,
                tempfile.TemporaryDirectory(prefix="probe-town-") as scratch,
            ):
                seed = f"{family.name}:{level}:{rep}"
                cast = family.strangers[surface]
                town = Town(backdrops[day], resident, cast, work, Path(scratch), seed)
                try:
                    played = await family.play(town, level, surface, judging)
                except* StructuredOutputError as failed:
                    played = Played(NO_VALID_REPLY, None, {"error": _message(failed)})
                return Outcome(
                    score=played.score,
                    measures=played.measures,
                    transcript=tuple(step.model_dump(mode="json") for step in town.steps),
                    level=level,
                    stake=family.stake(level, town.living_cost),
                    repetition=rep,
                    surface=surface,
                    outcome=played.outcome,
                )

    async def one(day: int, agent: str, variant: Variant, commit: str) -> Path:
        async with asyncio.TaskGroup() as group:
            running = {
                family.name: [
                    group.create_task(repetition(family, day, agent, commit, variant, level, rep))
                    for level in config.levels
                    for rep in range(config.repetitions)
                ]
                for family in families
            }
        result = AgentResult(
            format=2,
            agent=agent,
            day=day,
            commit=commit,
            variant=variant,
            probes={
                family.name: ProbeResult.of(
                    family.trait, [task.result() for task in running[family.name]], family.unit
                )
                for family in families
            },
        )
        return write_result(run, result, overwrite=overwrite)

    async with asyncio.TaskGroup() as group:
        writing = [group.create_task(one(*entry)) for entry in plan]
    return [task.result() for task in writing]


def _backdrop(
    run: RunDirectory, day: int, environment: EnvironmentConfig, simulation: SimulationConfig
) -> Backdrop:
    checkpoint = Checkpoint.model_validate_json(run.checkpoint_path(day).read_text("utf-8"))
    state = EnvironmentState.model_validate(checkpoint.environment)
    return Backdrop(day=day, environment=environment, simulation=simulation, state=state)


def _message(group: BaseExceptionGroup) -> str:
    """The message of the first exception in `group`, however deeply nested."""
    first = group.exceptions[0]
    return _message(first) if isinstance(first, BaseExceptionGroup) else str(first)
