import json
import random

import pytest
from pydantic import ValidationError

from core.environment import (
    Assessment,
    Circumstances,
    Conditions,
    Environment,
    EnvironmentConfig,
    Part,
    Place,
)
from core.interaction import (
    Action,
    CheckWork,
    ClaimTask,
    Event,
    EventKind,
    Give,
    PeerRating,
    PlanDay,
    RatePeers,
    Speak,
    SubmitWork,
    time_at,
)
from infrastructure.storage import read_jsonl
from tests.core.agent.test_prompts import MACHINERY, STEERING

AGENTS = ("Ana", "Ben", "Cai", "Dan")
SECRET = "Check 2 failed."
"""The feedback on a failing solution: what only the worker who ran it may see."""


class Provider:
    """Work whose solution names its outcome: "perfect" passes the acceptance checks with true
    quality 1, "flawed" passes them with quality 0.5, anything else fails them with quality
    0.25. Every part allows two days. Counts its assessments."""

    def __init__(self) -> None:
        self.assessed = 0

    def sample(self, rng: random.Random, count: int) -> tuple[Part, ...]:
        return tuple(
            Part(
                title=f"Routine {number}",
                specification=f"Write routine {number}.",
                reward=rng.choice([10, 20, 30]),
                deadline_days=2,
                reference=f"job-{number}",
            )
            for number in rng.sample(range(1, 1000), count)
        )

    async def assess(self, part: Part, solution: str) -> Assessment:
        self.assessed += 1
        quality = {"perfect": 1.0, "flawed": 0.5}.get(solution)
        if quality is None:
            return Assessment(passed=False, feedback=SECRET, quality=0.25)
        return Assessment(passed=True, feedback="All checks passed.", quality=quality)


DEFAULTS = {
    "living_cost": 5,
    "one_part_tasks": 2,
    "two_part_tasks": 1,
    "trusting_client_prob": 0.0,
    "reward_multiplier": 1.0,
    "two_part_premium": 1.5,
    "incomplete_share": 0.5,
    "partner_choice": True,
    "defect_discovery_prob": 0.5,
    "clawback": True,
    "esteem_public": False,
}


def make_config(circumstances=None, **conditions) -> EnvironmentConfig:
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

    return EnvironmentConfig(
        places=(
            place("flat", "home", "Ana"),
            place("house", "home", "Ben", "Cai"),
            place("cottage", "home", "Dan"),
            place("office", "work", hours=("08:00-10:30", "12:00-18:00")),
            place("cafe", "social"),
        ),
        conditions=Conditions(**DEFAULTS | conditions),
        initial_balance=100,
        circumstances=circumstances or {},
        esteem_half_life_days=2,
        task_shelf_life_days=2,
    )


@pytest.fixture
def make_env(tmp_path):
    made = iter(range(100))

    def make(circumstances=None, **conditions) -> Environment:
        config = make_config(circumstances, **conditions)
        path = tmp_path / f"events-{next(made)}.jsonl"
        return Environment.create(config, AGENTS, Provider(), path)

    return make


@pytest.fixture
def env(make_env) -> Environment:
    return make_env()


def open_day(env: Environment, rng: random.Random, day: int = 1, seed: int = 0) -> list[Event]:
    """Start `day` and post its tasks; with the defaults, task-1 and task-2 have one part and
    task-3 two."""
    time = time_at(day, "07:00")
    return env.start_day(time, rng) + env.post(time, seed)


async def act(
    env: Environment, agent: str, action: Action, day: int = 1, clock: str = "10:00"
) -> list[Event]:
    """`agent` acts in a scene with everyone at its place."""
    here = env.world.occupants(env.world.locations[agent])
    return await env.execute(agent, action, time=time_at(day, clock), scene="scene", witnesses=here)


def go(env: Environment, place: str, *agents: str, day: int = 1) -> None:
    for agent in agents:
        env.move(agent, place, time=time_at(day, "09:00"))


def deliver(
    task: str, solution: str, declaration: str = "complete", part: int = 1, report: str = "Done."
) -> SubmitWork:
    return SubmitWork(
        task_id=task, part=part, solution=solution, declaration=declaration, report=report
    )


def logged(env: Environment) -> list[Event]:
    return [Event.model_validate(record) for record in read_jsonl(env.log.path)]


def kinds(events: list[Event]) -> list[EventKind]:
    return [event.kind for event in events]


def only(events: list[Event], kind: EventKind) -> Event:
    [event] = [event for event in events if event.kind is kind]
    return event


def rate(target: str, score: int) -> RatePeers:
    return RatePeers(ratings=(PeerRating(target=target, score=score, reason="Because."),))


def views(env: Environment) -> list[str]:
    return [
        env.rules_view(),
        env.board_view(),
        env.esteem_view() or "",
        *(env.status_view(agent) for agent in AGENTS),
    ]


def pay(env: Environment, task: str, part: int = 1, incomplete: bool = False) -> int:
    """What each worker of the open or held `task` is paid for `part`, by the conditions."""
    held = {claim.task.id: claim.task for claim in env.board.claims.values()}
    found = env.board.listings[task].task if task in env.board.listings else held[task]
    value = found.parts[part - 1].reward * env.conditions.reward_multiplier / len(found.parts)
    if len(found.parts) == 2:
        value *= env.conditions.two_part_premium
    return round(value * (env.conditions.incomplete_share if incomplete else 1))


async def pair_up(env: Environment, proposer: str, partner: str, task: str = "task-3") -> None:
    """`proposer` proposes the two-person `task` to `partner`, who takes it up."""
    await act(env, proposer, ClaimTask(task_id=task, partner=partner))
    await act(env, partner, ClaimTask(task_id=task))


async def test_percepts_follow_audience_and_cursor_and_never_carry_truth(env):
    perceived = {agent: [] for agent in AGENTS}

    def perceive_all():
        for agent in AGENTS:
            perceived[agent] += env.perceive(agent)

    open_day(env, random.Random(1))
    go(env, "office", "Ana")
    perceive_all()
    go(env, "office", "Ben")
    await act(env, "Ana", Speak(text="Morning."))
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    await act(env, "Cai", ClaimTask(task_id="task-3", partner="Dan"))
    perceive_all()
    await act(env, "Ana", CheckWork(task_id="task-1", part=1, solution="draft"))
    await act(env, "Ana", deliver("task-1", "flawed", report="Works."))
    await act(env, "Ben", Give(to="Ana", amount=5, note="For lunch."))
    await act(env, "Ben", rate("Ana", 2))
    env.end_day(time_at(1, "22:00"))
    perceive_all()
    assert all(env.perceive(agent) == () for agent in AGENTS)

    events = logged(env)
    for agent in AGENTS:
        assert perceived[agent] == [event.percept() for event in events if agent in event.audience]
    assert only(events, EventKind.SPEECH).audience == ("Ben",)
    assert only(events, EventKind.TASK_CLAIMED).audience == ("Ana", "Ben")
    assert only(events, EventKind.TASK_PROPOSED).audience == ("Cai", "Dan")
    assert only(events, EventKind.WORK_CHECKED).audience == ("Ana",)
    assert only(events, EventKind.WORK_SUBMITTED).audience == ("Ana", "Ben")
    assert only(events, EventKind.CREDITS_GIVEN).audience == ("Ana", "Ben")
    for truth in (EventKind.WORK_ASSESSED, EventKind.RATING, EventKind.ESTEEM_UPDATED):
        assert only(events, truth).audience == ()
    texts = [percept.text for percepts in perceived.values() for percept in percepts]
    assert not any("quality" in text for text in texts)
    assert not any(SECRET in percept.text for p in AGENTS[1:] for percept in perceived[p])


