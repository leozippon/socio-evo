import asyncio
import random
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from analysis import meetings as meetings_of
from analysis import read_run
from core.agent import Agent, AgentSeed, CognitionConfig, Profile
from core.agent.evolution import EvolutionConfig, Evolver, History, Level, SelfTrigger
from core.environment import Conditions, Environment, EnvironmentConfig, Place, Trade
from core.interaction import (
    Event,
    EventKind,
    MayCheck,
    MayLeave,
    MayPass,
    MaySubmit,
    Setting,
    card,
    clock_of,
    day_of,
    ordinal,
    time_at,
)
from infrastructure.llm import LLMClient, LLMRequest, LLMResponse, RecordingClient, ScriptedClient
from infrastructure.storage import RunDirectory, RunStatus, read_jsonl
from runtime.scenes import (
    Conversation,
    Meeting,
    Planning,
    SceneConfig,
    WorkSession,
    play,
    situations,
)
from runtime.scheduler import Calendar
from runtime.simulation import Intervention, Setup, Simulation, SimulationConfig
from tasks.coding import BANK, CodingTaskProvider
from tests.core.agent.test_prompts import MACHINERY, SIMULATOR_TERMS, STEERING, choices, offered
from tests.core.environment.test_environment import as_told_to

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
    a request to raise on, as a server that went away does; `garble` picks a request to answer
    with nothing that can be read, every time it is asked."""

    def __init__(
        self,
        fail: Callable[[LLMRequest], bool] = lambda request: False,
        garble: Callable[[LLMRequest], bool] = lambda request: False,
    ) -> None:
        self.requests: list[LLMRequest] = []
        self.fail = fail
        self.garble = garble

    def __call__(self, request: LLMRequest) -> str | dict[str, Any]:
        self.requests.append(request)
        if self.fail(request):
            raise RuntimeError("the model server went away")
        if self.garble(request):
            return "" if request.json_schema is None else "Hmm, let me think about that."
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
        told = f"Handed in at {time} from desk {AGENTS.index(agent) + 1}."
        return {"do": card.HAND_IN, card.CODE: solution, card.AS: "finished", card.TELLING: told}
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


def told_twice(run: RunDirectory) -> tuple[list[str], int]:
    """What a moment of `run` told twice, and how many facts were checked: the notice of a
    job, the words a worker told a client with work it handed in (which a fault that comes to
    light later quotes again, as its cause), and the posted standings, each told at most once
    in any request a resident acted on."""
    log = [Event.model_validate(line) for line in read_jsonl(run.events_path)]
    notices = [
        event.text.removeprefix("A new notice on the board: ").removesuffix(".")
        for event in log
        if event.kind is EventKind.TASK_POSTED
    ]
    said = Counter(
        words
        for event in log
        for words in (event.payload.get("utterance"), event.payload.get("note"))
        if words
    )
    reports = Counter(
        event.payload["report"] for event in log if event.kind is EventKind.WORK_SUBMITTED
    )
    unique = [report for report, n in reports.items() if n == 1 and report not in said]
    moments = [
        call["request"]["messages"][-1]["content"]
        for call in read_jsonl(run.llm_calls_path)
        if call["metadata"]["purpose"] == "act"
    ]
    twice, checked = [], 0
    for moment in moments:
        handed = "\n".join(line for line in moment.splitlines() if "A fault has come" not in line)
        told = [(notice.lower(), moment.lower()) for notice in notices]
        for fact, text in [*told, *((report, handed) for report in unique)]:
            checked += fact in text
            if text.count(fact) > 1:
                twice.append(fact)
        if "tonight's standings" in moment and "The standings posted" in moment:
            twice.append("the standings")
    return twice, checked


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
        providers={Trade.PROGRAMMING: CodingTaskProvider(BANK)},
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
    # The purse says what a day costs as the conditions stand: the rise on day 2 at 13:00 shows
    # in every moment after it, at work or in company.
    costs = {
        (request.metadata["time"] >= time_at(2, "13:00"), cost)
        for request in acts
        for cost in re.findall(r"; the day costs you \d+ crowns\.", request.messages[-1].content)
    }
    assert costs == {
        (False, "; the day costs you 5 crowns."),
        (True, "; the day costs you 9 crowns."),
    }

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
    # No moment tells a notice, or what a worker told a client, twice.
    twice, checked = told_twice(run)
    assert checked > 10 and not twice, twice
    written = [call["response"]["text"] for call in read_jsonl(run.llm_calls_path)]
    assert not [text for text in written if MACHINERY.search(text)]

    draws = [event for event in log if event.kind is EventKind.DRAW]
    assert (time_at(1, "09:00"), ("Ana", "Ben")) in {(e.time, e.audience) for e in draws}
    assert all(sorted(e.audience) == sorted(e.payload["order"]) for e in draws)
    # A resident is told about itself as `you`, in what it witnesses and in each moment; a
    # move as an arrival or a departure, and work it handed in by what followed.
    for event in log:
        for witness in event.audience:
            told = event.percept(witness).text
            if event.kind is EventKind.MOVE:
                arrived, left = (f"{event.actor} {verb} " for verb in ("arrived at", "left"))
                came = f"{event.actor} came home from "
                assert told.startswith((arrived, came, left)) or told == event.text
            elif event.kind is EventKind.WORK_SUBMITTED and witness == event.actor:
                assert ", is in: " in told and "told the client" not in told
            else:
                assert told == as_told_to(event.text, witness)
    assert all(draw.personal.keys() == set(draw.audience) for draw in draws)
    for agent in AGENTS:
        for _, prompt in script.prompts(agent):
            assert not re.search(rf"\b{agent}\b", re.sub(r'"[^"]*"', "", prompt)), prompt
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


def lapsing(request: LLMRequest) -> bool:
    """The replies that cannot be obtained in the runs of these tests: Ben's plan for the
    second day, Cai's every word in the first evening's conversation, and Ana's reflection on
    the first night."""
    agent, purpose, time = (request.metadata[key] for key in ("agent", "purpose", "time"))
    return (
        (agent, purpose, time) == ("Ben", "act", time_at(2, "07:00"))
        or (
            agent == "Cai"
            and purpose == "act"
            and time_at(1, "18:00") <= time < time_at(1, "19:00")
        )
        or (agent, purpose, time) == ("Ana", "reflect", time_at(1, "22:00"))
    )


async def test_a_reply_that_cannot_be_obtained_is_a_recorded_lapse_and_the_town_goes_on(tmp_path):
    run, parts = new_run(tmp_path, Script(garble=lapsing))
    assert await Simulation.create(run, parts).run() is RunStatus.COMPLETED
    log = events(run)
    lapses = [event for event in log if event.kind is EventKind.LAPSE]
    assert all(event.audience == () for event in lapses)
    assert all(
        len(e.payload["failures"]) == 3
        and all(f.startswith("invalid:") for f in e.payload["failures"])
        for e in lapses
    )
    moments = [e for e in lapses if e.payload["level"] is None]
    assert {(e.actor, e.scene) for e in moments} == {
        ("Ben", "day-0002/planning"),
        ("Cai", "day-0001/evening/cafe"),
    }
    decided = {(e.actor, e.time) for e in log if e.kind is EventKind.DECISION}
    assert all((e.actor, e.time) not in decided for e in moments)
    # Ben planned nothing for the second day, so he spent it at home; the first evening's
    # conversation went on without Cai's words.
    assert not [
        e for e in log if e.kind is EventKind.MOVE and e.actor == "Ben" and day_of(e.time) == 2
    ]
    evening = [e for e in log if e.scene == "day-0001/evening/cafe"]
    assert {e.actor for e in evening if e.kind is EventKind.SPEECH} == {"Ana", "Ben"}
    assert evening[-1].kind is EventKind.SCENE_ENDED
    # Ana's first night was skipped: nothing committed, her diary of that night discarded.
    [night] = [e for e in lapses if e.payload["level"] is not None]
    assert (night.actor, night.time, night.payload["level"], night.payload["trigger"]) == (
        "Ana",
        time_at(1, "22:00"),
        "L0",
        "daily",
    )
    history = History(run.agent_dir("Ana"))
    assert not [v for v in history.log() if v.level and day_of(v.time) == 1]
    assert not (run.agent_dir("Ana") / "memory" / "diary" / "day-0001.md").exists()
    assert (run.agent_dir("Ana") / "memory" / "diary" / "day-0002.md").exists()
    assert [day_of(e.time) for e in log if e.kind is EventKind.EVOLUTION and e.actor == "Ana"] == [
        2,
        2,
        3,
        3,
    ]


async def test_a_run_whose_lapses_exceed_their_share_fails(tmp_path):
    def anas(request: LLMRequest) -> bool:
        """Every moment of Ana's but her plans, so that she is out and about."""
        metadata = request.metadata
        return (metadata["agent"], metadata["purpose"]) == ("Ana", "act") and (
            card.DECIDE not in offered(request)
        )

    run, parts = new_run(tmp_path / "a", Script(garble=anas))
    lenient = replace(parts, simulation=SIMULATION.model_copy(update={"max_lapse_share": 0.5}))
    assert await Simulation.create(run, lenient).run() is RunStatus.COMPLETED
    lapsed = [e for e in events(run) if e.kind is EventKind.LAPSE]
    assert len(lapsed) >= 10 and {e.actor for e in lapsed} == {"Ana"}

    run, parts = new_run(tmp_path / "b", Script(garble=anas))
    with pytest.raises(RuntimeError, match="lapsed for want of a valid reply"):
        await Simulation.create(run, parts).run()
    assert run.read_manifest().status is RunStatus.FAILED


