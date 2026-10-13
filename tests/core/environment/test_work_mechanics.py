"""The mechanics of work the first seven-day run called for: an asking names the part the
asker will do and stands until the notice comes down or the asker takes another job; a
hand-in or a try may name the draft on the desk; a client who pays on the word takes only the
word of those whose standing reaches the threshold; and the night tells what is still on the
desk."""

import random

import pytest
from pydantic import ValidationError

from core.environment import Conditions, Environment, Trade
from core.interaction import (
    Card,
    CheckWork,
    ClaimTask,
    EventKind,
    MayCheck,
    MaySubmit,
    SubmitWork,
    form,
    time_at,
)
from core.interaction.card import DRAFT
from runtime.scenes import Review, WorkSession
from tests.core.environment.test_environment import (
    AGENTS,
    DEFAULTS,
    SECRET,
    act,
    deliver,
    ended,
    go,
    kinds,
    make_config,
    only,
    open_day,
    rate,
)
from tests.core.environment.test_trades import traders


async def test_an_asking_names_the_part_and_stands_until_the_notice_comes_down(env):
    rng = random.Random(21)
    open_day(env, rng)
    go(env, "office", "Ana", "Ben", "Cai")
    [asked] = await act(env, "Ana", ClaimTask(task_id="task-3", partner="Ben", part=2))
    assert asked.kind is EventKind.TASK_PROPOSED
    assert asked.payload == {"task_id": "task-3", "partner": "Ben", "part": 2}
    assert asked.text.endswith('", together, Ana to do part 2 and Ben part 1.')
    assert asked.percept("Ben").text.endswith("together, Ana to do part 2 and you part 1.")
    assert asked.percept("Ana").text.endswith("together, you to do part 2 and Ben part 1.")
    assert ") together, you to do part 2 and Ben part 1." in env.status_view("Ana")
    assert ") together, Ana to do part 2 and you part 1." in env.status_view("Ben")
    assert "the part you mean to do" in env.rules_view()
    assert "it lapses at the end of the day" not in env.rules_view()

    # The asking stands overnight, and is taken up the next day.
    assert EventKind.OFFER_ENDED not in kinds(env.end_day(time_at(1, "22:00")))
    assert EventKind.OFFER_ENDED not in kinds(env.start_day(time_at(2, "07:00"), rng))
    assert ") together, Ana to do part 2 and you part 1." in env.status_view("Ben")
    [taken] = await act(env, "Ben", ClaimTask(task_id="task-3"), day=2)
    assert taken.kind is EventKind.TASK_CLAIMED
    assert taken.payload["parts"] == {"Ana": 2, "Ben": 1}
    assert taken.text.endswith(
        "; Ana is to do part 2 and Ben part 1, though either may hand in either."
    )
    assert taken.percept("Ana").text.endswith(
        "; you are to do part 2 and Ben part 1, though either may hand in either."
    )
    assert taken.percept("Ben").text.endswith(
        "; Ana is to do part 2 and you part 1, though either may hand in either."
    )
    assert "it is due by the end of" in env.status_view("Ben")
    assert "; Ana is to do part 2 and you part 1, though either of you may hand in either." in (
        env.status_view("Ben")
    )
    events = await act(env, "Ben", deliver("task-3", "perfect", part=2), day=2)  # either part
    assert only(events, EventKind.WORK_SUBMITTED).payload["accepted"] is True

    # An asking ends when the notice comes down, or when the asker takes another job.
    env.post(time_at(2, "12:00"), 0)  # task-4 and task-5 alone, task-6 for two
    await act(env, "Cai", ClaimTask(task_id="task-6", partner="Dan", part=1), day=2)
    assert EventKind.OFFER_ENDED not in kinds(env.end_day(time_at(2, "22:00")))
    came_down = env.start_day(time_at(4, "07:00"), rng)  # posted two days ago: retired
    assert only(came_down, EventKind.OFFER_ENDED).payload["cause"] == "came_down"
    assert ended(came_down) == {
        "Cai": "Your asking of Dan for job 6 ended, since the notice of job 6 came down.",
        "Dan": "Cai's asking of you for job 6 ended, since the notice of job 6 came down.",
    }
    assert not env.board.offers
    env.post(time_at(4, "09:00"), 1)  # task-7, task-8 alone, task-9 for two
    await act(env, "Cai", ClaimTask(task_id="task-9", partner="Dan", part=2), day=4)
    _, *others = await act(env, "Cai", ClaimTask(task_id="task-7"), day=4)
    assert only(others, EventKind.OFFER_ENDED).payload["cause"] == "took_another"
    assert ended(others)["Dan"] == (
        "Cai's asking of you for job 9 is withdrawn, since Cai took job 7."
    )


async def test_a_name_put_down_stands_overnight_too(make_env):
    env = make_env(partner_choice=False)
    rng = random.Random(22)
    open_day(env, rng)
    await act(env, "Ana", ClaimTask(task_id="task-3"))
    assert EventKind.OFFER_ENDED not in kinds(env.end_day(time_at(1, "22:00")))
    assert "Your name is down for job 3" in env.status_view("Ana")
    assert "it stands until the clerk pairs you or the notice comes down" in env.rules_view()
    await act(env, "Ben", ClaimTask(task_id="task-3"), day=2)
    [paired] = env.pair_applicants(time_at(2, "10:00"), rng)
    assert paired.kind is EventKind.TASK_CLAIMED and paired.payload["parts"] == {}
    assert "though either" not in paired.text


