"""Full real Agent lifecycle with a scripted model and private in-memory repository."""

import asyncio
import json
from pathlib import Path

from core.agent.evolution import EvolutionConfig, Evolver
from core.environment import Trade
from experiments.config import ExperimentConfig
from infrastructure.config import load_config
from infrastructure.llm import ScriptedClient
from infrastructure.storage import RunDirectory, RunStatus
from runtime.realtime.clock import RealtimeTiming
from runtime.realtime.engine import RealtimeEngine
from runtime.simulation import Setup, Simulation
from tests.runtime.activities.test_engine import PrivateRepositories, work
from tests.runtime.realtime.test_engine import take


def setup_run(tmp_path, days=2):
    config = load_config(Path("experiments/configs/community/realtime.yaml"), ExperimentConfig)
    calls = []

    def answer(request):
        if request.metadata["purpose"].startswith("work_summary"):
            return {"summary": "The submitted repair is awaiting its client verdict."}
        calls.append((request.metadata["agent"], request.metadata["purpose"]))
        assert request.metadata["purpose"] == "choose_activity"
        return {
            "thought": "Rest",
            "do": "rest",
            "day": "today",
            "until": "22:00",
            "wake for invitations": False,
        }

    provider = PrivateRepositories()
    simconfig = config.simulation.model_copy(
        update={
            "days": days,
            "lunch_place": None,
            "realtime": RealtimeTiming(multiplier=100_000, final_grading_wait_seconds=0),
        }
    )
    setup = Setup(
        simulation=simconfig,
        environment=config.environment,
        agents=config.agents,
        cognition=config.cognition,
        evolver=Evolver(EvolutionConfig(levels=())),
        providers={Trade.PROGRAMMING: provider},
        client=ScriptedClient(answer),
    )
    run = RunDirectory.create(
        tmp_path, "realtime-unit-fixture", 0, config=config, code_revision="test"
    )
    return run, setup, provider, calls


async def test_realtime_day_resume_uses_real_agent_and_no_morning_plan(tmp_path):
    run, setup, provider, calls = setup_run(tmp_path)
    first = Simulation.create(run, setup)
    assert await first.run(until_day=1) == RunStatus.INTERRUPTED
    second = Simulation.resume(run, setup)
    assert await second.run() == RunStatus.COMPLETED
    assert len(calls) == 16
    assert second.env.economy.balances["Mei"] == 80
    rows = [json.loads(x) for x in run.events_path.read_text().splitlines()]
    assert [row["time"] for row in rows] == sorted(row["time"] for row in rows)
    assert not any(row["kind"] == "goal_updated" for row in rows)
    assert len([r for r in rows if r["kind"] == "day_ended"]) == 2


async def test_final_pending_grading_resumes_without_rerunning_day_or_charging_again(tmp_path):
    run, setup, provider, calls = setup_run(tmp_path, days=1)
    sim = Simulation.create(run, setup)
    sim.env.post(420, 0)
    engine = RealtimeEngine(sim)
    engine.now = 7 * 3600
    engine.end = 22 * 3600
    engine.clock.rebase(engine.now)
    sim.activity_engine = engine
    work(engine)
    await take(engine)
    provider.verdict_ready = asyncio.Event()
    # Seed a pending receipt before the active day, without invoking a real evaluator.
    from core.interaction import SubmitWork

    action = SubmitWork(task_id="task-1", solution="", report="Ready")
    engine.assessments["task-1"] = {
        "due": engine.now + 1200,
        "agent": "Mei",
        "action": action.model_dump(mode="json"),
        "place": "workshop",
        "delayed": False,
    }
    engine.start_assessment("task-1")
    engine.leave("Mei", "Pending submission fixture")
    assert await sim.run() == RunStatus.INTERRUPTED
    assert engine.assessments and len(calls) == 8
    balance = sim.env.economy.balances["Mei"]
    await engine.close()
    provider.verdict_ready.set()
    resumed = Simulation.resume(run, setup)
    assert await resumed.run() == RunStatus.COMPLETED
    assert not resumed.activity_engine.assessments
    assert len(calls) == 8  # no repeated model decisions or simulated day
    assert resumed.env.economy.balances["Mei"] == balance + 60
    rows = [json.loads(x) for x in run.events_path.read_text().splitlines()]
    assert len([r for r in rows if r["kind"] == "payment"]) == 1
    assert len([r for r in rows if r["kind"] == "day_ended"]) == 1


async def test_late_completion_does_not_round_night_into_an_extra_day(tmp_path, monkeypatch):
    from runtime.activities.model import at

    run, setup, provider, calls = setup_run(tmp_path, days=1)

    async def completed_late(engine, start):
        engine.now = at(1, "23:59:59")
        engine.end = at(1, "22:00")

    monkeypatch.setattr(RealtimeEngine, "run", completed_late)
    simulation = Simulation.create(run, setup)
    assert await simulation.run() == RunStatus.COMPLETED
    assert simulation.day == 1
    assert simulation.env.economy.balances["Mei"] == 100
    rows = [json.loads(x) for x in run.events_path.read_text().splitlines()]
    assert next(row for row in rows if row["kind"] == "day_ended")["time"] == 1439
