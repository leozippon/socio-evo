"""Rest deadlines survive the nightly boundary and serialized scheduler state."""

import json

import pytest

from core.environment.rejection import Rejected
from core.interaction import time_at
from runtime.activities.engine import ActivityEngine
from runtime.activities.model import RestActivity, at
from runtime.realtime.engine import RealtimeEngine
from tests.runtime.activities import test_engine as activity_tests
from tests.runtime.activities.test_engine import choose

engine = activity_tests.engine


@pytest.fixture(params=[ActivityEngine, RealtimeEngine])
def scheduler(engine, request):
    return request.param(engine.sim)


def sleep(scheduler, until="07:45", **arguments):
    scheduler.now, scheduler.end = at(1, "21:00"), at(1, "22:00")
    scheduler.select(
        "Mei",
        choose(
            "select_rest", arguments={"until": until, "day": "tomorrow", "wake": False, **arguments}
        ),
    )


@pytest.mark.parametrize("restore", [False, True])
async def test_tomorrow_rest_closes_today_and_resumes_at_home(scheduler, restore):
    scheduler.env.move("Mei", "workshop", time=time_at(1, "20:00"))
    sleep(scheduler)
    first = scheduler.activities[scheduler.current["Mei"]]
    assert first.members["Mei"].end <= scheduler.end
    # A member_end can precede the day-close cleanup at exactly 22:00.
    scheduler.now = scheduler.end
    for event in scheduler.queue.pop_at(scheduler.end):
        await scheduler.process(event)
    scheduler.boundary()
    assert "Mei" not in scheduler.current
    assert scheduler.env.world.locations["Mei"] == scheduler.env.config.homes["Mei"]
    assert scheduler.rest_intents["Mei"]["until"] == at(2, "07:45")
    if restore:
        state = json.loads(json.dumps(scheduler.state()))
        scheduler = type(scheduler)(scheduler.sim, state)
    scheduler.prepare_day(time_at(2, "07:00"))
    rest = scheduler.activities[scheduler.current["Mei"]]
    assert isinstance(rest, RestActivity)
    assert rest.id == first.id
    assert rest.place == scheduler.env.config.homes["Mei"]
    assert rest.members["Mei"].end == at(2, "07:45")
    assert rest.wake_invitations is False
    if isinstance(scheduler, RealtimeEngine):
        assert "Mei" not in scheduler.selection_rests
        assert not scheduler.running
    scheduler.now = at(2, "07:45")
    for event in scheduler.queue.pop_at(scheduler.now):
        await scheduler.process(event)
    assert "Mei" not in scheduler.current
    assert "Mei" not in scheduler.rest_intents


def test_rest_ending_at_next_day_start_does_not_roll_forward(scheduler):
    sleep(scheduler, until="07:00")
    scheduler.now = scheduler.end
    scheduler.boundary()
    scheduler = type(scheduler)(scheduler.sim, json.loads(json.dumps(scheduler.state())))
    scheduler.prepare_day(time_at(2, "07:00"))
    assert "Mei" not in scheduler.current
    assert "Mei" not in scheduler.rest_intents


@pytest.mark.parametrize(
    "reason", ["I changed my mind.", "A new invitation arrived.", "Time for lunch."]
)
def test_early_interruptions_cancel_future_rest(scheduler, reason):
    sleep(scheduler)
    scheduler.now += 60
    scheduler.leave("Mei", reason)
    assert "Mei" not in scheduler.rest_intents
    scheduler.now = scheduler.end
    scheduler.boundary()
    scheduler.prepare_day(time_at(2, "07:00"))
    assert "Mei" not in scheduler.current


@pytest.mark.parametrize("day", ["today", None, "yesterday"])
def test_past_today_and_unknown_day_are_rejected(scheduler, day):
    scheduler.now, scheduler.end = at(1, "21:00"), at(1, "22:00")
    arguments = {"until": "07:00"}
    if day is not None:
        arguments["day"] = day
    with pytest.raises(
        Rejected, match="today or tomorrow" if day == "yesterday" else "Rest not started"
    ):
        scheduler.select("Mei", choose("select_rest", arguments=arguments))
    assert "Mei" not in scheduler.current
    assert not scheduler.rest_intents


async def test_nightly_settlement_and_checkpoint_resume_keep_morning_rest(tmp_path):
    from pathlib import Path

    from core.agent.evolution import EvolutionConfig, Evolver
    from core.environment import Trade
    from experiments.config import ExperimentConfig
    from infrastructure.config import load_config
    from infrastructure.llm import ScriptedClient
    from infrastructure.storage import RunDirectory, RunStatus
    from runtime.simulation import Setup, Simulation
    from tests.runtime.activities.test_engine import PrivateRepositories

    config = load_config(Path("experiments/configs/community/activities.yaml"), ExperimentConfig)
    calls = []

    def answer(request):
        minute = request.metadata["time"]
        calls.append((request.metadata["agent"], minute))
        assert request.metadata["purpose"] == "choose_activity"
        return {
            "thought": "Rest until my chosen time.",
            "do": "rest",
            "day": "tomorrow" if minute < 1440 else "today",
            "until": "07:45" if minute < 1440 else "22:00",
            "wake for invitations": False,
        }

    setup = Setup(
        simulation=config.simulation.model_copy(update={"days": 2, "lunch_place": None}),
        environment=config.environment,
        agents=config.agents,
        cognition=config.cognition,
        evolver=Evolver(EvolutionConfig(levels=())),
        providers={Trade.PROGRAMMING: PrivateRepositories()},
        client=ScriptedClient(answer),
    )
    run = RunDirectory.create(tmp_path, "overnight-rest", 0, config=config, code_revision="test")
    first = Simulation.create(run, setup)
    assert await first.run(until_day=1) == RunStatus.INTERRUPTED
    assert set(first.activity_engine.rest_intents) == set(first.agents)
    restored = Simulation.resume(run, setup)
    assert await restored.run() == RunStatus.COMPLETED
    assert all(minute == time_at(2, "07:45") for _, minute in calls if minute >= 1440)
    assert len(calls) == 2 * len(restored.agents)
    assert restored.env.economy.balances["Mei"] == 80
    rows = [json.loads(line) for line in run.events_path.read_text().splitlines()]
    assert len([row for row in rows if row["kind"] == "day_ended"]) == 2
    morning = [
        row
        for row in rows
        if row["kind"] == "activity_entered" and row["time"] == time_at(2, "07:00")
    ]
    assert len(morning) == len(restored.agents)
    assert all(row["payload"]["activity_type"] == "rest" for row in morning)
    assert all(row["payload"]["end"] == time_at(2, "07:45") for row in morning)
