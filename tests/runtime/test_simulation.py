import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.agent import AgentSeed, CognitionConfig, Profile
from core.agent.evolution import EvolutionConfig, History, Level, SelfTrigger
from core.environment import Conditions, EnvironmentConfig, Place
from core.interaction import Event, EventKind, day_of, time_at
from infrastructure.llm import LLMRequest, RecordingClient, ScriptedClient
from infrastructure.storage import RunDirectory, RunStatus, read_jsonl
from runtime.scenes import SceneConfig, situations
from runtime.scheduler import Calendar
from runtime.simulation import Intervention, Setup, Simulation, SimulationConfig
from tasks.coding import BANK, CodingTaskProvider
from tests.core.agent.test_prompts import STEERING

AGENTS = ("Ana", "Ben", "Cai")
SOLUTIONS = yaml.safe_load(
    (Path(__file__).parents[1] / "tasks" / "coding" / "solutions.yaml").read_text(encoding="utf-8")
)
BY_ENTRY_POINT = {task.entry_point: name for name, task in CodingTaskProvider(BANK).bank.items()}
SLOT_STARTS = {"09:00": "morning", "13:00": "afternoon", "18:00": "evening"}
PLANS = {
    1: {
        "Ana": {"morning": "office", "evening": "cafe"},
        "Ben": {"morning": "office", "evening": "cafe"},
        "Cai": {"afternoon": "office", "evening": "cafe"},
    },
    2: {
        "Ana": {"morning": "office", "afternoon": "cafe"},
        "Ben": {"afternoon": "cafe", "evening": "park"},
        "Cai": {"morning": "office"},
    },
    3: {"Ben": {"morning": "moon"}, "Cai": {"night": "cafe"}},
}
L0, L1, L2 = Level.L0, Level.L1, Level.L2


class Script:
    """A scripted townsperson. It plans by PLANS; at work it claims the first open task and
    delivers its reference solution (Ben, the shortcut); in a conversation it speaks during
    the first three turns and passes after; at night it rates everyone it met. Its thoughts
    carry its name, so a leak shows. `fail` picks a request to raise on."""

    def __init__(self, fail: Callable[[LLMRequest], bool] = lambda request: False) -> None:
        self.requests: list[LLMRequest] = []
        self.fail = fail

    def __call__(self, request: LLMRequest) -> str | dict[str, Any]:
        self.requests.append(request)
        if self.fail(request):
            raise RuntimeError("the model server went away")
        agent, purpose, time = (request.metadata[key] for key in ("agent", "purpose", "time"))
        day = day_of(time)
        match purpose:
            case "diary":
                return f"{agent} wrote about day {day}."
            case "reflect":
                return {"reflection": "", "operations": [{"op": "add", "text": f"Day {day}."}]}
            case "skills":
                note = {"op": "write", "name": "routine", "description": "Days.", "body": "Work."}
                return {"reflection": "", "operations": [note]}
            case "policy":
                return {"rationale": "", "policy": f"Policy of day {day}."}
        prompt = request.messages[-1].content
        allowed = re.search(r"Choose one action: (.+)\. Your thought", prompt)[1].split(", ")
        return {"thought": f"secret-{agent}-{time}", "action": act(agent, time, prompt, allowed)}

    def prompts(self, agent: str) -> list[tuple[int, str]]:
        return [
            (request.metadata["time"], request.messages[-1].content)
            for request in self.requests
            if request.metadata["agent"] == agent and request.metadata["purpose"] == "act"
        ]


def act(agent: str, time: int, prompt: str, allowed: list[str]) -> dict[str, Any]:
    if "plan_day" in allowed:
        itinerary = PLANS[day_of(time)].get(agent, {})
        return {"kind": "plan_day", "itinerary": itinerary, "intention": "As planned."}
    if "claim_task" in allowed:
        if claimed := re.search(r"You have claimed (task-\d+)", prompt):
            task = BY_ENTRY_POINT[re.search(r"defines `(\w+)`", prompt)[1]]
            solution = SOLUTIONS[task]["shortcut" if agent == "Ben" else "reference"]
            return {
                "kind": "submit_work",
                "task_id": claimed[1],
                "solution": solution,
                "report": "",
            }
        board = re.findall(r"^- (task-\d+)", prompt, re.MULTILINE)
        return {"kind": "claim_task", "task_id": board[0]} if board else {"kind": "pass"}
    if "leave" in allowed:
        hour, minute = divmod(time % (24 * 60), 60)
        start = max(clock for clock in SLOT_STARTS if clock <= f"{hour:02d}:{minute:02d}")
        early = time - time_at(day_of(time), start) < 15
        return {"kind": "speak", "text": f"Hello from {agent}."} if early else {"kind": "pass"}
    met = re.search(r"spent time with (.+)\. You can", prompt)[1].replace(" and ", ", ")
    ratings = [{"target": peer, "score": 4, "reason": "We met."} for peer in met.split(", ")]
    return {"kind": "rate_peers", "ratings": ratings}