async def test_a_hand_in_or_a_try_may_name_the_draft_on_the_desk(env):
    open_day(env, random.Random(23))
    go(env, "office", "Ana", "Ben")
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    await act(env, "Ben", ClaimTask(task_id="task-2"))
    work = WorkSession(
        env,
        "work",
        "office",
        ["Ana", "Ben"],
        start=time_at(1, "09:00"),
        until=time_at(1, "10:00"),
        rounds=1,
        closes=False,
    )
    bare = [a for a in work.allowed("Ana") if isinstance(a, MayCheck | MaySubmit)]
    assert all(a.drafts == () for a in bare)
    assert "draft on your desk" not in form(Card(bare).model)
    [none] = await act(env, "Ana", CheckWork(task_id="task-1", part=1, solution=DRAFT))
    assert none.kind is EventKind.ACTION_REJECTED
    assert none.text.startswith('There is no draft on your desk for job 1, "Routine')
    assert env.providers[Trade.PROGRAMMING].assessed == 0

    long = "x = 1\n" * 2000  # longer than any limit the desk ever had
    [tried] = await act(env, "Ana", CheckWork(task_id="task-1", part=1, solution=long))
    assert tried.payload["solution"] == long and SECRET in tried.text
    assert f"The draft on your desk, the code you tried:\n```\n{long.rstrip()}\n```" in (
        env.status_view("Ana")
    )
    with_draft = [a for a in work.allowed("Ana") if isinstance(a, MayCheck | MaySubmit)]
    assert all(a.drafts == (1,) for a in with_draft)
    assert '"code": "…" (or "the draft on your desk", to use it as it is)' in (
        form(Card(with_draft).model)
    )
    [again] = await act(env, "Ana", CheckWork(task_id="task-1", part=1, solution=DRAFT))
    assert again.kind is EventKind.WORK_CHECKED and again.payload["solution"] == long
    events = await act(env, "Ana", deliver("task-1", DRAFT, "incomplete"))
    submitted = only(events, EventKind.WORK_SUBMITTED)
    assert submitted.payload["accepted"] and submitted.payload["solution"] == long
    assert only(events, EventKind.WORK_ASSESSED).payload["tested"] is False

    # A draft is one's own: a partner's try leaves nothing on your desk.
    await act(env, "Cai", ClaimTask(task_id="task-3", partner="Dan", part=1))
    await act(env, "Dan", ClaimTask(task_id="task-3"))
    await act(env, "Cai", CheckWork(task_id="task-3", part=2, solution="draft"))
    [none] = await act(env, "Dan", deliver("task-3", DRAFT, part=2))
    assert none.text.startswith('There is no draft on your desk for part 2 of job 3, "Routine')
    [none] = await act(env, "Cai", deliver("task-3", DRAFT, part=1))
    assert none.text.startswith('There is no draft on your desk for part 1 of job 3, "Routine')
    events = await act(env, "Cai", deliver("task-3", DRAFT, part=2))
    assert only(events, EventKind.WORK_SUBMITTED).payload["solution"] == "draft"


