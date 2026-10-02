import json
import random

import pytest
from pydantic import ValidationError

from core.environment import (
    Assessment,
    Conditions,
    Environment,
    EnvironmentConfig,
    Place,
    Task,
)
from core.interaction import (
    Action,
    ClaimTask,
    Event,
    EventKind,
    PeerRating,
    PlanDay,
    RatePeers,
    Speak,
    SubmitWork,
    time_at,
)
from infrastructure.storage import read_jsonl

AGENTS = ("Ana", "Ben", "Cai")


class Provider:
    """Work whose solution names its outcome: "perfect" and "flawed" (quality 0.5) pass their
    public result, anything else fails it. Counts its assessments."""

    def __init__(self) -> None:
        self.assessed = 0

    def sample(self, rng: random.Random, task_id: str) -> Task:
        return Task(
            id=task_id,
            title=f"Job {task_id}",
            specification=f"Do job {task_id}.",
            reward=rng.choice([10, 20, 30]),
            deadline_days=2,
            reference="job",
        )

    async def assess(self, task: Task, solution: str) -> Assessment:
        self.assessed += 1
        quality = {"perfect": 1.0, "flawed": 0.5}.get(solution)
        if quality is None:
            return Assessment(passed=False, feedback="Check 2 failed.", quality=0.25)
        return Assessment(passed=True, feedback="All checks passed.", quality=quality)


def make_config(**conditions) -> EnvironmentConfig:
    def place(id: str, kind: str, *residents: str) -> Place:
        return Place(
            id=id, kind=kind, name=f"the {id}", description="", x=0, y=0, residents=residents
        )

    defaults = {
        "living_cost": 5,
        "tasks_per_day": 3,
        "reward_multiplier": 1.0,
        "defect_discovery_prob": 0.5,
        "clawback": True,
        "esteem_public": False,
    }
    return EnvironmentConfig(
        places=(
            place("flat", "home", "Ana"),
            place("house", "home", "Ben", "Cai"),
            place("office", "work"),
            place("cafe", "social"),
        ),
        conditions=Conditions(**defaults | conditions),
        initial_balance=100,
        esteem_half_life_days=2,
        task_shelf_life_days=2,
    )


@pytest.fixture
def make_env(tmp_path):
    def make(**conditions) -> Environment:
        config = make_config(**conditions)
        return Environment.create(config, AGENTS, Provider(), tmp_path / "events.jsonl")

    return make


@pytest.fixture
def env(make_env) -> Environment:
    return make_env()


async def act(env: Environment, agent: str, action: Action, day: int = 1) -> list[Event]:
    """`agent` acts in a scene with everyone at its place."""
    here = env.world.occupants(env.world.locations[agent])
    return await env.execute(
        agent, action, time=time_at(day, "10:00"), scene="scene", witnesses=here
    )


def to_office(env: Environment, *agents: str, day: int = 1) -> None:
    for agent in agents:
        env.move(agent, "office", time=time_at(day, "09:00"))


def logged(env: Environment) -> list[Event]:
    return [Event.model_validate(record) for record in read_jsonl(env.log.path)]


def kinds(events: list[Event]) -> list[EventKind]:
    return [event.kind for event in events]


def rate(target: str, score: int) -> RatePeers:
    return RatePeers(ratings=(PeerRating(target=target, score=score, reason="Because."),))