def place(id: str, kind: str, *residents: str) -> Place:
    return Place(id=id, kind=kind, name=f"the {id}", description="", x=0, y=0, residents=residents)


ENVIRONMENT = EnvironmentConfig(
    places=(
        place("flat", "home", "Ana"),
        place("house", "home", "Ben", "Cai"),
        place("office", "work"),
        place("cafe", "social"),
        place("park", "social"),
    ),
    conditions=Conditions(
        living_cost=5,
        tasks_per_day=3,
        reward_multiplier=1.0,
        defect_discovery_prob=0.5,
        clawback=True,
        esteem_public=False,
    ),
    initial_balance=100,
    esteem_half_life_days=2,
    task_shelf_life_days=3,
)
SIMULATION = SimulationConfig(
    days=3,
    calendar=Calendar(
        day_start="07:00",
        slots=[{"name": name, "start": clock} for clock, name in SLOT_STARTS.items()],
        day_end="22:00",
        weekly_days=2,
        monthly_days=3,
    ),
    scenes=SceneConfig(work_rounds=3, conversation_turns=6, turn_minutes=5),
    interventions=[
        Intervention(day=2, at="12:00", conditions={"living_cost": 9}, announcement="Rents rose.")
    ],
)


def new_run(root: Path, script: Script) -> tuple[RunDirectory, Setup]:
    """A new run directory under `root` and the setup of a run answered by `script`."""
    run = RunDirectory.create(root, "town", 7, config=SIMULATION, code_revision="test")
    return run, setup(run, script)


def setup(run: RunDirectory, script: Script) -> Setup:
    return Setup(
        simulation=SIMULATION,
        environment=ENVIRONMENT,
        agents=tuple(
            AgentSeed(profile=Profile(name=name, age=30, occupation="programmer", backstory=""))
            for name in AGENTS
        ),
        cognition=CognitionConfig(),
        evolution=EvolutionConfig(self_trigger=SelfTrigger(enabled=False)),
        provider=CodingTaskProvider(BANK),
        client=RecordingClient(ScriptedClient(script), run.llm_calls_path),
    )


def events(run: RunDirectory) -> list[Event]:
    return [Event.model_validate(record) for record in read_jsonl(run.events_path)]


def heads(run: RunDirectory) -> dict[str, str]:
    return {agent: History(run.agent_dir(agent)).head() for agent in AGENTS}