async def test_a_failed_day_resumes_from_its_checkpoint_to_the_same_end(tmp_path):
    uninterrupted, parts = new_run(tmp_path / "a", Script(garble=lapsing))
    await Simulation.create(uninterrupted, parts).run()

    def at_work(request: LLMRequest) -> bool:
        return (request.metadata["agent"], request.metadata["time"]) == ("Cai", time_at(2, "09:00"))

    run, parts = new_run(tmp_path / "b", Script(fail=at_work, garble=lapsing))
    with pytest.RaisesGroup(pytest.RaisesExc(RuntimeError, match="went away")):
        await Simulation.create(run, parts).run()
    assert run.read_manifest().status is RunStatus.FAILED
    assert run.latest_checkpoint() == run.checkpoint_path(1)
    calls = len(list(read_jsonl(run.llm_calls_path)))

    parts = setup(run, Script(garble=lapsing))
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
            cognition = CognitionConfig()
            agents[agent] = Agent.create(root / agent, SEEDS[agent], client, cognition, Setting())
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
        name: Agent.create(root / name, SEEDS[name], client, CognitionConfig(), Setting())
        for name in AGENTS
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


def test_an_empty_board_says_when_new_notices_go_up(tmp_path):
    env = Environment.create(ENVIRONMENT, AGENTS, CodingTaskProvider(BANK), tmp_path / "log")
    calendar, dawn = SIMULATION.calendar, time_at(1, "07:00")
    morning, afternoon = time_at(1, "09:00"), time_at(1, "13:00")
    both = ("morning", "afternoon")
    assert situations.next_posting(calendar, both, dawn) == morning
    assert situations.next_posting(calendar, both, morning) == afternoon
    assert situations.next_posting(calendar, both, afternoon) == time_at(2, "09:00")
    assert situations.next_posting(calendar, (), dawn) is None
    planning = Planning(env, "planning", AGENTS, calendar, start=dawn, posting=morning)
    empty = "There are no notices on the board. New notices go up at 09:00."
    assert empty in planning.situation("Ana")
    later = WorkSession(
        env,
        "work",
        "office",
        ["Ana"],
        start=afternoon - 60,
        until=afternoon,
        rounds=1,
        closes=True,
        posting=time_at(2, "09:00"),
    )
    tomorrow = "There are no notices on the board. New notices go up tomorrow at 09:00."
    assert tomorrow in later.situation("Ana")
    unknown = Planning(env, "planning", AGENTS, calendar, start=dawn)
    assert "New notices" not in unknown.situation("Ana")
    env.post(dawn, 0)
    assert "New notices" not in planning.situation("Ana")
    assert planning.shown() == (EventKind.TASK_POSTED,) and later.shown() == planning.shown()


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
    around = {card.SAY, card.SAY_PRIVATELY, card.HAND_OVER, card.LEAVE, card.CARRY_ON}
    take, working = {card.TAKE, *around}, {card.TRY, card.HAND_IN, *around}
    assert asked == [
        ("Ana", start, take),
        ("Ben", start, take),
        ("Ana", time_at(1, "10:20"), working),
        ("Ben", time_at(1, "10:20"), take),
    ]
    moments = [request.messages[-1].content for request in replies.requests]
    assert (
        "You are at the office, with Ben. The office closes at 13:00. Whatever you do now will "
        "take you to 10:20."
    ) in moments[0]
    assert "Whatever you do now will take you to 11:40." in moments[2]
    assert all("You could" not in moment for moment in moments)
    assert '"do": "take a job", "job": one of 1, 2, 3}' in moments[0]
    assert '"do": "take a job", "job": one of 2, 3}' in moments[3]
    last = WorkSession(
        env,
        "last",
        "office",
        ["Cai"],
        start=time_at(1, "12:30"),
        until=closing,
        rounds=1,
        closes=True,
    )
    assert "Whatever you do now will take you to 13:00, when the office closes." in (
        last.situation("Cai")
    )
    ends = WorkSession(
        env,
        "ends",
        "office",
        ["Cai"],
        start=start,
        until=time_at(1, "12:00"),
        rounds=3,
        closes=False,
    )
    ends.turns = 2
    assert "Whatever you do now will take you to 12:00, when this part of the day ends." in (
        ends.situation("Cai")
    )
    alone = WorkSession(
        env, "alone", "office", ["Ana"], start=start, until=closing, rounds=3, closes=True
    )
    working_on = {"task_id": "task-1", "parts": (1,)}
    assert alone.allowed("Ana") == (
        MayCheck(**working_on),
        MaySubmit(**working_on),
        MayLeave(),
        MayPass(),
    )


