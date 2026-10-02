"""Offline evaluation of a run: probes on every agent as it stood at the end of given days."""

import asyncio
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from functools import partial
from pathlib import Path

from core.agent import Agent, CognitionConfig
from core.agent.evolution import History
from evaluation.config import EvaluationConfig
from evaluation.judge import Judge
from evaluation.probes import PROBES, Instruments, Outcome, Probe
from evaluation.results import AgentResult, ProbeResult, result_path, write_result
from evaluation.snapshots import frozen, version_at
from infrastructure.llm import LLMClient
from infrastructure.storage import RunDirectory
from tasks.coding import CodingTaskProvider


async def evaluate(
    run: RunDirectory,
    days: Iterable[int],
    config: EvaluationConfig,
    *,
    client: LLMClient,
    judge: LLMClient,
    cognition: CognitionConfig,
    overwrite: bool = False,
) -> list[Path]:
    """Run the configured probes on every agent of `run` as it stood at the end of each of
    `days`, write one result file per agent and day, and return their paths.

    The evaluated agents answer through `client` with `cognition` as their prompt limits, and
    free text is judged through `judge`. Each repetition of a probe runs on its own fresh
    export of the agent, so nothing reaches an agent repository, the event log or another
    repetition. Everything is checked before any probe runs: ValueError for no days or no
    agents, a day an agent's history does not reach, or a probe peer named like an agent of
    the run; FileExistsError for an existing result file unless `overwrite`.
    """
    days = sorted(set(days))
    agents = sorted(path.name for path in run.agents_dir.iterdir())
    if not days or not agents:
        raise ValueError(f"nothing to evaluate: days {days}, agents {agents}")
    probes = [PROBES[name] for name in config.probes]
    if clashes := sorted({peer for probe in probes for peer in probe.peers} & set(agents)):
        raise ValueError(f"probe peers share names with agents of the run: {clashes}")
    histories = {agent: History(run.agent_dir(agent)) for agent in agents}
    plan = [
        (day, agent, version_at(histories[agent], day).commit) for day in days for agent in agents
    ]
    targets = [result_path(run, agent, day) for day, agent, _ in plan]
    if not overwrite and (existing := [str(path) for path in targets if path.exists()]):
        raise FileExistsError(f"evaluation results exist: {existing}")

    instruments = Instruments(
        judge=Judge(judge), work=CodingTaskProvider(config.bank, timeout=config.sandbox_timeout)
    )
    written = []
    for day, agent, commit in plan:
        export = partial(frozen, histories[agent], commit, client, cognition)
        results = await asyncio.gather(
            *(_repeat(probe, config.repetitions, day, export, instruments) for probe in probes)
        )
        result = AgentResult(
            agent=agent,
            day=day,
            commit=commit,
            probes={probe.name: result for probe, result in zip(probes, results, strict=True)},
        )
        written.append(write_result(run, result, overwrite=overwrite))
    return written


async def _repeat(
    probe: Probe,
    repetitions: int,
    day: int,
    export: Callable[[], AbstractContextManager[Agent]],
    instruments: Instruments,
) -> ProbeResult:
    async def once(repetition: int) -> Outcome:
        with export() as agent:
            return await probe.run(agent, day, repetition, instruments)

    outcomes = await asyncio.gather(*map(once, range(repetitions)))
    return ProbeResult.of(probe.dimension, outcomes)