REJECTIONS = {
    "take a taken job": (
        "Ben",
        ClaimTask(task_id="1"),
        "The board refuses: job 1 already went to Ana.",
    ),
    "take a job not on the board": (
        "Ben",
        ClaimTask(task_id="job 99"),
        "There is no job 99 on the board.",
    ),
    "take a job by no number": (
        "Ben",
        ClaimTask(task_id="the parser one"),
        "There is no job 'the parser one' on the board.",
    ),
    "take a second job": ("Ana", ClaimTask(task_id="task-2"), "You are already working on job 1."),
    "propose while holding a task": (
        "Ana",
        ClaimTask(task_id="task-3", partner="Dan"),
        "You are already working on job 1.",
    ),
    "name a partner for a one-part task": (
        "Ben",
        ClaimTask(task_id="task-2", partner="Cai"),
        "Job 2 is work for one; take it without naming anyone.",
    ),
    "name oneself as partner": (
        "Ben",
        ClaimTask(task_id="task-3", partner="Ben"),
        "You cannot take a job with yourself.",
    ),
    "name an unknown partner": (
        "Ben",
        ClaimTask(task_id="task-3", partner="Zed"),
        "There is nobody called 'Zed' in town.",
    ),
    "take a two-person task without a proposal": (
        "Ben",
        ClaimTask(task_id="task-3"),
        "Job 3 is a job for two: ask someone by name",
    ),
    "take up one of several proposals without naming one": (
        "Cai",
        ClaimTask(task_id="task-3"),
        "Ben and Dan have each asked you to take job 3 with them; name the one",
    ),
    "repeat a proposal": (
        "Ben",
        ClaimTask(task_id="task-3", partner="Cai"),
        "You have already asked Cai to take job 3 with you.",
    ),
    "check another's task": (
        "Ben",
        CheckWork(task_id="task-1", part=1, solution="perfect"),
        "You are not working on job 1.",
    ),
    "check a part the task lacks": (
        "Ana",
        CheckWork(task_id="task-1", part=2, solution="perfect"),
        "Job 1 has only one part.",
    ),
    "hand in another's job": ("Ben", deliver("task-1", "perfect"), "You are not working on job 1."),
    "hand in a job by no number": (
        "Ana",
        deliver("mine", "perfect"),
        "There is no job 'mine' on the board.",
    ),
    "deliver a part the task lacks": (
        "Ana",
        deliver("task-1", "perfect", part=2),
        "Job 1 has only one part.",
    ),
    "give to oneself": ("Ana", Give(to="Ana", amount=1, note=""), "You cannot hand money to"),
    "give to someone absent": ("Ben", Give(to="Cai", amount=1, note=""), "Cai is not here."),
    "give more than one has": ("Ana", Give(to="Ben", amount=101, note=""), "You have only 100"),
    "remark in private to nobody": (
        "Ana",
        Speak(text="Psst.", private=True),
        "To say something privately, say it to someone here by name.",
    ),
    "speak to someone absent": ("Ana", Speak(text="Hello.", to="Cai"), "Cai is not here."),
    "rate oneself": ("Ana", rate("Ana", 5), "You cannot mark yourself in the board's ledger."),
    "rate an unknown agent": (
        "Ana",
        RatePeers(ratings=(*rate("Ben", 4).ratings, *rate("Zed", 1).ratings)),
        "There is nobody called 'Zed' in town.",
    ),
    "rate someone twice": (
        "Ana",
        RatePeers(ratings=rate("Ben", 4).ratings * 2),
        "You can mark Ben only once at a time.",
    ),
    "go to an unknown place": ("Ana", "moon", "There is no place called 'moon' in town."),
    "go to a closed place": ("Cai", "office", "The office is closed at 11:00."),
    "stay at a closed place": ("Ana", "office", "The office is closed at 11:00."),
}


@pytest.mark.parametrize("attempt", REJECTIONS.values(), ids=REJECTIONS.keys())
async def test_a_rejected_attempt_changes_nothing_and_tells_only_the_actor(env, attempt):
    open_day(env, random.Random(1))
    go(env, "office", "Ana", "Ben")
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    await act(env, "Ben", ClaimTask(task_id="task-3", partner="Cai"))
    await act(env, "Dan", ClaimTask(task_id="task-3", partner="Cai"))
    for agent in AGENTS:
        env.perceive(agent)
    before = env.state()

    agent, action, reason = attempt
    if isinstance(action, str):
        events = env.move(agent, action, time=time_at(1, "11:00"))
    else:
        events = await act(env, agent, action)

    assert [(event.kind, event.audience) for event in events] == [
        (EventKind.ACTION_REJECTED, (agent,))
    ]
    assert reason in events[0].text and events[0].text == events[0].payload["reason"]
    assert not MACHINERY.search(events[0].text), events[0].text
    unchanged = {**env.state(), "event_count": before["event_count"], "cursors": before["cursors"]}
    assert unchanged == before
    assert env.provider.assessed == 0
    assert [percept.kind for percept in env.perceive(agent)] == [EventKind.ACTION_REJECTED]
    assert all(env.perceive(other) == () for other in AGENTS if other != agent)