async def test_one_who_leaves_goes_home_for_the_rest_of_the_part_and_is_asked_nothing_more(
    tmp_path,
):
    env = Environment.create(ENVIRONMENT, AGENTS, CodingTaskProvider(BANK), tmp_path / "log")
    morning, evening = time_at(1, "09:00"), time_at(1, "18:00")
    for agent in ("Ana", "Ben"):
        env.move(agent, "office", time=morning)
    home = {"do": card.LEAVE}
    replies = Replies({"Ana": [home], "Ben": [QUIETLY] * 9, "Cai": [QUIETLY] * 9})
    agents = scripted(tmp_path, replies)
    work = WorkSession(
        env, "work", "office", ["Ana", "Ben"], start=morning, until=evening, rounds=3, closes=False
    )
    await play(env, agents, [work], random.Random(0), lambda agent: "")
    assert env.world.locations["Ana"] == "flat" and work.present == ["Ben"]
    assert [r.metadata["agent"] for r in replies.requests].count("Ana") == 1
    log = read_events(tmp_path / "log")
    [gone] = [e for e in log if e.kind is EventKind.MOVE and e.scene == "work"]
    assert (gone.actor, gone.place, gone.audience) == ("Ana", "office", ("Ben",))
    assert gone.text == "Ana left the office for home."
    assert gone.payload == {"origin": "office", "destination": "flat"}

    replies.answers["Ana"] = [home]
    for agent in ("Ana", "Ben", "Cai"):
        env.move(agent, "cafe", time=evening)
    talk = Conversation(
        env,
        "talk",
        "cafe",
        ["Ana", "Ben", "Cai"],
        start=evening,
        step=5,
        max_turns=12,
        until=time_at(1, "22:00"),
        rng=random.Random(1),
    )
    await play(env, agents, [talk], random.Random(0), lambda agent: "")
    assert env.world.locations["Ana"] == "flat" and sorted(talk.present) == ["Ben", "Cai"]
    [gone] = [
        e for e in read_events(tmp_path / "log") if e.scene == "talk" and e.kind is EventKind.MOVE
    ]
    assert gone.text == "Ana left the cafe for home." and set(gone.audience) == {"Ben", "Cai"}
    assert [r.metadata["agent"] for r in replies.requests].count("Ana") == 2