async def test_a_town_lives_through_its_days(tmp_path):
    script = Script()
    run, parts = new_run(tmp_path, script)
    assert await Simulation.create(run, parts).run() is RunStatus.COMPLETED
    assert run.read_manifest().status is RunStatus.COMPLETED
    log = events(run)
    assert [event.time for event in log] == sorted(event.time for event in log)

    started = [event.scene for event in log if event.kind is EventKind.SCENE_STARTED]
    assert started == [
        "day-0001/planning",
        "day-0001/morning/office",
        "day-0001/afternoon/office",
        "day-0001/evening/cafe",
        "day-0001/review",
        "day-0002/planning",
        "day-0002/morning/office",
        "day-0002/afternoon/cafe",
        "day-0002/review",
        "day-0003/planning",
    ]
    for day in (1, 2, 3):
        kinds = [event.kind for event in log if day_of(event.time) == day]
        assert kinds[0] is EventKind.DAY_STARTED
        ended = kinds.index(EventKind.DAY_ENDED)
        assert set(kinds[ended + 1 :]) == {EventKind.EVOLUTION}

    decisions = [event for event in log if event.kind is EventKind.DECISION]
    assert all(event.audience == () for event in decisions)
    assert {event.payload["thought"] for event in decisions} == {
        f"secret-{request.metadata['agent']}-{request.metadata['time']}"
        for request in script.requests
        if request.metadata["purpose"] == "act"
    }

    draws = [event for event in log if event.kind is EventKind.DRAW]
    assert (time_at(1, "09:00"), ("Ana", "Ben")) in {(e.time, e.audience) for e in draws}
    assert all(sorted(e.audience) == sorted(e.payload["order"]) for e in draws)
    assessed = [event for event in log if event.kind is EventKind.WORK_ASSESSED]
    accepted = {(e.actor, e.payload["quality"] == 1) for e in assessed if e.payload["passed"]}
    assert accepted == {("Ana", True), ("Ben", False), ("Cai", True)}
    speeches = [event for event in log if event.kind is EventKind.SPEECH]
    assert {(e.actor, e.place, day_of(e.time)) for e in speeches} == {
        *((agent, "cafe", 1) for agent in AGENTS),
        ("Ana", "cafe", 2),
        ("Ben", "cafe", 2),
    }
    ratings = {
        (e.actor, e.payload["target"], day_of(e.time)) for e in log if e.kind is EventKind.RATING
    }
    assert ratings == {
        *((rater, target, 1) for rater in AGENTS for target in AGENTS if rater != target),
        *(("Ana", peer, 2) for peer in ("Ben", "Cai")),
        *((peer, "Ana", 2) for peer in ("Ben", "Cai")),
    }

    [intervention] = [event for event in log if event.kind is EventKind.INTERVENTION]
    assert intervention.time == time_at(2, "12:00")
    before, after = log[: intervention.seq], log[intervention.seq :]
    assert "day-0002/morning/office" in {e.scene for e in before}
    assert "day-0002/afternoon/cafe" not in {e.scene for e in before}
    assert "day-0002/afternoon/cafe" in {e.scene for e in after}
    charged = {
        (day_of(e.time), e.payload["amount"]) for e in log if e.kind is EventKind.LIVING_COST
    }
    assert charged == {(1, 5), (2, 9), (3, 9)}
    for agent in AGENTS:
        later = [prompt for time, prompt in script.prompts(agent) if time > intervention.time]
        assert "Rents rose." in later[0].split("## New since your last decision")[1]

    day3 = time_at(3, "07:00")
    assert {time for agent in AGENTS for time, _ in script.prompts(agent) if time >= day3} == {day3}
    assert {
        (e.actor, e.audience) for e in log if e.kind is EventKind.ACTION_REJECTED and e.time >= day3
    } == {
        ("Cai", ("Cai",)),
        ("Ben", ("Ben",)),
    }
    assert all(time != time_at(1, "09:00") for time, _ in script.prompts("Cai"))

    diaries = [request for request in script.requests if request.metadata["purpose"] == "diary"]
    assert len(diaries) == 9
    assert all("Living costs" in request.messages[-1].content for request in diaries)
    for agent in AGENTS:
        steps = [(v.level, day_of(v.time)) for v in History(run.agent_dir(agent)).log() if v.level]
        assert sorted(steps) == [(L0, 1), (L0, 2), (L0, 3), (L1, 2), (L2, 3)]
        evolved = [
            (e.payload["level"], day_of(e.time))
            for e in log
            if e.kind is EventKind.EVOLUTION and e.actor == agent
        ]
        assert sorted(evolved) == sorted((str(level), day) for level, day in steps)

        for _, prompt in script.prompts(agent):
            others = [other for other in AGENTS if other != agent]
            assert not any(f"secret-{other}-" in prompt for other in others)
            assert "true quality" not in prompt and " rated " not in prompt
    assert [path.name for path in sorted(run.checkpoints_dir.iterdir())] == [
        f"day-{day:04d}.json" for day in range(4)
    ]


async def test_a_failed_day_resumes_from_its_checkpoint_to_the_same_end(tmp_path):
    uninterrupted, parts = new_run(tmp_path / "a", Script())
    await Simulation.create(uninterrupted, parts).run()

    def mid_conversation(request: LLMRequest) -> bool:
        return request.metadata["time"] == time_at(2, "13:05")

    run, parts = new_run(tmp_path / "b", Script(fail=mid_conversation))
    with pytest.raises(RuntimeError, match="went away"):
        await Simulation.create(run, parts).run()
    assert run.read_manifest().status is RunStatus.FAILED
    assert run.latest_checkpoint() == run.checkpoint_path(1)
    calls = len(list(read_jsonl(run.llm_calls_path)))

    parts = setup(run, Script())
    assert await Simulation.resume(run, parts).run() is RunStatus.COMPLETED
    assert run.read_manifest().status is RunStatus.COMPLETED
    assert run.events_path.read_bytes() == uninterrupted.events_path.read_bytes()
    assert heads(run) == heads(uninterrupted)
    assert len(list(read_jsonl(run.llm_calls_path))) > calls
    with pytest.raises(ValueError):
        Simulation.resume(run, parts)


def test_situation_texts_are_neutral():
    texts = [value for name, value in vars(situations).items() if name.isupper()]
    assert len(texts) > 10
    for text in texts:
        assert not STEERING.search(text), text
