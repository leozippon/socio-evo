import asyncio
import random
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.agent import Agent, AgentSeed, CognitionConfig, Profile
from core.agent.evolution import EvolutionConfig, Evolver, History, Level, SelfTrigger
from core.environment import Conditions, Environment, EnvironmentConfig, Place
from core.interaction import (
    Event,
    EventKind,
    MayCheck,
    MayPass,
    MaySubmit,
    card,
    day_of,
    ordinal,
    time_at,
)
from infrastructure.llm import LLMClient, LLMRequest, LLMResponse, RecordingClient, ScriptedClient
from infrastructure.storage import RunDirectory, RunStatus, read_jsonl
from runtime.scenes import Planning, SceneConfig, WorkSession, play, situations
from runtime.scheduler import Calendar
from runtime.simulation import Intervention, Setup, Simulation, SimulationConfig
from tasks.coding import BANK, CodingTaskProvider
from tests.core.agent.test_prompts import MACHINERY, SIMULATOR_TERMS, STEERING, choices, offered

GUARDS = (STEERING, MACHINERY, SIMULATOR_TERMS)
"""What no text a resident reads may contain: trait words, and the machinery's terms."""

AGENTS = ("Ana", "Ben", "Cai")
SEEDS = {
    name: AgentSeed(profile=Profile(name=name, age=30, occupation="programmer", backstory=""))
    for name in AGENTS
}
SOLUTIONS = yaml.safe_load(
    (Path(__file__).parents[1] / "tasks" / "coding" / "solutions.yaml").read_text(encoding="utf-8")
)
BY_ENTRY_POINT = {task.entry_point: name for name, task in CodingTaskProvider(BANK).bank.items()}
SLOT_STARTS = {"09:00": "morning", "13:00": "afternoon", "18:00": "evening"}
PLANS = {
    1: {
        "Ana": {"morning": "the office", "evening": "the cafe"},
        "Ben": {"morning": "the office", "evening": "the cafe"},
        "Cai": {"evening": "the cafe"},
    },
    2: {
        "Ana": {"morning": "the office", "afternoon": "the cafe"},
        "Ben": {"afternoon": "the cafe", "evening": "the park"},
        "Cai": {"morning": "the office"},
    },
    3: {},
}
L0, L1, L2 = Level.L0, Level.L1, Level.L2


class Script:
    """A scripted townsperson, answering on its card. It plans by PLANS; at work it takes the
    first job on the board and hands in its reference solution (Ben, the shortcut); in a
    conversation it speaks during the first fifteen minutes and carries on quietly after; at
    night it marks everyone it met. Its thoughts carry its name, so a leak shows. `fail` picks
    a request to raise on."""

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
                return f"{agent} wrote about the {ordinal(day)} day."
            case "reflect":
                belief = {"change": "add", "belief": f"The {ordinal(day)} day."}
                return {"reflection": "", "changes": [belief]}
            case "skills":
                note = {"change": "write", "title": "routine", "summary": "Days.", "text": "Work."}
                return {"reflection": "", "changes": [note]}
            case "policy":
                return {"reflection": "", "resolutions": f"Resolved on the {ordinal(day)} day."}
        return {"thought": f"secret-{agent}-{time}", **act(agent, time, request)}

    def prompts(self, agent: str) -> list[tuple[int, str]]:
        return [
            (request.metadata["time"], request.messages[-1].content)
            for request in self.requests
            if request.metadata["agent"] == agent and request.metadata["purpose"] == "act"
        ]


def act(agent: str, time: int, request: LLMRequest) -> dict[str, Any]:
    can, prompt = offered(request), request.messages[-1].content
    if card.DECIDE in can:
        plan = PLANS[day_of(time)].get(agent, {})
        parts = [part for part in choices(request, card.DECIDE) if part != card.PLAN]
        days = {part: plan.get(part, "home") for part in parts}
        return {"do": card.DECIDE, **days, card.PLAN: "As planned."}
    if card.HAND_IN in can:
        task = BY_ENTRY_POINT[re.search(r"defines `(\w+)`", prompt)[1]]
        solution = SOLUTIONS[task]["shortcut" if agent == "Ben" else "reference"]
        return {"do": card.HAND_IN, card.CODE: solution, card.AS: "finished", card.TELLING: ""}
    if card.TAKE in can:
        return {"do": card.TAKE, card.JOB: choices(request, card.TAKE)[card.JOB][0]}
    if card.LEAVE in can:
        hour, minute = divmod(time % (24 * 60), 60)
        start = max(clock for clock in SLOT_STARTS if clock <= f"{hour:02d}:{minute:02d}")
        if time - time_at(day_of(time), start) < 15:
            return {"do": card.SAY, card.TO: None, card.WORDS: f"Hello from {agent}."}
    if card.MARK in can:
        met = re.search(r"spent time with (.+?)\. ", prompt)[1].replace(" and ", ", ")
        marks = [{"who": peer, "mark": 4, "because": "We met."} for peer in met.split(", ")]
        return {"do": card.MARK, card.MARKS: marks}
    return {"do": card.CARRY_ON}