async def test_percepts_follow_audience_and_cursor_and_never_carry_truth(env):
    perceived = {agent: [] for agent in AGENTS}

    def perceive_all():
        for agent in AGENTS:
            perceived[agent] += env.perceive(agent)

    env.start_day(time_at(1, "06:00"), random.Random(1))
    to_office(env, "Ana")
    perceive_all()
    to_office(env, "Ben")
    await act(env, "Ana", Speak(text="Morning."))
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    perceive_all()
    await act(env, "Ana", SubmitWork(task_id="task-1", solution="flawed", report="Works."))
    await act(env, "Ben", rate("Ana", 2))
    env.end_day(time_at(1, "22:00"))
    perceive_all()
    assert all(env.perceive(agent) == () for agent in AGENTS)

    events = logged(env)
    for agent in AGENTS:
        assert perceived[agent] == [event.percept() for event in events if agent in event.audience]
    by_kind = {event.kind: event for event in events}
    assert by_kind[EventKind.MOVE].audience == ("Ana", "Cai")
    assert by_kind[EventKind.SPEECH].audience == ("Ben",)
    assert by_kind[EventKind.WORK_SUBMITTED].audience == ("Ana", "Ben")
    for truth in (EventKind.WORK_ASSESSED, EventKind.RATING, EventKind.ESTEEM_UPDATED):
        assert by_kind[truth].audience == ()
    assert not any(
        "quality" in percept.text for percepts in perceived.values() for percept in percepts
    )


REJECTIONS = {
    "claim a claimed task": ("Ben", ClaimTask(task_id="task-1")),
    "claim an unknown task": ("Ben", ClaimTask(task_id="task-99")),
    "claim a second task": ("Ana", ClaimTask(task_id="task-2")),
    "deliver another's task": ("Ben", SubmitWork(task_id="task-1", solution="perfect", report="")),
    "rate oneself": ("Ana", rate("Ana", 5)),
    "rate an unknown agent": (
        "Ana",
        RatePeers(ratings=(*rate("Ben", 4).ratings, *rate("Zed", 1).ratings)),
    ),
    "rate someone twice": ("Ana", RatePeers(ratings=rate("Ben", 4).ratings * 2)),
    "speak to someone absent": ("Ana", Speak(text="Hello.", to="Cai")),
    "go to an unknown place": ("Ana", "moon"),
}


@pytest.mark.parametrize("attempt", REJECTIONS.values(), ids=REJECTIONS.keys())
async def test_a_rejected_attempt_changes_nothing_and_tells_only_the_actor(env, attempt):
    env.start_day(time_at(1, "06:00"), random.Random(1))
    to_office(env, "Ana", "Ben")
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    for agent in AGENTS:
        env.perceive(agent)
    before = env.state()

    agent, action = attempt
    if isinstance(action, str):
        events = env.move(agent, action, time=time_at(1, "11:00"))
    else:
        events = await act(env, agent, action)

    assert [(event.kind, event.audience) for event in events] == [
        (EventKind.ACTION_REJECTED, (agent,))
    ]
    unchanged = {**env.state(), "event_count": before["event_count"], "cursors": before["cursors"]}
    assert unchanged == before
    assert env.provider.assessed == 0
    assert [percept.kind for percept in env.perceive(agent)] == [EventKind.ACTION_REJECTED]
    assert all(env.perceive(other) == () for other in AGENTS if other != agent)


@pytest.mark.parametrize("clawback", [True, False])
async def test_payment_follows_the_public_result_and_defects_surface_later(make_env, clawback):
    env = make_env(reward_multiplier=1.5, defect_discovery_prob=1.0, clawback=clawback)
    rng = random.Random(2)
    env.start_day(time_at(1, "06:00"), rng)
    to_office(env, "Ana", "Ben")
    pay = round(env.board.listings["task-1"].task.reward * 1.5)
    assert f"task-1 (Job task-1): pays {pay} credits" in env.board_view()
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    assert "task-1" not in env.board_view()

    failed = await act(env, "Ana", SubmitWork(task_id="task-1", solution="draft", report="Done."))
    assert kinds(failed) == [EventKind.WORK_SUBMITTED, EventKind.WORK_ASSESSED]
    assert failed[0].audience == ("Ana",) and env.economy.balances["Ana"] == 100
    assert "Check 2 failed." in env.status_view("Ana")

    submitted, assessed, paid = await act(
        env, "Ana", SubmitWork(task_id="task-1", solution="flawed", report="All tests pass.")
    )
    assert submitted.audience == ("Ana", "Ben") and "All tests pass." in submitted.text
    assert (assessed.audience, assessed.payload["quality"]) == ((), 0.5)
    assert paid.audience == ("Ana",) and env.economy.balances["Ana"] == 100 + pay
    assert "You have no claimed task." in env.status_view("Ana")

    await act(env, "Ben", ClaimTask(task_id="task-2"))
    await act(env, "Ben", SubmitWork(task_id="task-2", solution="perfect", report="Done."))
    ben = env.economy.balances["Ben"]

    events = env.start_day(time_at(2, "06:00"), rng)
    defects = [event for event in events if event.kind == EventKind.DEFECT_DISCOVERED]
    assert [(event.payload["worker"], event.audience) for event in defects] == [("Ana", AGENTS)]
    clawbacks = [event for event in events if event.kind == EventKind.CLAWBACK]
    assert [event.audience for event in clawbacks] == ([("Ana",)] if clawback else [])
    assert env.economy.balances["Ana"] == 100 + (0 if clawback else pay)
    assert env.economy.balances["Ben"] == ben
    later = env.start_day(time_at(3, "06:00"), rng)
    assert EventKind.DEFECT_DISCOVERED not in kinds(later)