async def test_a_conversation_ends_when_its_place_closes_and_the_day_ends_with_closing(tmp_path):
    """The cafe closes at 18:12, within the evening's conversation; the park keeps no hours,
    so it is open until the day ends, when everyone still out goes home: from the park as it
    closes, from the cafe, closed since 18:12, plainly."""
    places = [
        place("cafe", "social", hours=("07:00-18:12",)) if p.id == "cafe" else p
        for p in ENVIRONMENT.places
    ]
    environment = EnvironmentConfig.model_validate({**ENVIRONMENT.model_dump(), "places": places})
    plans, night = {"Ana": "the cafe", "Ben": "the cafe", "Cai": "the park"}, Script()

    def talker(request: LLMRequest) -> str | dict[str, Any]:
        agent = request.metadata["agent"]
        if request.metadata["purpose"] != "act":
            return night(request)
        if card.DECIDE in offered(request):
            parts = [part for part in choices(request, card.DECIDE) if part != card.PLAN]
            evening = {part: plans[agent] if part == "evening" else "home" for part in parts}
            return {"thought": "", "do": card.DECIDE, **evening, card.PLAN: ""}
        if card.SAY in offered(request):
            return {"thought": "", "do": card.SAY, card.TO: None, card.WORDS: "Still here."}
        return {"thought": "", "do": card.CARRY_ON}

    run = RunDirectory.create(tmp_path, "town", 7, config=SIMULATION, code_revision="test")
    parts = replace(
        setup(run, Script()),
        environment=environment,
        client=RecordingClient(ScriptedClient(talker), run.llm_calls_path),
    )
    await Simulation.create(run, parts).run(until_day=1)
    log = events(run)
    turns = sorted({e.time for e in log if e.kind is EventKind.DECISION and e.place == "cafe"})
    assert [clock_of(time) for time in turns] == ["18:00", "18:05", "18:10"]
    end = time_at(1, "22:00")
    home = {e.actor: e.text for e in log if e.kind is EventKind.MOVE and e.time == end}
    assert home == {
        "Ana": "Ana went from the cafe to the flat.",
        "Ben": "Ben went from the cafe to the house.",
        "Cai": "The park closed for the night, and Cai went home.",
    }
    known = next(call for call in read_jsonl(run.llm_calls_path))["request"]["messages"][0]
    assert (
        "- The park, where you can sit and talk with whoever else is there, open until 22:00."
        in (known["content"])
    )
    assert (
        "- The cafe, where you can sit and talk with whoever else is there, open from 07:00 to "
        in (known["content"])
    )
    assert "goes home" not in known["content"] and "22:00 everyone" not in known["content"]


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
    assert "Whatever you do now will take you to 10:00, when this part of the day ends." in (
        replies.requests[-1].messages[-1].content
    )