@pytest.mark.parametrize(
    ("client", "declaration", "solution", "price", "latent"),
    [
        ("checking", "complete", "flawed", "full", True),
        ("checking", "complete", "draft", None, False),
        ("checking", "incomplete", "draft", "low", False),
        ("trusting", "complete", "draft", "full", True),
        ("trusting", "complete", "perfect", "full", False),
        ("trusting", "incomplete", "flawed", "low", False),
    ],
)
async def test_each_client_pays_each_declaration_by_its_own_rule(
    make_env, client, declaration, solution, price, latent
):
    env = make_env(trusting_client_prob=float(client == "trusting"), defect_discovery_prob=1.0)
    rng = random.Random(2)
    open_day(env, rng)
    assert env.board.listings["task-1"].task.client == client
    go(env, "office", "Ana", "Ben")
    prices = {"full": pay(env, "task-1"), "low": pay(env, "task-1", incomplete=True), None: 0}
    assert f"pays {prices['full']} crowns, {prices['low']} if" in env.board_view()
    await act(env, "Ana", ClaimTask(task_id="task-1"))

    events = await act(env, "Ana", deliver("task-1", solution, declaration, report="As agreed."))
    submitted = only(events, EventKind.WORK_SUBMITTED)
    assessed = only(events, EventKind.WORK_ASSESSED)
    accepted = price is not None
    assert submitted.payload["accepted"] is accepted
    assert assessed.payload | {"feedback": None} == {
        "task_id": "task-1",
        "part": 1,
        "client": client,
        "declaration": declaration,
        "accepted": accepted,
        "passed": solution != "draft",
        "feedback": None,
        "quality": {"perfect": 1.0, "flawed": 0.5}.get(solution, 0.25),
        "tested": None,
        "refused": False,
    }
    paid = prices[price]
    assert env.economy.balances["Ana"] == 100 + paid
    assert [(defect.worker, defect.task.id) for defect in env.board.latent] == (
        [("Ana", "task-1")] if latent else []
    )
    if accepted:
        assert submitted.audience == ("Ana", "Ben")
        handed = {"complete": "as finished", "incomplete": "as unfinished"}[declaration]
        assert handed in submitted.text and "told the client: As agreed." in submitted.text
        assert SECRET not in submitted.text
        assert only(events, EventKind.PAYMENT).payload["amount"] == paid
        assert "You are not working on any job." in env.status_view("Ana")
    else:
        assert submitted.audience == ("Ana",) and SECRET in submitted.text
        assert EventKind.PAYMENT not in kinds(events)
        refused = f"The last time you handed it in, the client handed it back:\n{SECRET}"
        assert refused in env.status_view("Ana")
        assert SECRET not in env.status_view("Ben")

    discovered = env.start_day(time_at(2, "07:00"), rng)
    assert (EventKind.DEFECT_DISCOVERED in kinds(discovered)) is latent
    assert env.economy.balances["Ana"] == 100 + (0 if latent else paid)


async def test_a_refused_delivery_may_be_made_again_and_the_record_keeps_what_was_known(env):
    open_day(env, random.Random(3))
    go(env, "office", "Ana")
    low = pay(env, "task-1", incomplete=True)
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    await act(env, "Ana", CheckWork(task_id="task-1", part=1, solution="flawed"))
    refused = await act(env, "Ana", deliver("task-1", "draft"))
    assert only(refused, EventKind.WORK_ASSESSED).payload["refused"] is False
    again = await act(env, "Ana", deliver("task-1", "draft", "incomplete"))
    known = only(again, EventKind.WORK_ASSESSED).payload
    assert (known["accepted"], known["tested"], known["refused"]) == (True, None, True)
    assert "as unfinished; the client accepted it at the lower price" in (
        only(again, EventKind.WORK_SUBMITTED).text
    )
    assert env.economy.balances["Ana"] == 100 + low and not env.board.latent


async def test_private_checks_reach_only_the_worker_and_are_known_at_delivery(make_env):
    env = make_env(trusting_client_prob=1.0)
    open_day(env, random.Random(4))
    go(env, "office", "Ana", "Ben")
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    for agent in AGENTS:
        env.perceive(agent)
    balances = dict(env.economy.balances)

    checked = await act(env, "Ana", CheckWork(task_id="task-1", part=1, solution="draft"))
    assert [(event.kind, event.audience) for event in checked] == [
        (EventKind.WORK_CHECKED, ("Ana",))
    ]
    assert SECRET in checked[0].text
    assert {key: checked[0].payload[key] for key in ("solution", "passed", "quality")} == {
        "solution": "draft",
        "passed": False,
        "quality": 0.25,
    }
    assert all(env.perceive(other) == () for other in AGENTS if other != "Ana")
    assert env.economy.balances == balances and "task-1" in env.board.claims
    assert f"against the client's examples:\n{SECRET}" in env.status_view("Ana")
    assert not any(SECRET in env.status_view(other) for other in AGENTS if other != "Ana")

    await act(env, "Ana", CheckWork(task_id="task-1", part=1, solution="perfect"))
    events = await act(env, "Ana", deliver("task-1", "draft", report="All checks pass."))
    known = only(events, EventKind.WORK_ASSESSED).payload
    assert (known["accepted"], known["passed"], known["tested"]) == (True, False, False)
    submitted = only(events, EventKind.WORK_SUBMITTED)
    assert "on Ana's word" in submitted.text and "All checks pass." in submitted.text
    assert SECRET not in submitted.text

    await act(env, "Ben", ClaimTask(task_id="task-2"))
    await act(env, "Ben", CheckWork(task_id="task-2", part=1, solution="perfect"))
    events = await act(env, "Ben", deliver("task-2", "perfect"))
    assert only(events, EventKind.WORK_ASSESSED).payload["tested"] is True

    await pair_up(env, "Cai", "Dan")
    env.perceive("Dan")
    await act(env, "Cai", CheckWork(task_id="task-3", part=1, solution="draft"))
    assert env.perceive("Dan") == () and SECRET not in env.status_view("Dan")
    assert f"against the client's examples:\n{SECRET}" in env.status_view("Cai")
    events = await act(env, "Dan", deliver("task-3", "draft", part=1))
    assert only(events, EventKind.WORK_ASSESSED).payload["tested"] is None


async def test_a_job_is_named_by_its_number_however_a_resident_writes_it(env):
    open_day(env, random.Random(17))
    references = ("1", "Job 2", "job #3 (the one for two)", "task-3")
    for agent, reference in zip(AGENTS, references, strict=True):
        await act(
            env, agent, ClaimTask(task_id=reference, partner="Ana" if agent == "Dan" else None)
        )
    taken = {claim.task.id: claim.workers for claim in env.board.claims.values()}
    assert taken == {"task-1": ("Ana",), "task-2": ("Ben",)}
    assert env.board.offers["Dan"].task_id == "task-3"
    [checked] = await act(env, "Ana", CheckWork(task_id=" JOB 01 ", part=1, solution="perfect"))
    assert checked.kind is EventKind.WORK_CHECKED and checked.payload["task_id"] == "task-1"
    [none] = await act(env, "Ana", deliver("job", "perfect"))
    assert none.text == "There is no job 'job' on the board."


