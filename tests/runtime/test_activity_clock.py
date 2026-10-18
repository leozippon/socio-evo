"""Independent time, delayed evidence, voluntary discussion, and day checkpoint recovery."""

import json
import random
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.environment import Assessment, Environment, Trade
from core.environment.rejection import Rejected
from core.interaction import (
    Card,
    ClaimTask,
    Decision,
    Event,
    EventKind,
    Pass,
    RunCommand,
    Speak,
    SubmitWork,
    time_at,
)
from core.interaction.actions import Activity
from core.interaction.card import MayActivity
from experiments.config import ExperimentConfig
from infrastructure.config import load_config
from infrastructure.llm import ScriptedClient
from runtime.scheduler import TriggerQueue
from runtime.scheduler.activity import ActivityClock, Discussion, Pending
from runtime.simulation import Simulation
from tests.core.environment.test_technical_community import RepositoryProvider


class Repositories(RepositoryProvider):
    def __init__(self):
        self.commands = []
        self.patches = []

    async def run_command(self, part, worker, task_id, command):
        self.commands.append((worker, command))
        return {"exit_code": 0, "output": "new evidence"}

    async def prepare_submission(self, part, worker, task_id, solution):
        return "diff --git a/test.py b/test.py\n+fix"

    async def assess(self, part, patch):
        self.patches.append(patch)
        return Assessment(passed=True, quality=1, feedback="Accepted")


@pytest.fixture
def clock(tmp_path):
    cfg = load_config(Path("experiments/configs/community/lite.yaml"), ExperimentConfig)
    provider = Repositories()
    env = Environment.create(
        cfg.environment, list(cfg.environment.homes), provider, tmp_path / "events.jsonl"
    )
    env.post(time_at(1, "07:00"), 1)
    sim = SimpleNamespace(
        env=env,
        config=cfg.simulation,
        rng=random.Random(7),
        goals={},
        agents={a: None for a in env.agents},
        queue=TriggerQueue(),
        _met={a: set() for a in env.agents},
        _bound_lapses=lambda: None,
    )
    result = ActivityClock(sim)
    result.end = time_at(1, "22:00")
    result.planned = set(env.agents)
    return result


def logged(clock):
    return [Event.model_validate_json(line) for line in clock.env.log.path.read_text().splitlines()]


def pending(clock, who, action, start, minutes=5, discussion=None):
    p = Pending(
        who,
        Decision(thought="test", action=action),
        start,
        start + minutes,
        clock.env.world.locations[who],
        discussion,
    )
    clock.pending[who] = p
    return p


def work_place(clock):
    return next(p.id for p in clock.env.world.places.values() if p.kind == "work")


def put_at_work(clock):
    for who in clock.env.agents:
        clock.env.move(who, work_place(clock), time=time_at(1, "08:00"))


def test_work_boundaries_and_lunch_board(clock):
    put_at_work(clock)
    assert clock.can_work("Mei", time_at(1, "11:40"))
    assert not clock.can_work("Mei", time_at(1, "11:45"))
    assert not clock.can_work("Mei", time_at(1, "12:30"))
    assert clock.can_work("Mei", time_at(1, "17:40"))
    assert not clock.can_work("Mei", time_at(1, "17:45"))
    for hour in ("07:10", "12:10"):
        card = Card(clock.allowed("Aisha", time_at(1, hour)))
        assert "take a job" in str(card.model.model_json_schema())
        assert "use the terminal" not in str(card.model.model_json_schema())


async def test_effects_wait_for_independent_completion_and_claims_draw(clock):
    put_at_work(clock)
    start = time_at(1, "08:00")
    for who in ("Mei", "Tomas"):
        pending(clock, who, ClaimTask(task_id="task-1"), start)
    await clock.complete(start)
    assert not clock.env.board.claims
    await clock.complete(start + 5)
    claim = clock.env.board.claims["task-1"]
    assert len(claim.workers) == 1
    draw = next(e for e in logged(clock) if e.kind == EventKind.DRAW)
    assert draw.payload["order"][0] == claim.workers[0]
    winner = claim.workers[0]
    pending(clock, winner, RunCommand(task_id="task-1", command="pytest"), start + 5, 20)
    pending(clock, "Aisha", Pass(), start + 5)
    await clock.complete(start + 10)
    assert winner in clock.pending and "Aisha" not in clock.pending
    assert not clock.env.providers[Trade.PROGRAMMING].commands
    assert not any(e.kind == EventKind.COMMAND_EXECUTED for e in logged(clock))
    await clock.complete(start + 25)
    assert clock.env.providers[Trade.PROGRAMMING].commands == [(winner, "pytest")]
    assert next(e.time for e in logged(clock) if e.kind == EventKind.COMMAND_EXECUTED) == start + 25