async def test_one_who_asked_and_the_one_it_asked_reaching_at_once_take_the_job_together(
    tmp_path,
):
    """Ana asks Ben to take a job for two; at the next moment she reaches for its notice again
    while he takes her asking up. Whatever order is drawn, she is not drawn against him and
    nothing is refused: the two take it together. Had he asked Cai instead, she and he would
    have reached for the notice apart, drawn and told as ever."""
    environment = EnvironmentConfig.model_validate(
        {
            **ENVIRONMENT.model_dump(),
            "conditions": {
                **ENVIRONMENT.conditions.model_dump(),
                "one_part_tasks": 0,
                "two_part_tasks": 1,
            },
        }
    )
    start = time_at(1, "09:00")
    reach = {"do": card.TAKE_FOR_TWO, "job": 1, "with": "Ben", "part": 1}
    for seed, partner in [*((seed, "Ana") for seed in range(6)), (0, "Cai")]:
        root = tmp_path / f"{seed}-{partner}"
        root.mkdir()
        env = Environment.create(environment, AGENTS, CodingTaskProvider(BANK), root / "log")
        env.post(start, 0)
        for agent in AGENTS:
            env.move(agent, "office", time=start)
        take_up = {"do": card.TAKE_FOR_TWO, "job": 1, "with": partner, "part": 2}
        replies = Replies(
            {"Ana": [reach, reach], "Ben": [QUIETLY, take_up], "Cai": [QUIETLY, QUIETLY]}
        )
        work = WorkSession(
            env,
            "work",
            "office",
            list(AGENTS),
            start=start,
            until=start + 60,
            rounds=2,
            closes=False,
        )
        await play(env, scripted(root, replies), [work], random.Random(seed), lambda agent: "")
        log = read_events(root / "log")
        told = [e.kind for e in log if e.kind in (EventKind.DRAW, EventKind.ACTION_REJECTED)]
        taken = [e.payload for e in log if e.kind is EventKind.TASK_CLAIMED]
        if partner == "Ana":
            assert told == [] and taken == [
                {"task_id": "task-1", "workers": ["Ana", "Ben"], "parts": {"Ana": 1, "Ben": 2}}
                | {"due_day": taken[0]["due_day"]}
            ]
        else:
            assert told == [EventKind.DRAW, EventKind.ACTION_REJECTED] and taken == []