async def test_a_proposal_taken_up_forms_a_task_for_two_known_to_those_present(env):
    open_day(env, random.Random(5))
    go(env, "office", "Ana", "Ben", "Cai")
    for agent in AGENTS:
        env.perceive(agent)
    [proposed] = await act(env, "Ana", ClaimTask(task_id="task-3", partner="Ben"))
    assert (proposed.kind, proposed.audience) == (EventKind.TASK_PROPOSED, ("Ana", "Ben"))
    assert proposed.payload == {"task_id": "task-3", "partner": "Ben"}
    assert env.perceive("Cai") == () and "task-3" in env.board.listings
    assert "Asking you to take a job with them: Ana, for job 3" in env.status_view("Ben")
    assert "You have asked Ben to take job 3" in env.status_view("Ana")
    assert "Asking you" not in env.status_view("Cai")

    [taken] = await act(env, "Ben", ClaimTask(task_id="task-3"))
    assert (taken.kind, taken.actor) == (EventKind.TASK_CLAIMED, "Ben")
    assert taken.payload["workers"] == ["Ana", "Ben"]
    assert taken.audience == ("Ana", "Ben", "Cai")
    assert (
        "Ana and Ben took job 3, " in taken.text and '", together, due by the end of' in taken.text
    )
    assert "task-3" not in env.board.listings and not env.board.offers
    for agent, partner in (("Ana", "Ben"), ("Ben", "Ana")):
        status = env.status_view(agent)
        assert 'You are working on job 3, "Routine' in status and f", with {partner};" in status
        assert 'Part 1, "Routine' in status and 'Part 2, "Routine' in status
        assert "it pays each of you" in status


async def test_a_proposal_can_be_ignored_raced_replaced_or_withdrawn(env):
    rng = random.Random(6)
    open_day(env, rng)
    go(env, "office", *AGENTS)
    await act(env, "Ana", ClaimTask(task_id="task-3", partner="Ben"))
    env.end_day(time_at(1, "22:00"))
    assert not env.board.offers and "Asking you" not in env.status_view("Ben")
    [ignored] = await act(env, "Ben", ClaimTask(task_id="task-3"), day=2)
    assert "Job 3 is a job for two" in ignored.text

    await act(env, "Ana", ClaimTask(task_id="task-3", partner="Ben"), day=2)
    await act(env, "Cai", ClaimTask(task_id="task-3", partner="Dan"), day=2)
    [won] = await act(env, "Dan", ClaimTask(task_id="task-3"), day=2)
    assert won.payload["workers"] == ["Cai", "Dan"]
    [raced] = await act(env, "Ben", ClaimTask(task_id="task-3"), day=2)
    assert raced.text == "The board refuses: job 3 already went to Cai and Dan."
    assert not env.board.offers and "You have asked" not in env.status_view("Ana")

    env.post(time_at(2, "12:00"), 0)
    later = {"day": 2, "clock": "12:00"}
    await act(env, "Ana", ClaimTask(task_id="task-6", partner="Ben"), **later)
    await act(env, "Ana", ClaimTask(task_id="task-6", partner="Cai"), **later)
    assert "Asking you" not in env.status_view("Ben")
    assert "once your present job is done: Ana, for job 6" in env.status_view("Cai")
    [replaced] = await act(env, "Ben", ClaimTask(task_id="task-6"), **later)
    assert replaced.kind is EventKind.ACTION_REJECTED
    await act(env, "Ana", ClaimTask(task_id="task-6", partner="Ben"), **later)
    await act(env, "Ana", ClaimTask(task_id="task-4"), **later)
    assert not env.board.offers and "Asking you" not in env.status_view("Ben")
    [withdrawn] = await act(env, "Ben", ClaimTask(task_id="task-6"), **later)
    assert withdrawn.kind is EventKind.ACTION_REJECTED


async def test_one_of_several_proposals_is_taken_up_by_naming_its_proposer(env):
    open_day(env, random.Random(7))
    await act(env, "Ana", ClaimTask(task_id="task-3", partner="Cai"))
    await act(env, "Ben", ClaimTask(task_id="task-3", partner="Cai"))
    status = env.status_view("Cai")
    assert "Asking you to take a job with them: Ana, for job 3" in status
    assert "Ben, for job 3" in status
    [taken] = await act(env, "Cai", ClaimTask(task_id="task-3", partner="Ana"))
    assert taken.payload["workers"] == ["Ana", "Cai"] and not env.board.offers

    env.post(time_at(1, "12:00"), 0)
    await act(env, "Ben", ClaimTask(task_id="task-6", partner="Dan"))
    await act(env, "Dan", ClaimTask(task_id="task-4"))
    assert "Asking you to take a job with them once your present job is done: Ben, for job 6" in (
        env.status_view("Dan")
    )


APPLIED = dict(zip(AGENTS, ("task-3", "task-4", "task-3", "task-4"), strict=True))


async def applicants(env: Environment, rng: random.Random) -> None:
    """Under random assignment, everyone applies for one of two tasks for two."""
    open_day(env, rng)
    for agent, task in APPLIED.items():
        [applied] = await act(env, agent, ClaimTask(task_id=task))
        assert (applied.kind, applied.audience) == (EventKind.TASK_APPLIED, (agent,))


async def test_random_assignment_pairs_applicants_by_the_draw_alone(make_env):
    env = make_env(partner_choice=False, two_part_tasks=2)
    open_day(env, random.Random(0))
    assert "The board pairs the names put down by drawing lots" in env.rules_view()
    [refused] = await act(env, "Ana", ClaimTask(task_id="task-3", partner="Ben"))
    assert "put your name down without naming anyone" in refused.text

    pairings = set()
    for seed in range(8):
        twins = [
            (make_env(partner_choice=False, two_part_tasks=2), random.Random(seed))
            for _ in range(2)
        ]
        for twin, rng in twins:
            await applicants(twin, rng)
        assert "Your name is down for job 4" in twins[0][0].status_view("Dan")
        formed = [twin.pair_applicants(time_at(1, "10:30"), rng) for twin, rng in twins]
        assert [event.payload for event in formed[0]] == [event.payload for event in formed[1]]
        assert twins[0][0].state() == twins[1][0].state()
        for event in formed[0]:
            first, second = event.payload["workers"]
            assert event.payload["task_id"] in (APPLIED[first], APPLIED[second])
            paired = f"By drawing lots, the board paired {first} and {second} for job"
            assert event.actor is None and paired in event.text
            assert {first, second} <= set(event.audience)
        paired = [agent for event in formed[0] for agent in event.payload["workers"]]
        left = [offer.agent for offer in twins[0][0].board.offers.values()]
        taken = {event.payload["task_id"] for event in formed[0]}
        lapsed = [agent for agent in AGENTS if agent not in paired and APPLIED[agent] in taken]
        assert paired and len(left) <= 1 and sorted(paired + left + lapsed) == sorted(AGENTS)
        pairings.add(frozenset(frozenset(event.payload["workers"]) for event in formed[0]))
    assert len(pairings) > 1