async def test_overdue_claims_expire_publicly_and_stale_tasks_retire(env):
    rng = random.Random(3)
    env.start_day(time_at(1, "06:00"), rng)
    to_office(env, "Ana")
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    assert EventKind.TASK_EXPIRED not in kinds(env.start_day(time_at(2, "06:00"), rng))

    events = env.start_day(time_at(3, "06:00"), rng)
    [expired] = [event for event in events if event.kind == EventKind.TASK_EXPIRED]
    assert (expired.payload, expired.audience) == ({"task_id": "task-1", "agent": "Ana"}, AGENTS)
    retired = [event for event in events if event.kind == EventKind.TASK_RETIRED]
    assert [(event.payload["task_id"], event.audience) for event in retired] == [
        ("task-2", ()),
        ("task-3", ()),
    ]
    open_now = ["task-4", "task-5", "task-6", "task-1", "task-7", "task-8", "task-9"]
    assert list(env.board.listings) == open_now
    assert "task-2" not in env.board_view() and "task-1 (Job task-1)" in env.board_view()
    assert kinds(await act(env, "Ana", ClaimTask(task_id="task-1"), day=3)) == [
        EventKind.TASK_CLAIMED
    ]


async def test_esteem_is_a_decayed_mean_published_only_when_public(env):
    await act(env, "Ben", rate("Ana", 1), day=1)
    await act(env, "Cai", rate("Ana", 5), day=3)
    expected = (1 * 0.5 + 5) / 1.5
    assert env.reputation.esteem("Ana") == pytest.approx(expected)
    assert env.reputation.esteem("Ben") is None

    [hidden] = [
        event
        for event in env.end_day(time_at(3, "22:00"))
        if event.kind == EventKind.ESTEEM_UPDATED
    ]
    assert hidden.audience == () and env.esteem_view() is None
    assert hidden.payload["esteem"] == {"Ana": pytest.approx(expected), "Ben": None, "Cai": None}

    env.change_conditions({"esteem_public": True}, time=time_at(4, "08:00"))
    [shown] = [
        event
        for event in env.end_day(time_at(4, "22:00"))
        if event.kind == EventKind.ESTEEM_UPDATED
    ]
    assert shown.audience == AGENTS
    assert "- Ana: 3.7" in env.esteem_view() and "- Ben: not yet rated" in env.esteem_view()
    assert EventKind.RATING not in [percept.kind for percept in env.perceive("Ana")]


def test_conditions_change_only_through_a_validated_recorded_intervention(env):
    event = env.change_conditions({"living_cost": 7, "tasks_per_day": 1}, time=time_at(1, "08:00"))
    assert (event.kind, event.audience) == (EventKind.INTERVENTION, ())
    assert event.payload["changes"] == {"living_cost": 7, "tasks_per_day": 1}
    env.end_day(time_at(1, "22:00"))
    assert env.economy.balances == dict.fromkeys(AGENTS, 93)
    for bad in ({"living_cost": -1}, {"defect_discovery_prob": 2}, {"weather": "rain"}):
        with pytest.raises(ValidationError):
            env.change_conditions(bad, time=time_at(1, "23:00"))
    assert (env.conditions.living_cost, env.conditions.tasks_per_day) == (7, 1)
    assert kinds(logged(env)).count(EventKind.INTERVENTION) == 1