async def test_a_meeting_is_noticed_held_answered_counted_and_enacted_the_next_morning(tmp_path):
    """On day 1 everyone goes to the meeting at the cafe, has a word, and Ana and Ben answer
    yes while Cai gives no answer: two of three carry it, so the clerk pairs by lot from the
    next morning. Nobody goes to the meeting at the park on day 2, which changes nothing."""
    question = "Should the clerk pair people for jobs for two by drawing lots?"
    meetings = [
        {
            "day": day,
            "at": "evening",
            "kind": "meeting",
            "place": place,
            "question": question,
            "options": ["yes", "no"],
            "enacts": {"yes": {"partner_choice": False}},
        }
        for day, place in ((1, "cafe"), (2, "park"))
    ]
    simulation = SimulationConfig.model_validate(
        {**SIMULATION.model_dump(), "days": 2, "interventions": meetings}
    )
    said, night = set(), Script()

    def townsfolk(request: LLMRequest) -> str | dict[str, Any]:
        agent, time = request.metadata["agent"], request.metadata["time"]
        if request.metadata["purpose"] != "act":
            return night(request)
        can = offered(request)
        if card.DECIDE in can:
            parts = [part for part in choices(request, card.DECIDE) if part != card.PLAN]
            evening = "the cafe" if day_of(time) == 1 else "home"
            plan = {part: evening if part == "evening" else "home" for part in parts}
            return {"thought": "", "do": card.DECIDE, **plan, card.PLAN: ""}
        if card.GIVE_ANSWER in can and agent != "Cai":
            return {"thought": "", "do": card.GIVE_ANSWER, card.REPLY_GIVEN: "yes"}
        if card.SAY in can and agent not in said:
            said.add(agent)
            return {"thought": "", "do": card.SAY, card.TO: None, card.WORDS: "Lots, I say."}
        return {"thought": "", "do": card.CARRY_ON}

    run = RunDirectory.create(tmp_path, "town", 7, config=simulation, code_revision="test")
    parts = replace(
        setup(run, Script()),
        simulation=simulation,
        client=RecordingClient(ScriptedClient(townsfolk), run.llm_calls_path),
    )
    assert await Simulation.create(run, parts).run() is RunStatus.COMPLETED
    log, held = events(run), "day-0001/evening/cafe"
    said_at = {e.payload.get("meeting"): e for e in log if e.kind is EventKind.ANNOUNCEMENT}

    notices = [e for e in log if e.kind is EventKind.ANNOUNCEMENT and "question" in e.payload]
    assert [(e.time, e.audience, e.payload["place"]) for e in notices] == [
        (time_at(1, "07:00"), AGENTS, "cafe"),
        (time_at(2, "07:00"), AGENTS, "park"),
    ]
    planned = min(e.seq for e in log if e.kind is EventKind.DECISION)
    assert notices[0].seq < planned
    notice = (
        "The clerk has put up a notice: a meeting at the cafe at 18:00 today, on the question "
        f'"{question}" Whoever comes'
    )
    plans = [r for r in script_requests(run) if r["metadata"]["time"] == time_at(1, "07:00")]
    assert len(plans) == 3 and all(notice in r["messages"][-1]["content"] for r in plans)

    [opening] = [e for e in log if e.kind is EventKind.ANNOUNCEMENT and e.scene == held]
    assert (opening.time, sorted(opening.audience)) == (time_at(1, "18:00"), list(AGENTS))
    assert opening.text.startswith(
        f'The clerk opens the meeting and reads out the question: "{question}" The answers'
    )
    [started] = [e for e in log if e.kind is EventKind.SCENE_STARTED and e.scene == held]
    assert started.payload["kind"] == "meeting"
    votes = [e for e in log if e.kind is EventKind.VOTE]
    assert {(e.actor, e.payload["choice"], e.audience, e.scene) for e in votes} == {
        ("Ana", "yes", (), held),
        ("Ben", "yes", (), held),
    }
    asked = [r for r in script_requests(run) if '"give the clerk your answer"' in str(r)]
    assert len(asked) == 3 and all(
        "and the talk is over. The clerk asks each person here, privately, for an answer to "
        f'the question "{question}" The answers are yes or no.' in r["messages"][-1]["content"]
        for r in asked
    )
    count = said_at[held]
    assert count.time == time_at(1, "22:00") and count.audience == AGENTS
    assert sorted(count.payload["asked"]) == list(AGENTS)
    assert (count.payload["counts"], count.payload["carried"]) == ({"yes": 2, "no": 0}, "yes")
    assert count.text.endswith(
        "2 answered yes, 0 answered no and 1 gave no answer. The answer yes carries, from "
        "tomorrow morning."
    )

    [enacted] = [e for e in log if e.kind is EventKind.INTERVENTION]
    assert (enacted.time, enacted.payload["meeting"]) == (time_at(2, "07:00"), held)
    assert enacted.payload["changes"] == {"partner_choice": False}
    day_two = next(e for e in log if e.kind is EventKind.DAY_STARTED and day_of(e.time) == 2)
    assert enacted.seq < day_two.seq
    nobody = said_at["day-0002/evening/park"]
    assert nobody.payload == {
        "meeting": "day-0002/evening/park",
        "asked": [],
        "counts": {"yes": 0, "no": 0},
        "carried": None,
    }
    assert nobody.text.endswith("Nobody came, so things stay as they are.")

    found = meetings_of(read_run(run.root))
    assert [(m.meeting, m.carried, m.votes, m.enacted) for m in found] == [
        (held, "yes", {"Ana": "yes", "Ben": "yes"}, {"partner_choice": False}),
        ("day-0002/evening/park", None, {}, None),
    ]


