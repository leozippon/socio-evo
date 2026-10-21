"""Full lifecycle and day checkpoint tests with the real Agent and a scripted model."""

import json
from pathlib import Path

from core.agent.evolution import EvolutionConfig, Evolver
from core.environment import Trade
from experiments.config import ExperimentConfig
from infrastructure.config import load_config
from infrastructure.llm import ScriptedClient
from infrastructure.storage import RunDirectory, RunStatus
from runtime.simulation import Setup, Simulation
from tests.runtime.activities.test_engine import PrivateRepositories


async def test_two_day_real_agent_checkpoint_resume_preserves_work(tmp_path):
    config = load_config(Path("experiments/configs/community/activities.yaml"), ExperimentConfig)
    simulation_config = config.simulation.model_copy(update={"days": 2, "lunch_place": None})
    calls = []
    selections = {}
    tools = {}

    def answer(request):
        who = request.metadata["agent"]
        purpose = request.metadata["purpose"]
        minute = request.metadata["time"]
        day = minute // 1440 + 1
        calls.append((who, purpose, minute))
        if purpose == "choose_activity":
            key = (who, day)
            selections[key] = selections.get(key, 0) + 1
            if who == "Mei" and selections[key] == 1:
                return {
                    "thought": "Continue my repair at home.",
                    "do": "work",
                    "minutes": 10,
                    "public": False,
                }
            return {
                "thought": "Rest until tomorrow.",
                "do": "rest",
                "day": "today",
                "until": "22:00",
                "wake for invitations": False,
            }
        if purpose.startswith("work_summary"):
            return {"summary": "The repair remains paused; no new code was run."}
        assert purpose == "activity_tool", purpose
        tools[day] = tools.get(day, 0) + 1
        if day == 1 and tools[day] == 1:
            return {
                "thought": "Take an available repair.",
                "do": "take a job",
                "job": "task-1",
                "partner": None,
            }
        # Work outside opening hours is unavailable; a task can still be claimed at home.
        return {
            "thought": "Save the repair for workshop hours.",
            "do": "leave this activity",
        }

    provider = PrivateRepositories()
    setup = Setup(
        simulation=simulation_config,
        environment=config.environment,
        agents=config.agents,
        cognition=config.cognition,
        evolver=Evolver(EvolutionConfig(levels=())),
        providers={Trade.PROGRAMMING: provider},
        client=ScriptedClient(answer),
    )
    run = RunDirectory.create(
        tmp_path, "activity-checkpoint", 0, config=config, code_revision="local-test"
    )
    first = Simulation.create(run, setup)
    assert await first.run(until_day=1) == RunStatus.INTERRUPTED
    assert first.goals == {}
    task = first.env.board.claim_of("Mei").task.id
    provider.patches[("Mei", task)] = "retained private diff"
    paused = [a for a in first.activity_engine.activities.values() if a.kind == "work"]
    assert paused and paused[0].status == "paused"
    restored = Simulation.resume(run, setup)
    assert await restored.run() == RunStatus.COMPLETED
    assert restored.env.board.claim_of("Mei").task.id == task
    assert provider.patches[("Mei", task)] == "retained private diff"
    assert paused[0].id in restored.activity_engine.activities
    assert restored.env.economy.balances["Mei"] == 80  # two daily living costs
    assert all(
        purpose in ("choose_activity", "activity_tool", "work_summary", "work_summary_merge")
        for _, purpose, _ in calls
    )
    rows = [json.loads(line) for line in run.events_path.read_text().splitlines()]
    assert not any(row["kind"] == "goal_updated" for row in rows)
    assert len([row for row in rows if row["kind"] == "day_ended"]) == 2