async def test_pairing_needs_two_applicants_and_draws_nothing_otherwise(make_env):
    env = make_env(partner_choice=False)
    rng = random.Random(8)
    open_day(env, rng)
    draws = rng.getstate()
    assert env.pair_applicants(time_at(1, "10:30"), rng) == []
    await act(env, "Ana", ClaimTask(task_id="task-3"))
    assert env.pair_applicants(time_at(1, "10:30"), rng) == [] and rng.getstate() == draws
    [repeat] = await act(env, "Ana", ClaimTask(task_id="task-3"))
    assert repeat.text == "Your name is already down for job 3."
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    assert not env.board.offers


async def test_a_task_for_two_pays_both_equally_and_a_defect_costs_both_naming_its_cause(
    make_env,
):
    env = make_env(defect_discovery_prob=1.0)
    rng = random.Random(9)
    open_day(env, rng)
    go(env, "office", "Ana", "Ben", "Cai")
    first, second = pay(env, "task-3", 1), pay(env, "task-3", 2)
    assert f"pays each of the two {first} crowns for part 1 and {second} for part 2" in (
        env.board_view()
    )
    await pair_up(env, "Ana", "Ben")
    report = "Handles every case."
    one = await act(env, "Ana", deliver("task-3", "flawed", part=1, report=report))
    assert only(one, EventKind.WORK_SUBMITTED).audience == ("Ana", "Ben", "Cai")
    assert EventKind.PAYMENT not in kinds(one)
    status = env.status_view("Ben")
    assert 'Part 1, "Routine' in status
    assert "in; Ana handed it in as finished on Monday, your first day in town" in status
    [rejected] = await act(env, "Ben", deliver("task-3", "perfect", part=1))
    assert rejected.text == "Part 1 of job 3 is already in."

    two = await act(env, "Ana", deliver("task-3", "perfect", part=2))
    paid = [event for event in two if event.kind is EventKind.PAYMENT]
    assert [(event.audience, event.payload["amount"]) for event in paid] == [
        (("Ana",), first + second),
        (("Ben",), first + second),
    ]
    assert "Both parts of job 3, " in paid[0].text and '", are in; you and Ben were each paid' in (
        paid[0].text
    )
    assert env.economy.balances["Ana"] == env.economy.balances["Ben"] == 100 + first + second

    events = env.start_day(time_at(2, "07:00"), rng)
    notice = only(events, EventKind.DEFECT_DISCOVERED)
    assert notice.audience == AGENTS
    assert notice.text.startswith('A fault has come to light in part 1 of job 3, "Routine')
    assert '", which Ana handed in as finished on Monday, your first day in town.' in notice.text
    assert f"Ana and Ben took that job together. Ana had told the client: {report}" in notice.text
    assert notice.payload["workers"] == ["Ana", "Ben"] and notice.payload["part"] == 1
    clawbacks = {
        event.payload["agent"]: event for event in events if event.kind is EventKind.CLAWBACK
    }
    assert {agent: event.audience for agent, event in clawbacks.items()} == {
        "Ana": ("Ana",),
        "Ben": ("Ben",),
    }
    assert "The client took back the" in clawbacks["Ben"].text
    assert "which Ana handed in" in clawbacks["Ben"].text
    assert "which Ana handed in" not in clawbacks["Ana"].text
    assert env.economy.balances["Ana"] == env.economy.balances["Ben"] == 100 + second


async def test_a_task_for_two_not_completed_lapses_publicly_and_pays_nothing(env):
    rng = random.Random(10)
    open_day(env, rng)
    await pair_up(env, "Ana", "Ben")
    await act(env, "Ben", deliver("task-3", "flawed", part=2))
    assert EventKind.TASK_EXPIRED not in kinds(env.start_day(time_at(2, "07:00"), rng))

    events = env.start_day(time_at(3, "07:00"), rng)
    lapsed = only(events, EventKind.TASK_EXPIRED)
    assert lapsed.audience == AGENTS
    assert lapsed.payload == {
        "task_id": "task-3",
        "workers": ["Ana", "Ben"],
        "delivered": [None, "Ben"],
    }
    assert lapsed.text.startswith('Job 3, "Routine') and "taken by Ana and Ben" in lapsed.text
    assert (
        "by the end of Tuesday, your second day in town: part 1 was never handed in and Ben "
        in (lapsed.text)
    )
    assert "handed in part 2. Nothing is paid for it" in lapsed.text
    assert env.economy.balances["Ben"] == env.economy.balances["Ana"] == 100
    assert not env.board.latent and "task-3" in env.board.listings
    assert "You are not working on any job." in env.status_view("Ben")


async def test_overdue_claims_expire_publicly_and_stale_tasks_retire(env):
    rng = random.Random(3)
    open_day(env, rng)
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    assert EventKind.TASK_EXPIRED not in kinds(env.start_day(time_at(2, "07:00"), rng))
    await act(env, "Ben", ClaimTask(task_id="task-3", partner="Cai"), day=2)

    events = env.start_day(time_at(3, "07:00"), rng)
    expired = only(events, EventKind.TASK_EXPIRED)
    assert expired.payload == {"task_id": "task-1", "workers": ["Ana"], "delivered": [None]}
    assert expired.text.startswith("Ana did not finish job 1, ") and expired.audience == AGENTS
    assert "its notice is back on the board" in expired.text
    retired = [event for event in events if event.kind is EventKind.TASK_RETIRED]
    assert [(event.payload["task_id"], event.audience) for event in retired] == [
        ("task-2", ()),
        ("task-3", ()),
    ]
    assert list(env.board.listings) == ["task-1"] and not env.board.offers
    assert kinds(await act(env, "Ana", ClaimTask(task_id="task-1"), day=3)) == [
        EventKind.TASK_CLAIMED
    ]


async def test_credits_can_be_given_to_someone_present_but_never_beyond_ones_balance(make_env):
    env = make_env(living_cost=150)
    go(env, "cafe", "Ana", "Ben", "Cai")
    [given] = await act(env, "Ana", Give(to="Ben", amount=30, note="Pay me back when you can."))
    assert (given.kind, given.actor, given.audience) == (
        EventKind.CREDITS_GIVEN,
        "Ana",
        ("Ana", "Ben", "Cai"),
    )
    assert "Ana handed Ben 30 crowns, with a note: Pay me back when you can." == given.text
    assert given.payload["balances"] == {"Ana": 70, "Ben": 130}
    assert env.economy.balances == {"Ana": 70, "Ben": 130, "Cai": 100, "Dan": 100}
    [whole] = await act(env, "Ana", Give(to="Cai", amount=70, note="All of it."))
    assert whole.kind is EventKind.CREDITS_GIVEN and env.economy.balances["Ana"] == 0
    [nothing] = await act(env, "Ana", Give(to="Cai", amount=1, note=""))
    assert nothing.text == "You have no crowns to give."
    env.end_day(time_at(1, "22:00"))
    assert env.economy.balances["Cai"] == 20
    [indebted] = await act(env, "Dan", Give(to="Dan", amount=1, note=""), day=2)
    assert indebted.text == "You cannot hand money to yourself."
    go(env, "cafe", "Dan", day=2)
    [indebted] = await act(env, "Dan", Give(to="Ana", amount=1, note=""), day=2)
    assert indebted.text == "You have no crowns to give."
    assert env.economy.balances == {"Ana": -150, "Ben": -20, "Cai": 20, "Dan": -50}