async def test_grading_is_separate_and_freezes_patch(clock):
    put_at_work(clock)
    now = time_at(1, "08:00")
    pending(clock, "Mei", ClaimTask(task_id="task-1"), now)
    await clock.complete(now + 5)
    action = SubmitWork(task_id="task-1", solution="WORKTREE", report="Please check")
    pending(clock, "Mei", action, now + 5)
    await clock.complete(now + 10)
    assert "Mei" not in clock.pending and "task-1" in clock.grading
    assert not any(e.kind == EventKind.PAYMENT for e in logged(clock))
    pending(
        clock, "Mei", Activity(operation="move", target=clock.env.config.homes["Mei"]), now + 10
    )
    await clock.complete(now + 15)
    assert clock.env.world.locations["Mei"] == clock.env.config.homes["Mei"]
    await clock.complete(now + 30)
    assert not clock.grading and not clock.env.board.claims
    assert any(e.kind == EventKind.PAYMENT and e.time == now + 30 for e in logged(clock))


def test_invitation_never_locks_and_start_rechecks_busy(clock):
    put_at_work(clock)
    now = time_at(1, "09:00")
    clock.control(
        "Mei", Activity(operation="invite", target="Tomas", topic="repair", remote=True), now
    )
    d = next(iter(clock.discussions.values()))
    clock.control("Tomas", Activity(operation="accept", target=d.id), now + 5)
    assert not clock.pending and not d.members
    pending(clock, "Tomas", RunCommand(task_id="task-1", command="pytest"), now + 5, 20)
    with pytest.raises(Rejected, match="free"):
        clock.control("Mei", Activity(operation="start", target=d.id), now + 10)
    assert not d.members
    clock.pending.clear()
    clock.control("Mei", Activity(operation="start", target=d.id), now + 25)
    assert d.members == ["Mei", "Tomas"] and clock.member_of("Aisha") is None


async def test_shared_turn_exit_extension_and_observer(clock):
    put_at_work(clock)
    now = time_at(1, "11:30")
    d = Discussion(
        "d", "Mei", "Tomas", "repair", 20, True, work_place(clock), ["Mei", "Tomas"], now + 20
    )
    clock.discussions[d.id] = d
    # One person's consent cannot extend the meeting.
    clock.control("Mei", Activity(operation="extend", target="d", minutes=60), now)
    assert d.end == now + 20
    clock.control("Tomas", Activity(operation="agree", target="d"), now)
    assert d.end == time_at(1, "12:00")
    pending(clock, "Mei", Speak(text="first turn"), now, discussion="d")
    pending(clock, "Tomas", Pass(), now, discussion="d")
    pending(clock, "Aisha", Pass(), now)
    await clock.complete(now + 5)
    assert clock.member_of("Aisha") is None
    speech = next(e for e in logged(clock) if e.kind == EventKind.SPEECH)
    assert "Tomas" in speech.audience and "Aisha" in speech.audience
    pending(clock, "Tomas", Activity(operation="exit", target="d"), now + 5, discussion="d")
    pending(clock, "Mei", Pass(), now + 5, discussion="d")
    await clock.complete(now + 10)
    assert d.closed and not d.members


def test_goal_is_optional_on_legacy_cards_and_bounded_on_new_cards():
    old = Card((MayActivity(moves={"home": "h"}),))
    answer = old.model.model_validate({"thought": "go", "do": "move", "to": "home"})
    assert old.decision(answer).goal is None
    new = Card((MayActivity(moves={"home": "h"}),), goal_updates=True)
    answer = new.model.model_validate(
        {"thought": "go", "do": "move", "to": "home", "current goal": "Review the patch"}
    )
    assert new.decision(answer).goal == "Review the patch"