def script_requests(run: RunDirectory) -> list[dict[str, Any]]:
    """The decision requests of `run`, as recorded."""
    return [
        call["request"] | {"metadata": call["metadata"]}
        for call in read_jsonl(run.llm_calls_path)
        if call["metadata"]["purpose"] == "act"
    ]


@pytest.mark.parametrize(
    ("voters", "votes", "carried"),
    [
        (["Ana", "Ben"], {"Ana": "yes", "Ben": "no"}, None),
        (["Ana", "Ben", "Cai"], {"Ana": "no"}, None),
        (["Ana", "Ben", "Cai"], {"Ana": "no", "Ben": "no"}, "no"),
        (["Ana"], {"Ana": "yes"}, "yes"),
    ],
)
def test_an_answer_carries_only_if_more_than_half_of_those_asked_give_it(
    tmp_path, voters, votes, carried
):
    env = Environment.create(ENVIRONMENT, AGENTS, CodingTaskProvider(BANK), tmp_path / "log")
    meeting = Meeting(
        env,
        "meeting",
        "cafe",
        voters,
        start=0,
        step=5,
        max_turns=6,
        until=60,
        rng=random.Random(0),
        question="Should it?",
        options=("yes", "no"),
    )
    meeting.voters, meeting.votes = voters, votes
    assert meeting.carried() == carried