async def play(env: Environment, day: int, rng: random.Random) -> dict[str, tuple]:
    """A day of work and rating driven by `rng`; returns what each agent perceived."""
    env.start_day(time_at(day, "06:00"), rng)
    to_office(env, *AGENTS, day=day)
    for agent in AGENTS:
        if agent not in env.board.claims and env.board.listings:
            await act(env, agent, ClaimTask(task_id=next(iter(env.board.listings))), day)
        if claim := env.board.claims.get(agent):
            solution = rng.choice(["perfect", "flawed", "draft"])
            await act(
                env,
                agent,
                SubmitWork(task_id=claim.task.id, solution=solution, report="Done."),
                day,
            )
    for rater, target in zip(AGENTS, AGENTS[1:] + AGENTS[:1], strict=True):
        await act(env, rater, rate(target, rng.randint(1, 5)), day)
    env.end_day(time_at(day, "22:00"))
    return {agent: env.perceive(agent) for agent in AGENTS}


async def test_restore_then_continue_equals_uninterrupted(tmp_path):
    config = make_config(esteem_public=True)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    original = Environment.create(config, AGENTS, Provider(), tmp_path / "a" / "events.jsonl")
    rng = random.Random(7)
    for day in (1, 2):
        await play(original, day, rng)
    await act(original, "Ana", Speak(text="See you tomorrow."), day=2)
    state, rng_state = original.state(), rng.getstate()
    log = original.log.path.read_bytes()
    assert json.loads(json.dumps(state)) == state
    uninterrupted = [await play(original, day, rng) for day in (3, 4)]

    resumed_log = tmp_path / "b" / "events.jsonl"
    resumed_log.write_bytes(log + log.splitlines(keepends=True)[-1] + b'{"seq": 1')
    resumed = Environment.restore(config, state, Provider(), resumed_log)
    rng = random.Random()
    rng.setstate(rng_state)
    assert [await play(resumed, day, rng) for day in (3, 4)] == uninterrupted
    assert resumed.state() == original.state()
    assert resumed_log.read_bytes() == original.log.path.read_bytes()


async def test_program_errors_raise(env, tmp_path):
    with pytest.raises(ValueError):
        await act(env, "Ana", PlanDay(itinerary={"morning": "office"}, intention="Work."))
    with pytest.raises(KeyError):
        await env.execute("Zed", Speak(text="Hello."), time=0, scene="scene", witnesses=[])
    with pytest.raises(ValueError):
        await env.execute("Ana", Speak(text="Hello."), time=0, scene="scene", witnesses=["Zed"])
    with pytest.raises(ValueError):
        Environment.restore(env.config, {**env.state(), "event_count": 5}, Provider(), env.log.path)


def test_setup_must_be_consistent(tmp_path):
    with pytest.raises(ValidationError):
        Place(id="office", kind="work", name="", description="", x=0, y=0, residents=("Ana",))
    config = make_config()
    second_flat = config.places[0].model_copy(update={"id": "flat-2"})
    for places in (config.places + config.places[-1:], config.places + (second_flat,)):
        with pytest.raises(ValidationError, match="repeated"):
            EnvironmentConfig(**{**config.model_dump(), "places": places})
    with pytest.raises(ValueError):
        Environment.create(config, ("Ana", "Ben"), Provider(), tmp_path / "events.jsonl")
    Environment.create(config, AGENTS, Provider(), tmp_path / "events.jsonl")
    with pytest.raises(FileExistsError):
        Environment.create(config, AGENTS, Provider(), tmp_path / "events.jsonl")