async def test_full_independent_day_and_resume_use_real_agent_protocol(tmp_path):
    from tests.runtime.test_simulation import Script, new_run

    script = Script()
    run, setup = new_run(tmp_path, script)
    config = setup.simulation.model_copy(
        update={"scheduling": "independent", "days": 2, "interventions": ()}
    )

    fail = {"enabled": False}

    def respond(request):
        if request.metadata["purpose"] != "act":
            return script(request)
        if fail["enabled"] and request.metadata["time"] == time_at(2, "08:00"):
            raise RuntimeError("interrupted model service")
        if "set today's goal" in str(request.json_schema):
            goal = (
                "Learn carefully"
                if request.metadata["time"] < time_at(2, "07:00")
                else "Review edits"
            )
            return {"thought": "Plan", "do": "set today's goal", "goal": goal}
        return {"thought": "Rest", "do": "carry on quietly", "current goal": None}

    setup = replace(
        setup,
        simulation=config,
        providers={Trade.PROGRAMMING: Repositories()},
        client=ScriptedClient(respond),
    )
    # The helper normally saves only its simulation config; analytics needs experiment metadata.
    import yaml

    run.config_path.write_text(
        yaml.safe_dump(
            {
                "name": "town",
                "agents": [a.model_dump(mode="json") for a in setup.agents],
                "environment": setup.environment.model_dump(mode="json"),
                "simulation": config.model_dump(mode="json"),
            }
        )
    )
    sim = Simulation.create(run, setup)
    await sim.run(until_day=1)
    assert sim.day == 1 and set(sim.goals.values()) == {"Learn carefully"}
    checkpoint = json.loads(run.latest_checkpoint().read_text())
    assert checkpoint["goals"] == sim.goals
    events = [Event.model_validate_json(s) for s in run.events_path.read_text().splitlines()]
    posts = [e for e in events if e.kind == EventKind.TASK_POSTED]
    assert posts and posts[0].time == time_at(1, "07:00")
    assert any(e.kind == EventKind.DAY_ENDED and e.time == time_at(1, "22:00") for e in events)
    resumed = Simulation.resume(run, setup)
    assert resumed.goals == sim.goals
    fail["enabled"] = True
    with pytest.raises(ExceptionGroup):
        await resumed.run()
    assert set(resumed.goals.values()) == {"Review edits"}
    fail["enabled"] = False
    resumed = Simulation.resume(run, setup)
    assert set(resumed.goals.values()) == {"Learn carefully"}
    await resumed.run()
    assert resumed.day == 2
    assert set(resumed.goals.values()) == {"Review edits"}
    from analysis import measure, read_run

    measured = measure(read_run(run.root))
    assert len(measured.agents) == 6  # Three residents, two completed days.


async def test_driver_delivers_busy_residents_news_only_after_their_action(clock):
    observations = {a: [] for a in clock.env.agents}
    office = work_place(clock)

    class Resident:
        def __init__(self, name):
            self.name = name

        async def act(self, observation):
            observations[self.name].append(observation)
            at = observation.time
            action = Pass()
            if at == time_at(1, "07:00"):
                action = Activity(operation="goal", topic="Repair a job")
            elif self.name == "Mei":
                if at == time_at(1, "07:05"):
                    action = ClaimTask(task_id="task-1")
                elif at == time_at(1, "07:55"):
                    action = Activity(operation="move", target=office)
                elif at == time_at(1, "08:00"):
                    action = RunCommand(task_id="task-1", command="pytest")
            elif self.name == "Tomas" and at == time_at(1, "08:05"):
                action = Activity(operation="invite", target="Mei", topic="The repair", remote=True)
            return Decision(thought="Next step", action=action)

    clock.sim.agents = {a: Resident(a) for a in clock.env.agents}
    clock.planned.clear()
    await clock.run(time_at(1, "07:00"))
    times = [o.time for o in observations["Mei"]]
    assert time_at(1, "08:05") not in times
    assert time_at(1, "08:10") not in times
    assert time_at(1, "08:20") in times
    after = next(o for o in observations["Mei"] if o.time == time_at(1, "08:20"))
    assert any("invites Mei" in p.text for p in after.percepts)
    assert any("new evidence" in p.text for p in after.percepts)
    assert time_at(1, "08:05") in [o.time for o in observations["Aisha"]]
    assert not clock.pending and not clock.grading
    assert all(clock.env.world.locations[a] == clock.env.config.homes[a] for a in clock.env.agents)
    log = logged(clock)
    assert [e.time for e in log] == sorted(e.time for e in log)
    assert all(
        e.payload["end"] <= time_at(1, "22:00") for e in log if e.kind == EventKind.ACTION_STARTED
    )


async def test_movement_completes_before_rechecking_discussion_start(clock):
    put_at_work(clock)
    now = time_at(1, "09:00")
    d = Discussion("d", "Mei", "Tomas", "repair", 20, accepted=True)
    clock.discussions[d.id] = d
    pending(clock, "Mei", Activity(operation="start", target="d"), now)
    pending(clock, "Tomas", Activity(operation="move", target=clock.env.config.homes["Tomas"]), now)
    await clock.complete(now + 5)
    assert not d.members
    assert any(e.kind == EventKind.ACTION_REJECTED and e.actor == "Mei" for e in logged(clock))


async def test_closing_completes_work_before_five_minute_return(clock):
    put_at_work(clock)
    now = time_at(1, "11:35")
    pending(clock, "Mei", ClaimTask(task_id="task-1"), now)
    await clock.complete(now + 5)
    pending(clock, "Mei", RunCommand(task_id="task-1", command="pytest"), now + 5, 20)
    await clock.complete(time_at(1, "12:00"))
    clock.boundary(time_at(1, "12:00"))
    assert clock.pending["Mei"].end == time_at(1, "12:05")
    assert clock.env.world.locations["Mei"] == work_place(clock)
    await clock.complete(time_at(1, "12:05"))
    assert clock.env.world.locations["Mei"] == clock.env.config.homes["Mei"]