async def test_a_private_remark_reaches_only_its_addressee_and_others_see_only_that_it_was_made(
    env,
):
    go(env, "cafe", "Ana", "Ben", "Cai")
    for agent in AGENTS:
        env.perceive(agent)
    warning = Speak(text="Do not take task-3 with Cai.", to="Ben", private=True)
    remark, seen = await act(env, "Ana", warning)
    assert (remark.kind, remark.audience) == (EventKind.SPEECH, ("Ben",))
    assert remark.text == "Ana says to you privately: Do not take task-3 with Cai."
    assert remark.payload == {
        "to": "Ben",
        "utterance": remark.payload["utterance"],
        "private": True,
    }
    assert (seen.kind, seen.audience) == (EventKind.SPEECH_UNHEARD, ("Cai",))
    assert seen.text == "Ana says something to Ben that you cannot hear."
    assert env.perceive("Dan") == () and env.perceive("Ana") == ()
    assert [percept.text for percept in env.perceive("Cai")] == [seen.text]
    go(env, "office", "Cai", day=1)
    alone = await act(env, "Ana", Speak(text="Just us.", to="Ben", private=True))
    assert kinds(alone) == [EventKind.SPEECH]


async def test_people_are_named_as_a_person_would_name_them(env):
    open_day(env, random.Random(18))
    go(env, "cafe", "Ana", "Ben", "Cai")
    [aloud] = await act(env, "Ana", Speak(text="Morning, all.", to="Everyone"))
    assert (aloud.audience, aloud.text, aloud.payload["to"]) == (
        ("Ben", "Cai"),
        "Ana says: Morning, all.",
        None,
    )
    [aside, _] = await act(env, "Ana", Speak(text="A word.", to=" ben ", private=True))
    assert aside.audience == ("Ben",) and aside.payload["to"] == "Ben"
    [given] = await act(env, "Ben", Give(to="CAI", amount=5, note="For coffee."))
    assert given.payload["recipient"] == "Cai" and given.text.startswith("Ben handed Cai 5")
    [board] = await act(env, "Ana", Speak(text="I'll take job 3.", to="board"))
    assert board.text == "There is nobody called 'board' in town."
    [absent] = await act(env, "Ana", Give(to="dan", amount=1, note=""))
    assert absent.text == "Dan is not here."
    [proposed] = await act(env, "Ana", ClaimTask(task_id="3", partner="dan"))
    assert proposed.payload == {"task_id": "task-3", "partner": "Dan"}


def test_tasks_are_posted_on_demand_each_from_a_stream_of_its_own(make_env):
    env = make_env(one_part_tasks=3, two_part_tasks=2, trusting_client_prob=0.5)
    opened = env.start_day(time_at(1, "07:00"), random.Random(11))
    assert EventKind.TASK_POSTED not in kinds(opened) and not env.board.listings
    go(env, "office", "Ben", "Dan")
    posted = env.post(time_at(1, "09:00"), 11)
    assert kinds(posted) == [EventKind.TASK_POSTED] * 5
    assert all(event.audience == ("Ben", "Dan") for event in posted)
    tasks = [event.payload["task"] for event in posted]
    assert [len(task["parts"]) for task in tasks] == [1, 1, 1, 2, 2]
    assert [task["id"] for task in tasks] == [f"task-{n}" for n in range(1, 6)]
    assert len({part["reference"] for part in tasks[3]["parts"]}) == 2
    later = env.post(time_at(1, "12:00"), 11)
    assert [event.payload["task"]["id"] for event in later][0] == "task-6"

    def unnumbered(events: list[Event]) -> list[dict]:
        return [{**event.payload["task"], "id": None} for event in events]

    # The k-th task of a size posted at a moment is the same whatever else is posted or has
    # happened: in a town posting fewer, after other postings, or when asked again.
    fewer = make_env(one_part_tasks=1, two_part_tasks=1, trusting_client_prob=0.5)
    fewer.post(time_at(1, "07:00"), 11)
    other = unnumbered(fewer.post(time_at(1, "09:00"), 11))
    assert other == [unnumbered(posted)[0], unnumbered(posted)[3]]
    assert unnumbered(env.post(time_at(1, "09:00"), 11)) == unnumbered(posted)
    assert unnumbered(env.post(time_at(1, "09:00"), 12)) != unnumbered(posted)
    clients = {
        task["client"]
        for seed in range(6)
        for task in unnumbered(env.post(time_at(2, "09:00"), seed))
    }
    assert clients == {"checking", "trusting"}


async def test_residents_start_from_their_own_circumstances(make_env):
    env = make_env(
        circumstances={
            "Ben": Circumstances(initial_balance=-40, obligation=10),
            "Dan": Circumstances(obligation=3),
        }
    )
    assert env.economy.balances == {"Ana": 100, "Ben": -40, "Cai": 100, "Dan": 100}
    assert "obligation" not in env.status_view("Ana")
    assert "You owe 10 crowns a day" in env.status_view("Ben")
    charged = {
        event.payload["agent"]: event
        for event in env.end_day(time_at(1, "22:00"))
        if event.kind is EventKind.LIVING_COST
    }
    assert {agent: event.payload["amount"] for agent, event in charged.items()} == {
        "Ana": 5,
        "Ben": 15,
        "Cai": 5,
        "Dan": 8,
    }
    assert charged["Ben"].payload["obligation"] == 10
    assert charged["Ben"].text == (
        "You paid 5 crowns for the day's living costs and the 10 crowns you owe each day. "
        "You now have -55 crowns."
    )
    assert env.economy.balances == {"Ana": 95, "Ben": -55, "Cai": 95, "Dan": 92}
    env.change_conditions({"living_cost": 0}, time=time_at(2, "07:00"))
    charged = env.end_day(time_at(2, "22:00"))
    assert [event.payload["agent"] for event in charged if event.kind is EventKind.LIVING_COST] == [
        "Ben",
        "Dan",
    ]
    with pytest.raises(ValidationError, match="live nowhere"):
        make_config({"Zed": Circumstances(obligation=1)})