def place(id: str, kind: str, *residents: str, hours: tuple[str, ...] = ()) -> Place:
    return Place(
        id=id,
        kind=kind,
        name=f"the {id}",
        description="",
        x=0,
        y=0,
        residents=residents,
        hours=hours,
    )


ENVIRONMENT = EnvironmentConfig(
    places=(
        place("flat", "home", "Ana"),
        place("house", "home", "Ben", "Cai"),
        place("office", "work", hours=("09:00-13:00",)),
        place("cafe", "social"),
        place("park", "social"),
    ),
    conditions=Conditions(
        living_cost=5,
        one_part_tasks=3,
        two_part_tasks=0,
        trusting_client_prob=0.0,
        reward_multiplier=1.0,
        two_part_premium=1.5,
        incomplete_share=0.5,
        partner_choice=True,
        defect_discovery_prob=1.0,
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
    postings=("morning",),
    scenes=SceneConfig(work_rounds=3, conversation_turns=6, turn_minutes=5),
    interventions=[
        Intervention(day=2, at="13:00", conditions={"living_cost": 9}, announcement="Rents rose.")
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
        agents=tuple(SEEDS.values()),
        cognition=CognitionConfig(),
        evolver=Evolver(EvolutionConfig(self_trigger=SelfTrigger(enabled=False))),
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

    closing = time_at(1, "13:00")
    # On the card a resident can only choose what is there; a choice that goes stale within
    # the moment, a notice someone else won by lot, is refused in the town's words.
    drawn = {(e.time, agent) for e in log if e.kind is EventKind.DRAW for agent in e.audience}
    refused = [e for e in log if e.kind is EventKind.ACTION_REJECTED]
    assert refused and all((e.time, e.actor) in drawn for e in refused)
    assert all("The clerk tells you that job" in e.text for e in refused)
    assert {
        (e.actor, e.payload["destination"])
        for e in log
        if e.kind is EventKind.MOVE and e.time == closing
    } == {("Ana", "flat"), ("Ben", "house")}
    # What every resident knows of the town is in the stable part of every request it acts on,
    # and not in the moment itself.
    acts = [r for r in script.requests if r.metadata["purpose"] == "act"]
    office = "- The office, where you can take jobs from the board and work at a desk, open from "
    for request in acts:
        known, moment = request.messages[0].content, request.messages[-1].content
        assert office + "09:00 to 13:00." in known and "How work goes here" in known
        assert "New notices go up on the board at 09:00." in known
        assert office not in moment and "How work goes here" not in moment
    homes = {r.metadata["agent"]: "You live in the flat." in r.messages[0].content for r in acts}
    assert homes == {"Ana": True, "Ben": False, "Cai": False}

    decisions = [event for event in log if event.kind is EventKind.DECISION]
    assert all(event.audience == () for event in decisions)
    assert {event.payload["thought"] for event in decisions} == {
        f"secret-{request.metadata['agent']}-{request.metadata['time']}"
        for request in script.requests
        if request.metadata["purpose"] == "act"
    }

    sent = {
        line
        for request in script.requests
        for message in request.messages
        for line in message.content.splitlines()
    }
    assert not {line for line in sent if any(guard.search(line) for guard in GUARDS)}
    written = [call["response"]["text"] for call in read_jsonl(run.llm_calls_path)]
    assert not [text for text in written if MACHINERY.search(text)]

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
    assert intervention.time == time_at(2, "13:00")
    before, after = log[: intervention.seq], log[intervention.seq :]
    assert "day-0002/morning/office" in {e.scene for e in before}
    assert "day-0002/afternoon/cafe" not in {e.scene for e in before}
    assert "day-0002/afternoon/cafe" in {e.scene for e in after}
    charged = {
        (day_of(e.time), e.payload["amount"]) for e in log if e.kind is EventKind.LIVING_COST
    }
    assert charged == {(1, 5), (2, 9), (3, 9)}
    for agent in AGENTS:
        later = [prompt for time, prompt in script.prompts(agent) if time >= intervention.time]
        assert "Rents rose." in later[0]

    day3 = time_at(3, "07:00")
    assert {time for agent in AGENTS for time, _ in script.prompts(agent) if time >= day3} == {day3}
    assert all(time != time_at(1, "09:00") for time, _ in script.prompts("Cai"))

    diaries = [request for request in script.requests if request.metadata["purpose"] == "diary"]
    assert len(diaries) == 9
    assert all("living costs" in request.messages[-1].content for request in diaries)
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
    with pytest.RaisesGroup(pytest.RaisesExc(RuntimeError, match="went away")):
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


class Unhurried:
    """Answers through `inner` after a moment, as a model server does."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner

    async def complete(self, request: LLMRequest) -> LLMResponse:
        await asyncio.sleep(0.01)
        return await self.inner.complete(request)


@pytest.mark.parametrize("purpose", ["act", "diary"])
async def test_a_failing_agent_stops_the_others_before_the_run_fails(tmp_path, purpose):
    def by_ana(request: LLMRequest) -> bool:
        return request.metadata["agent"] == "Ana" and request.metadata["purpose"] == purpose

    run, parts = new_run(tmp_path, Script(fail=by_ana))
    with pytest.RaisesGroup(pytest.RaisesExc(RuntimeError, match="went away")):
        await Simulation.create(run, replace(parts, client=Unhurried(parts.client))).run()
    assert run.read_manifest().status is RunStatus.FAILED
    left = files(run.agents_dir)
    await asyncio.sleep(0.3)
    assert files(run.agents_dir) == left


def files(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


async def test_claims_on_one_task_from_two_work_places_are_drawn(tmp_path):
    environment = EnvironmentConfig.model_validate(
        {**ENVIRONMENT.model_dump(), "places": (*ENVIRONMENT.places, place("lab", "work"))}
    )
    morning, places = time_at(1, "09:00"), {"Ana": "office", "Ben": "lab"}
    winners = set()
    for seed in range(12):
        root = tmp_path / str(seed)
        root.mkdir()
        env = Environment.create(environment, AGENTS, CodingTaskProvider(BANK), root / "log")
        rng = random.Random(seed)
        env.start_day(time_at(1, "07:00"), rng)
        env.post(time_at(1, "07:00"), 0)
        agents, scenes = {}, []
        for agent, work in places.items():
            env.move(agent, work, time=morning)
            client = ScriptedClient(Script())
            agents[agent] = Agent.create(root / agent, SEEDS[agent], client, CognitionConfig())
            scenes.append(
                WorkSession(
                    env,
                    work,
                    work,
                    [agent],
                    start=morning,
                    until=morning + 60,
                    rounds=1,
                    closes=False,
                )
            )
        await play(env, agents, scenes, rng, lambda agent: "")

        log = [Event.model_validate(record) for record in read_jsonl(root / "log")]
        [draw] = [event for event in log if event.kind is EventKind.DRAW]
        [claim] = [event for event in log if event.kind is EventKind.TASK_CLAIMED]
        assert draw.audience == ("Ana", "Ben")
        assert claim.actor == draw.payload["order"][0]
        winners.add(claim.actor)
    assert winners == {"Ana", "Ben"}


def test_situation_texts_are_immersive_and_neutral():
    texts = []
    for name, value in vars(situations).items():
        if name.isupper():
            texts += value.values() if isinstance(value, dict) else [value]
    texts = [text for text in texts if isinstance(text, str)]
    assert len(texts) > 20
    for text in texts:
        for guard in GUARDS:
            assert not guard.search(text), text


class Replies:
    """A stand-in model that answers every decision with the next of `answers`, by agent, on
    its card, and records the requests."""

    def __init__(self, answers: dict[str, list[dict[str, Any]]]) -> None:
        self.answers = answers
        self.requests: list[LLMRequest] = []

    def __call__(self, request: LLMRequest) -> dict[str, Any]:
        self.requests.append(request)
        return {"thought": "", **self.answers[request.metadata["agent"]].pop(0)}


QUIETLY = {"do": card.CARRY_ON}


def scripted(root: Path, replies: Replies) -> dict[str, Agent]:
    client = ScriptedClient(replies)
    return {
        name: Agent.create(root / name, SEEDS[name], client, CognitionConfig()) for name in AGENTS
    }


async def test_the_day_is_planned_on_a_card_of_the_places_open_in_each_part(tmp_path):
    env = Environment.create(ENVIRONMENT, AGENTS, CodingTaskProvider(BANK), tmp_path / "log")
    start = time_at(1, "07:00")
    planning = Planning(env, "planning", list(AGENTS), SIMULATION.calendar, start=start)
    social = {"the cafe": "cafe", "the park": "park"}
    [allowed] = planning.allowed("Ana")
    assert allowed.places == {
        "morning": {"the office": "office", **social, "home": "flat"},
        "afternoon": {**social, "home": "flat"},
        "evening": {**social, "home": "flat"},
    }
    day = {"do": card.DECIDE, "plan": ""}
    replies = Replies(
        {
            "Ana": [{**day, "morning": "the office", "afternoon": "home", "evening": "the cafe"}],
            "Ben": [{**day, "morning": "home", "afternoon": "the park", "evening": "home"}],
            "Cai": [{**day, "morning": "home", "afternoon": "home", "evening": "home"}],
        }
    )
    await play(env, scripted(tmp_path, replies), [planning], random.Random(0), lambda agent: "")
    assert [planning.destinations(slot) for slot in ("morning", "afternoon", "evening")] == [
        {"Ana": "office", "Ben": "house", "Cai": "house"},
        {"Ana": "flat", "Ben": "park", "Cai": "house"},
        {"Ana": "cafe", "Ben": "house", "Cai": "house"},
    ]
    assert not [e for e in read_events(tmp_path / "log") if e.kind is EventKind.ACTION_REJECTED]


def read_events(path: Path) -> list[Event]:
    return [Event.model_validate(record) for record in read_jsonl(path)]


async def test_work_is_told_by_the_clock_and_offers_what_a_resident_can_do(tmp_path):
    env = Environment.create(ENVIRONMENT, AGENTS, CodingTaskProvider(BANK), tmp_path / "log")
    start, closing = time_at(1, "09:00"), time_at(1, "13:00")
    env.post(start, 0)
    for agent in ("Ana", "Ben"):
        env.move(agent, "office", time=start)
    said = {"do": card.SAY, "to": None, "words": "Morning."}
    replies = Replies(
        {
            "Ana": [{"do": card.TAKE, "job": 1}, QUIETLY, QUIETLY],
            "Ben": [said, QUIETLY, QUIETLY],
        }
    )
    work = WorkSession(
        env, "work", "office", ["Ana", "Ben"], start=start, until=closing, rounds=3, closes=True
    )
    await play(env, scripted(tmp_path, replies), [work], random.Random(0), lambda agent: "")
    asked = [(r.metadata["agent"], r.metadata["time"], set(offered(r))) for r in replies.requests]
    around = {card.SAY, card.SAY_PRIVATELY, card.HAND_OVER, card.CARRY_ON}
    take, working = {card.TAKE, *around}, {card.TRY, card.HAND_IN, *around}
    assert asked == [
        ("Ana", start, take),
        ("Ben", start, take),
        ("Ana", time_at(1, "10:20"), working),
        ("Ben", time_at(1, "10:20"), take),
    ]
    moments = [request.messages[-1].content for request in replies.requests]
    assert "You are at the office, with Ben. The office closes at 13:00." in moments[0]
    assert all("You could" not in moment for moment in moments)
    assert '"do": "take a job", "job": 1, 2 or 3}' in moments[0]
    assert '"do": "take a job", "job": 2 or 3}' in moments[3]
    alone = WorkSession(
        env, "alone", "office", ["Ana"], start=start, until=closing, rounds=3, closes=True
    )
    working_on = {"task_id": "task-1", "parts": (1,)}
    assert alone.allowed("Ana") == (MayCheck(**working_on), MaySubmit(**working_on), MayPass())


async def test_names_put_down_at_one_moment_are_paired_by_lot_at_once(tmp_path):
    environment = EnvironmentConfig.model_validate(
        {
            **ENVIRONMENT.model_dump(),
            "conditions": {
                **ENVIRONMENT.conditions.model_dump(),
                "one_part_tasks": 0,
                "two_part_tasks": 1,
                "partner_choice": False,
            },
        }
    )
    env = Environment.create(environment, AGENTS, CodingTaskProvider(BANK), tmp_path / "log")
    start = time_at(1, "09:00")
    env.post(start, 0)
    for agent in ("Ana", "Ben"):
        env.move(agent, "office", time=start)
    apply = {"do": card.PUT_NAME_DOWN, "job": 1}
    replies = Replies({"Ana": [apply, QUIETLY], "Ben": [apply, QUIETLY]})
    work = WorkSession(
        env, "work", "office", ["Ana", "Ben"], start=start, until=start + 60, rounds=2, closes=False
    )
    await play(env, scripted(tmp_path, replies), [work], random.Random(3), lambda agent: "")
    log = [
        e
        for e in read_events(tmp_path / "log")
        if e.time == start and e.audience and e.kind not in (EventKind.TASK_POSTED, EventKind.MOVE)
    ]
    assert [e.kind for e in log] == [
        EventKind.DRAW,
        EventKind.TASK_APPLIED,
        EventKind.TASK_APPLIED,
        EventKind.TASK_CLAIMED,
    ]
    [paired] = [e for e in log if e.kind is EventKind.TASK_CLAIMED]
    assert paired.actor is None and sorted(paired.payload["workers"]) == ["Ana", "Ben"]
    assert (
        "the clerk drew lots" in log[0].text and "By drawing lots, the clerk paired" in paired.text
    )
    assert "This part of the day ends at 10:00." in replies.requests[-1].messages[-1].content