async def test_a_client_who_pays_on_the_word_takes_only_the_word_of_the_well_regarded(
    make_env,
):
    env = make_env(trusting_client_prob=1.0, trust_threshold=3.5, one_part_tasks=3)
    rng = random.Random(24)
    await act(env, "Dan", rate("Ben", 4), clock="21:00")
    await act(env, "Cai", rate("Ben", 4), clock="21:00")
    await act(env, "Dan", rate("Cai", 2), clock="21:00")
    open_day(env, rng)
    notice = (
        "the client pays on the word of anyone whose standing is at least 3.5, and tries the "
        "examples of anyone else's work before paying"
    )
    assert notice in env.board_view()
    rules = env.rules_view()
    assert (
        "Other clients pay the full price for a part handed in as finished on the word of "
        "anyone whose standing in the clerk's ledger is at least 3.5, and check anyone else's "
        "work as the first kind does. Each notice says which kind of client it has."
    ) in rules
    go(env, "office", *AGENTS)
    for agent, task in (("Ana", "task-1"), ("Ben", "task-2"), ("Cai", "task-3")):
        await act(env, agent, ClaimTask(task_id=task))
    assert 'You are working on job 1, "Routine' in env.status_view("Ana")
    assert notice in env.status_view("Ana")

    # Ana, not yet marked, is below any threshold: the client checks and hands back.
    events = await act(env, "Ana", deliver("task-1", "draft"))
    handed_back = only(events, EventKind.WORK_SUBMITTED)
    assert handed_back.audience == ("Ana",)
    assert handed_back.text.startswith(
        "The client, not taking your word, you having no standing yet, tried the examples of "
        'job 1, "Routine'
    )
    assert handed_back.text.endswith(
        f"and they did not pass; the clerk handed the work back with what the client found:\n"
        f"{SECRET}"
    )
    assessed = only(events, EventKind.WORK_ASSESSED).payload
    assert (assessed["client"], assessed["checked"], assessed["accepted"]) == (
        "trusting",
        True,
        False,
    )
    events = await act(env, "Ana", deliver("task-1", "flawed", report="Passes."))
    accepted = only(events, EventKind.WORK_SUBMITTED)
    assert accepted.percept("Ana").text == (
        f'Job 1, "{env.board.latent[0].task.parts[0].title}", is in: the client would not take '
        "your word, you having no standing yet; its examples passed and the client accepted it."
    )
    assert accepted.percept("Ben").text.startswith("Ana handed in job 1, ")
    assert (
        "as finished; the client would not take Ana's word, Ana having no standing yet; its "
        'examples passed and the client accepted it. Ana told the client: "Passes."'
    ) in accepted.percept("Ben").text
    assert [defect.worker for defect in env.board.latent] == ["Ana"]

    # Ben, marked 4, is taken at his word; Cai, marked 2, is not.
    events = await act(env, "Ben", deliver("task-2", "draft"))
    submitted = only(events, EventKind.WORK_SUBMITTED)
    assert submitted.payload["accepted"] and submitted.payload["checked"] is False
    assert "the client accepted it on Ben's word" in submitted.text
    events = await act(env, "Cai", deliver("task-3", "draft"))
    handed_back = only(events, EventKind.WORK_SUBMITTED)
    assert handed_back.text.startswith(
        "The client, not taking your word, your standing being below 3.5, tried the examples"
    )
    assert handed_back.payload["accepted"] is False
    # Handed in as unfinished, nothing is checked, whatever the standing.
    events = await act(env, "Cai", deliver("task-3", "draft", "incomplete"))
    submitted = only(events, EventKind.WORK_SUBMITTED)
    assert submitted.payload["accepted"] and submitted.payload["checked"] is False
    assert "at the lower price" in submitted.text

    # Without a threshold the client pays on everyone's word; the knob is bounded.
    env.change_conditions({"trust_threshold": None}, time=time_at(1, "12:00"))
    assert "the client cannot run code and pays on your word" in env.board_view()
    assert "pays on the word of anyone" not in env.rules_view()
    for bad in ({"trust_threshold": 0.5}, {"trust_threshold": 6}):
        with pytest.raises(ValidationError):
            env.change_conditions(bad, time=time_at(1, "12:00"))
    assert Conditions(**DEFAULTS).trust_threshold is None


def test_a_client_holding_the_answer_pays_the_well_regarded_on_their_word(tmp_path):
    config = make_config(
        one_part_tasks=1,
        two_part_tasks=0,
        trade_mix={Trade.CALCULATION: 1.0},
        trusting_client_prob=1.0,
        trust_threshold=4,
    )
    env = Environment.create(config, AGENTS, traders(), tmp_path / "events.jsonl")
    env.post(time_at(1, "09:00"), 0)
    assert (
        "a calculation for one; the client holds the answer; it pays on the word of anyone "
        "whose standing is at least 4, and compares anyone else's answer before paying"
    ) in env.board_view()


async def test_the_night_tells_what_is_still_on_the_desk(env):
    rng = random.Random(25)
    open_day(env, rng)
    go(env, "office", *AGENTS)
    night = time_at(1, "22:00")
    met = {agent: [other for other in AGENTS if other != agent] for agent in AGENTS}
    review = Review(env, "review", met, start=night)
    assert "Still on your desk" not in review.situation("Dan")
    assert review.situation("Dan").endswith("the clerk's ledger is open to you.")

    await act(env, "Ana", ClaimTask(task_id="task-1"))
    await act(env, "Ana", CheckWork(task_id="task-1", part=1, solution="draft"))
    await act(env, "Ben", ClaimTask(task_id="task-3", partner="Cai", part=1))
    await act(env, "Cai", ClaimTask(task_id="task-3"))
    await act(env, "Ben", deliver("task-3", "perfect", part=1))
    await act(env, "Cai", SubmitWork(task_id="task-3", part=2, solution="draft", report="."))
    await act(env, "Dan", ClaimTask(task_id="task-2"))
    due = "due by the end of Tuesday, your second day in town"
    assert review.situation("Ana").endswith(
        f'\n\nStill on your desk: job 1, "{_title(env, "task-1", 1)}", {due}: it is not in yet; '
        "your last try of it failed."
    )
    titles = f'"{_title(env, "task-3", 1)}" and "{_title(env, "task-3", 2)}"'
    assert review.situation("Cai").endswith(
        f"Still on your desk: job 3, {titles}, with Ben, {due}: part 1 is in (Ben handed it "
        "in); part 2 is not in yet; the clerk handed it back."
    )
    assert review.situation("Ben").endswith(
        "part 1 is in (you handed it in); part 2 is not in yet; you have not tried it."
    )
    assert review.situation("Dan").endswith(f"{due}: it is not in yet; you have not tried it.")


def _title(env: Environment, task_id: str, part: int) -> str:
    return env.board.claims[task_id].task.parts[part - 1].title