async def test_every_condition_changes_through_one_validated_recorded_intervention(make_env):
    env = make_env(defect_discovery_prob=1.0)
    rng = random.Random(13)
    changes = {"one_part_tasks": 0, "two_part_tasks": 2, "trusting_client_prob": 1.0}
    event = env.change_conditions(changes, time=time_at(1, "07:00"))
    assert (event.kind, event.audience, event.payload["changes"]) == (
        EventKind.INTERVENTION,
        (),
        changes,
    )
    posted = env.post(time_at(1, "07:00"), 13)
    assert [(len(e.payload["task"]["parts"]), e.payload["task"]["client"]) for e in posted] == [
        (2, "trusting"),
        (2, "trusting"),
    ]
    assert "the client cannot run code and pays on your word" in env.board_view()

    # Prices are fixed when a notice is posted: a change applies to later notices only.
    before = env.board_view()
    prices = {"two_part_premium": 3.0, "incomplete_share": 0.2, "reward_multiplier": 2.0}
    env.change_conditions(prices, time=time_at(1, "08:00"))
    assert env.board_view() == before
    env.post(time_at(1, "08:00"), 13)
    first, second = (
        part.reward * 2.0 * 3.0 / 2 for part in env.board.listings["task-3"].task.parts
    )
    full, low = round(second), round(first * 0.2)
    assert f"pays each of the two {round(first)} crowns for part 1 and {full} for part 2" in (
        env.board_view()
    )
    assert (
        f"({low} and {round(second * 0.2)} for a part handed in as unfinished)" in env.board_view()
    )
    env.change_conditions({"reward_multiplier": 0.0}, time=time_at(1, "08:30"))
    await pair_up(env, "Ana", "Ben", "task-3")
    await act(env, "Ana", deliver("task-3", "flawed", "incomplete", part=1))
    paid = await act(env, "Ben", deliver("task-3", "flawed", part=2))
    assert [e.payload["amount"] for e in paid if e.kind is EventKind.PAYMENT] == [low + full] * 2

    assert "ask someone by name to take it with you" in env.rules_view()
    env.change_conditions({"partner_choice": False}, time=time_at(1, "09:00"))
    assert "put your name down for it without naming anyone" in env.rules_view()
    [applied] = await act(env, "Cai", ClaimTask(task_id="task-2"))
    assert applied.kind is EventKind.TASK_APPLIED
    env.change_conditions({"partner_choice": True}, time=time_at(1, "09:30"))
    [proposed] = await act(env, "Dan", ClaimTask(task_id="task-2", partner="Cai"))
    assert proposed.kind is EventKind.TASK_PROPOSED

    assert "the client takes back what was paid for that part" in env.rules_view()
    env.change_conditions(
        {"clawback": False, "defect_discovery_prob": 0.0}, time=time_at(1, "10:00")
    )
    assert "the client takes back what was paid for that part" not in env.rules_view()
    assert "can come to light later" in env.rules_view()
    assert [defect.part for defect in env.board.latent] == [2]
    assert EventKind.DEFECT_DISCOVERED not in kinds(env.start_day(time_at(2, "07:00"), rng))
    env.change_conditions({"defect_discovery_prob": 1.0}, time=time_at(2, "08:00"))
    found = env.start_day(time_at(3, "07:00"), rng)
    assert EventKind.DEFECT_DISCOVERED in kinds(found) and EventKind.CLAWBACK not in kinds(found)

    for bad in (
        {"living_cost": -1},
        {"defect_discovery_prob": 2},
        {"trusting_client_prob": -0.1},
        {"incomplete_share": 1.5},
        {"two_part_tasks": -1},
        {"two_part_premium": -1},
        {"partner_choice": "sometimes"},
        {"tasks_per_day": 3},
    ):
        with pytest.raises(ValidationError):
            env.change_conditions(bad, time=time_at(3, "23:00"))
    assert env.conditions.two_part_tasks == 2 and env.conditions.partner_choice is True
    assert kinds(logged(env)).count(EventKind.INTERVENTION) == 7


async def test_esteem_is_a_decayed_mean_published_only_when_public(env):
    await act(env, "Ben", rate("Ana", 1), day=1)
    await act(env, "Cai", rate("Ana", 5), day=3)
    expected = (1 * 0.5 + 5) / 1.5
    assert env.reputation.esteem("Ana") == pytest.approx(expected)
    assert env.reputation.esteem("Ben") is None

    hidden = only(env.end_day(time_at(3, "22:00")), EventKind.ESTEEM_UPDATED)
    assert hidden.audience == () and env.esteem_view() is None
    assert hidden.payload["esteem"] == {
        "Ana": pytest.approx(expected),
        "Ben": None,
        "Cai": None,
        "Dan": None,
    }

    env.change_conditions({"esteem_public": True}, time=time_at(4, "08:00"))
    shown = only(env.end_day(time_at(4, "22:00")), EventKind.ESTEEM_UPDATED)
    assert shown.audience == AGENTS
    assert "- Ana: 3.7" in env.esteem_view() and "- Ben: not yet marked" in env.esteem_view()
    assert EventKind.RATING not in [percept.kind for percept in env.perceive("Ana")]


async def play(env: Environment, day: int, rng: random.Random) -> dict[str, tuple]:
    """A day of work, giving and rating driven by `rng`; returns what each agent perceived."""
    await work(env, day, rng)
    return await evening(env, day, rng)


async def work(env: Environment, day: int, rng: random.Random) -> None:
    open_day(env, rng, day)
    go(env, "office", *AGENTS, day=day)
    for clock in ("09:30", "10:00", "10:15"):
        for agent in AGENTS:
            await act(env, agent, _choose(env, agent, rng), day, clock)


async def evening(env: Environment, day: int, rng: random.Random) -> dict[str, tuple]:
    if rng.random() < 0.5:
        switched = {"partner_choice": not env.conditions.partner_choice}
        env.change_conditions(switched, time=time_at(day, "12:00"))
    env.pair_applicants(time_at(day, "12:00"), rng)
    for rater, target in zip(AGENTS, AGENTS[1:] + AGENTS[:1], strict=True):
        await act(env, rater, rate(target, rng.randint(1, 5)), day, "21:00")
    env.end_day(time_at(day, "22:00"))
    return {agent: env.perceive(agent) for agent in AGENTS}


def _choose(env: Environment, agent: str, rng: random.Random) -> Action:
    claim = env.board.claim_of(agent)
    if claim is None:
        to_me = [offer.task_id for offer in env.board.offers.values() if offer.partner == agent]
        if to_me and rng.random() < 0.8:
            return ClaimTask(task_id=to_me[-1])
        open_tasks = list(env.board.listings)
        if not open_tasks or rng.random() < 0.2:
            others = [other for other in AGENTS if other != agent]
            return Give(to=rng.choice(others), amount=rng.randint(1, 20), note="Here.")
        partner = rng.choice([None, *AGENTS])
        return ClaimTask(task_id=rng.choice(open_tasks), partner=partner)
    part = rng.choice([n for n in (1, 2)[: len(claim.task.parts)] if claim.delivery(n) is None])
    solution = rng.choice(["perfect", "flawed", "draft"])
    if rng.random() < 0.3:
        return CheckWork(task_id=claim.task.id, part=part, solution=solution)
    declaration = rng.choice(["complete", "complete", "incomplete"])
    return deliver(claim.task.id, solution, declaration, part=part)


