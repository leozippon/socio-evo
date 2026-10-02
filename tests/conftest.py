import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from core.agent.evolution import EvolutionConfig, Evolver, History, SelfTrigger
from evaluation import Dimension, Outcome, ProbeResult, version_at
from evaluation.results import AgentResult, write_result
from experiments.config import ExperimentConfig
from infrastructure.llm import LLMConfig, LLMRequest, RecordingClient, ScriptedClient
from infrastructure.storage import RunDirectory
from runtime.simulation import Setup, Simulation
from tasks.coding import BANK, CodingTaskProvider
from tests.runtime.test_simulation import ENVIRONMENT, SEEDS, SIMULATION, Script

TOWN = ExperimentConfig(
    name="town",
    llm=LLMConfig(backend="scripted", base_url="http://unused", api_key_env="UNUSED", model="x"),
    agents=tuple(SEEDS.values()),
    evolution=EvolutionConfig(self_trigger=SelfTrigger(enabled=False)),
    environment=ENVIRONMENT,
    simulation=SIMULATION,
)


class Townsfolk(Script):
    """The scripted town of the runtime tests, in which Cai leaves a conversation rather than
    let a turn pass."""

    def __call__(self, request: LLMRequest) -> str | dict[str, Any]:
        reply = super().__call__(request)
        if request.metadata["agent"] == "Cai" and request.metadata["purpose"] == "act":
            allowed = re.search(
                r"Choose one action: (.+)\. Your thought", request.messages[-1].content
            )
            if reply["action"] == {"kind": "pass"} and "leave" in allowed[1]:
                reply["action"] = {"kind": "leave"}
        return reply


@pytest.fixture(scope="session")
def town(tmp_path_factory) -> Path:
    """A finished three-day run of the scripted town with evaluation results of days 0 and
    3, under `<runs root>/town/seed-0007`. Tests must not change it; copy it to do so."""
    runs = tmp_path_factory.mktemp("runs")
    run = RunDirectory.create(runs, TOWN.name, 7, config=TOWN, code_revision="test")
    setup = Setup(
        simulation=TOWN.simulation,
        environment=TOWN.environment,
        agents=TOWN.agents,
        cognition=TOWN.cognition,
        evolver=Evolver(TOWN.evolution),
        provider=CodingTaskProvider(BANK),
        client=RecordingClient(ScriptedClient(Townsfolk()), run.llm_calls_path),
    )
    asyncio.run(Simulation.create(run, setup).run())
    for agent in SEEDS:
        for day in (0, 3):
            outcome = Outcome(score=day / 3, measures={"disclosed": day > 0}, transcript=())
            result = AgentResult(
                agent=agent,
                day=day,
                commit=version_at(History(run.agent_dir(agent)), day).commit,
                probes={"shortfall_report": ProbeResult.of(Dimension.HONESTY, [outcome])},
            )
            write_result(run, result, overwrite=False)
    return run.root