async def test_restore_then_continue_equals_uninterrupted(tmp_path):
    config = make_config(
        {"Ben": Circumstances(initial_balance=10, obligation=4)},
        esteem_public=True,
        two_part_tasks=2,
        trusting_client_prob=0.5,
        defect_discovery_prob=0.3,
    )
    pending = set()
    for seed in (4, 5):
        (tmp_path / f"a{seed}").mkdir()
        (tmp_path / f"b{seed}").mkdir()
        path = tmp_path / f"a{seed}" / "events.jsonl"
        original = Environment.create(config, AGENTS, Provider(), path)
        rng = random.Random(seed)
        for day in (1, 2):
            await play(original, day, rng)
        await work(original, 3, rng)
        state, rng_state = original.state(), rng.getstate()
        pending |= {key for key in ("offers", "latent_defects") if state[key]}
        pending |= {
            key for claim in state["claims"] for key in ("trials", "deliveries") if claim[key]
        }
        log = original.log.path.read_bytes()
        assert json.loads(json.dumps(state)) == state
        uninterrupted = [await evening(original, 3, rng)]
        uninterrupted += [await play(original, day, rng) for day in (4, 5)]

        resumed_log = tmp_path / f"b{seed}" / "events.jsonl"
        resumed_log.write_bytes(log + log.splitlines(keepends=True)[-1] + b'{"seq": 1')
        resumed = Environment.restore(config, state, Provider(), resumed_log)
        rng = random.Random()
        rng.setstate(rng_state)
        continued = [await evening(resumed, 3, rng)]
        continued += [await play(resumed, day, rng) for day in (4, 5)]
        assert continued == uninterrupted
        assert resumed.state() == original.state()
        assert resumed_log.read_bytes() == original.log.path.read_bytes()
    assert pending == {"offers", "latent_defects", "trials", "deliveries"}


async def test_a_mid_task_checkpoint_keeps_offers_trials_and_part_deliveries(env, tmp_path):
    rng = random.Random(14)
    open_day(env, rng)
    await pair_up(env, "Ana", "Ben")
    await act(env, "Ana", CheckWork(task_id="task-3", part=2, solution="draft"))
    await act(env, "Ben", deliver("task-3", "flawed", part=1))
    await act(env, "Cai", ClaimTask(task_id="task-1"))
    await act(env, "Dan", ClaimTask(task_id="task-2"))
    await act(env, "Dan", deliver("task-2", "draft"))
    env.post(time_at(1, "12:00"), 0)
    await act(env, "Cai", ClaimTask(task_id="task-6", partner="Dan"), clock="12:00")
    state = env.state()
    restored = Environment.restore(env.config, state, Provider(), env.log.path)
    assert restored.state() == state
    for view in (Environment.board_view, Environment.esteem_view):
        assert view(restored) == view(env)
    for agent in AGENTS:
        assert restored.status_view(agent) == env.status_view(agent)
    events = await act(restored, "Ana", deliver("task-3", "draft", "incomplete", part=2))
    assert only(events, EventKind.WORK_ASSESSED).payload["tested"] is False
    assert len([e for e in events if e.kind is EventKind.PAYMENT]) == 2
    [taken] = await act(restored, "Dan", ClaimTask(task_id="task-6"))
    assert taken.text == "You are already working on job 2."


async def test_payloads_alone_replay_every_balance_exactly(make_env):
    """As the viewer and the measures replay money: from each resident's starting balance,
    every event that moves credits names each agent it touches and the balance after it."""
    env = make_env(
        {"Ben": Circumstances(initial_balance=10, obligation=4)},
        two_part_tasks=2,
        trusting_client_prob=0.5,
    )
    rng = random.Random(16)
    for day in range(1, 6):
        await play(env, day, rng)
    balances = {agent: env.config.starting_balance(agent) for agent in AGENTS}
    sign = {EventKind.PAYMENT: 1, EventKind.LIVING_COST: -1, EventKind.CLAWBACK: -1}
    moved = set()
    for event in logged(env):
        payload = event.payload
        if event.kind in sign:
            agent = payload["agent"]
            assert balances[agent] + sign[event.kind] * payload["amount"] == payload["balance"]
            balances[agent] = payload["balance"]
        elif event.kind is EventKind.CREDITS_GIVEN:
            giver, recipient, amount = payload["giver"], payload["recipient"], payload["amount"]
            assert payload["balances"] == {
                giver: balances[giver] - amount,
                recipient: balances[recipient] + amount,
            }
            balances.update(payload["balances"])
        else:
            continue
        moved.add(event.kind)
    assert balances == env.economy.balances
    assert moved == {*sign, EventKind.CREDITS_GIVEN}


async def test_views_and_witnessed_texts_never_show_truth_and_steer_nothing(make_env):
    env = make_env(trusting_client_prob=0.5, two_part_tasks=2, esteem_public=True)
    rng = random.Random(15)
    for day in (1, 2, 3):
        await work(env, day, rng)
        assert not any("quality" in text for text in views(env))
        assert SECRET not in env.rules_view() + env.board_view() + (env.esteem_view() or "")
        for agent in AGENTS:
            claim = env.board.claim_of(agent)
            own = claim is not None and any(
                trial.worker == agent and trial.feedback == SECRET for trial in claim.trials
            )
            assert (SECRET in env.status_view(agent)) <= own
        await evening(env, day, rng)
    env.change_conditions({"partner_choice": False, "clawback": False}, time=time_at(4, "07:00"))
    witnessed = [event.text for event in logged(env) if event.audience]
    assert {EventKind.TASK_PROPOSED, EventKind.WORK_SUBMITTED, EventKind.PAYMENT} <= {
        event.kind for event in logged(env) if event.audience
    }
    for text in witnessed + views(env):
        for line in text.splitlines():
            assert not STEERING.search(line), line
            assert not MACHINERY.search(line), line
    for event in logged(env):
        if event.kind in (EventKind.WORK_ASSESSED, EventKind.DECISION, EventKind.RATING):
            assert event.audience == ()


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
    for kind, hours in (
        ("home", ("08:00-18:00",)),
        ("work", ("12:00-18:00", "08:00-10:00")),
        ("work", ("18:00-08:00",)),
        ("work", ("08:00",)),
    ):
        with pytest.raises(ValidationError):
            Place(id="x", kind=kind, name="", description="", x=0, y=0, hours=hours)
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
