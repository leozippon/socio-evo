"""Establishments: the configuration refuses a firm that cannot stand; a firm's job sheet is
posted to and taken from by its people alone and its clients pay the foreman, as its notices
tell them, who bears the clawbacks; wages go to the staff present at the day's end; places are
asked for, filled, given up and taken away, each refusal a plain word; and a checkpoint keeps
it all."""

import random
import re

import pytest
from pydantic import ValidationError

from core.environment import Environment, EnvironmentConfig, Place
from core.environment.environment import FIRMS_RULE
from core.interaction import Apply, ClaimTask, Dismiss, EventKind, Hire, Resign, time_at
from tests.core.environment.test_environment import (
    AGENTS,
    Provider,
    act,
    deliver,
    go,
    kinds,
    logged,
    make_config,
    only,
)

MILL = {
    "id": "mill",
    "kind": "work",
    "name": "the mill",
    "description": "",
    "x": 1,
    "y": 1,
    "hours": ("08:00-10:30", "12:00-18:00"),
    "trade": "programming",
    "establishment": {
        "foreman": "Ana",
        "staff": ["Ben"],
        "wage": 10,
        "positions": 3,
        "postings": {"one_part": 1, "two_part": 1},
    },
}


def with_mill(**changes) -> EnvironmentConfig:
    """The test town with the mill, a firm of Ana's with Ben on its staff and a place to fill."""
    config = make_config(**changes)
    places = (*config.places, Place.model_validate(MILL))
    return EnvironmentConfig.model_validate({**config.model_dump(), "places": places})


@pytest.fixture
def mill(tmp_path) -> Environment:
    return Environment.create(with_mill(), AGENTS, Provider(), tmp_path / "events.jsonl")


@pytest.mark.parametrize(
    ("changes", "refusal"),
    [
        ({"establishment": {**MILL["establishment"], "foreman": "Zed"}}, "live nowhere"),
        ({"establishment": {**MILL["establishment"], "staff": ["Ben", "Ben"]}}, "repeat"),
        ({"establishment": {**MILL["establishment"], "staff": ["Ana"]}}, "repeat"),
        ({"establishment": {**MILL["establishment"], "positions": 1}}, "positions do not hold"),
        ({"establishment": {**MILL["establishment"], "wage": -1}}, "greater than or equal"),
        ({"kind": "social"}, "not a work place"),
        ({"establishment": None}, "a trade and an establishment, or neither"),
        ({"trade": None}, "a trade and an establishment, or neither"),
    ],
)
def test_a_firm_that_cannot_stand_is_refused(changes, refusal):
    config = make_config()
    with pytest.raises(ValidationError, match=refusal):
        places = (*config.places, Place.model_validate({**MILL, **changes}))
        EnvironmentConfig.model_validate({**config.model_dump(), "places": places})


def test_a_resident_holds_at_most_one_position():
    config = make_config()
    second = {
        **MILL,
        "id": "forge",
        "name": "the forge",
        "establishment": {**MILL["establishment"], "foreman": "Cai"},
    }
    places = (*config.places, Place.model_validate(MILL), Place.model_validate(second))
    with pytest.raises(ValidationError, match="repeated position holders: \\['Ben'\\]"):
        EnvironmentConfig.model_validate({**config.model_dump(), "places": places})


async def test_a_firms_sheet_is_posted_to_and_taken_from_by_its_people_and_pays_its_foreman(mill):
    env, rng = mill, random.Random(31)
    assert FIRMS_RULE in env.rules_view()
    go(env, "mill", "Ana", "Ben", "Cai")
    go(env, "office", "Dan")
    env.start_day(time_at(1, "07:00"), rng)
    posted = env.post(time_at(1, "09:00"), 0)
    sheets = [(e.payload["task"]["id"], e.payload["task"]["sheet"], e.audience) for e in posted]
    assert sheets == [
        ("task-1", None, ("Dan",)),
        ("task-2", None, ("Dan",)),
        ("task-3", None, ("Dan",)),
        ("task-4", "mill", ("Ana", "Ben")),
        ("task-5", "mill", ("Ana", "Ben")),
    ]
    assert posted[3].text.startswith("A new notice on the mill's job sheet: job 4, ")
    assert [task.id for task in env.notices_for("Ana")] == ["task-4", "task-5"]
    assert env.notices_for("Cai") == [] and [t.id for t in env.notices_for("Dan")] == [
        "task-1",
        "task-2",
        "task-3",
    ]
    assert env.board_view("Ana").startswith("On the mill's job sheet:\n- Job 4, ")
    assert (
        env.board_view("Cai")
        == "The notices here are on the mill's job sheet, which only its people take from."
    )
    assert env.board_view("Dan").endswith(
        "- The mill has a place for a programmer at 10 crowns a day; anyone without a place "
        "may ask for it."
    )
    assert (
        env.board_view().count("\n- ") == 4
    )  # the board as anyone sees it: three jobs and the place

    [refused] = await act(env, "Cai", ClaimTask(task_id="task-4"))
    assert refused.text == "Cai is not of the mill; only its people take from its job sheet."
    [refused] = await act(env, "Ana", ClaimTask(task_id="task-5", partner="Cai", part=1))
    assert refused.text == "Cai is not of the mill; only its people take from its job sheet."
    [taken] = await act(env, "Ben", ClaimTask(task_id="task-4"))
    assert taken.kind is EventKind.TASK_CLAIMED
    price = env.board.claims["task-4"].task.prices[0].finished
    events = await act(env, "Ben", deliver("task-4", "flawed", report="Done."))
    paid = only(events, EventKind.PAYMENT)
    assert paid.audience == ("Ana", "Ben")
    assert paid.payload == {
        "agent": "Ana",
        "task_id": "task-4",
        "amount": price,
        "balance": 100 + price,
        "workers": ["Ben"],
    }
    assert (
        paid.percept("Ana").text
        == f"The clerk paid you, for the mill, {price} crowns. You now have {100 + price} crowns."
    )
    told = paid.percept("Ben").text
    assert told.startswith(f"The clerk paid the mill {price} crowns for job 4, ")
    assert told.endswith("; what you are paid is your wage.")
    assert env.economy.balances["Ben"] == 100
    await act(env, "Ana", ClaimTask(task_id="task-5", partner="Ben", part=1))
    await act(env, "Ben", ClaimTask(task_id="task-5"))
    await act(env, "Ana", deliver("task-5", "perfect", part=1))
    events = await act(env, "Ben", deliver("task-5", "perfect", part=2))
    paid = only(events, EventKind.PAYMENT)
    task = paid.payload["task_id"]
    assert paid.payload["agent"] == "Ana" and paid.payload["workers"] == ["Ana", "Ben"]
    assert paid.percept("Ben").text.startswith("Both parts of job 5, ")
    assert "; the clerk paid the mill " in paid.percept("Ben").text
    assert task == "task-5"

    found = env.start_day(time_at(2, "07:00"), random.Random(1))  # discovery probability 0.5
    while EventKind.DEFECT_DISCOVERED not in kinds(found):
        found = env.start_day(time_at(2, "07:00"), random.Random(1))
    clawback = only(found, EventKind.CLAWBACK)
    assert clawback.audience == ("Ana",) and clawback.payload["agent"] == "Ana"
    assert clawback.text.startswith(
        f"The client took back the {price} crowns the mill was paid for job 4, "
    )
    assert ", which Ben handed in. You now have" in clawback.text


async def test_a_job_on_a_firms_sheet_tells_whom_it_pays(mill):
    """Its staff read that the client pays the firm and that what they are paid is their wage,
    never that the price is theirs; the foreman reads what the firm earns; a worker who has
    left the staff is promised no wage; and the board's notices read as they always have."""
    env = mill
    go(env, "mill", "Ana", "Ben", "Cai")
    go(env, "office", "Dan")
    env.start_day(time_at(1, "07:00"), random.Random(31))
    posted = env.post(time_at(1, "09:00"), 0)
    alone, together = (env.board.listings[f"task-{n}"].task for n in (4, 5))
    full, low = alone.prices[0].finished, alone.prices[0].unfinished
    total = 2 * sum(price.finished for price in together.prices)
    less = [2 * (price.finished - price.unfinished) for price in together.prices]
    firm = [
        f"pays the mill {full} crowns, {low} crowns if handed in as unfinished",
        f"pays the mill {total} crowns in all, {less[0]} crowns less if part 1 is handed in as "
        f"unfinished and {less[1]} crowns less if part 2 is",
    ]
    wage = "; what you are paid is your wage;"

    foreman, staff = env.board_view("Ana").splitlines()[1:], env.board_view("Ben").splitlines()[1:]
    for earns, as_foreman, as_staff in zip(firm, foreman, staff, strict=True):
        assert f"; {earns}; two days" in as_foreman and "what you are paid" not in as_foreman
        assert f"; {earns}{wage} two days" in as_staff
        assert not re.search(r"pays \d|each of|to each|each is paid", as_staff), as_staff
    for event, earns in zip(posted[3:], firm, strict=True):
        assert f"; {earns}; two days" in event.text and event.percept("Ana").text == event.text
        assert f"; {earns}{wage} two days" in event.percept("Ben").text
    board = env.board_view("Dan").splitlines()[1]
    first = env.board.listings["task-1"].task.prices[0]
    assert board == (
        f'- Job 1, "{env.board.listings["task-1"].task.parts[0].title}": a programming job for '
        "one; the client tries the examples before paying; pays "
        f"{first.finished} crowns, {first.unfinished} crowns if handed in as unfinished; two "
        "days to do it, counting the day it is taken."
    )

    await act(env, "Ana", ClaimTask(task_id="task-5", partner="Ben", part=1))
    await act(env, "Ben", ClaimTask(task_id="task-5"))
    price = together.prices[0]
    held = (
        f'Part 1, "{together.parts[0].title}": not in yet; it pays the mill '
        f"{2 * price.finished} crowns, {2 * price.unfinished} crowns if handed in as unfinished."
    )
    for agent in ("Ana", "Ben"):
        assert held in env.status_view(agent) and "each of you" not in env.status_view(agent)
    await act(env, "Ana", deliver("task-5", "perfect", part=1))
    assert f"; it pays the mill {2 * price.finished} crowns.\n" in env.status_view("Ben")
    paid = only(await act(env, "Ben", deliver("task-5", "perfect", part=2)), EventKind.PAYMENT)
    assert paid.percept("Ben").text.endswith(
        f"; the clerk paid the mill {total} crowns for it; what you are paid is your wage."
    )
    assert f"; the clerk paid you, for the mill, {total} crowns." in paid.percept("Ana").text

    await act(env, "Ben", ClaimTask(task_id="task-4"))
    await act(env, "Ana", Dismiss(who="Ben"))
    paid = only(await act(env, "Ben", deliver("task-4", "perfect")), EventKind.PAYMENT)
    assert paid.percept("Ben").text == paid.text  # no longer of its staff: no wage is promised
    assert paid.text.startswith(f"The clerk paid the mill {full} crowns for job 4, ")
    assert paid.text.endswith('".')


async def test_wages_go_to_the_staff_present_from_the_foremans_purse(mill):
    env = mill
    go(env, "mill", "Ana", "Ben", "Cai")
    assert env.status_view("Ben").splitlines()[1] == (
        "You work at the mill (Ana is the foreman); 10 crowns a day, paid for the days you are "
        "there."
    )
    assert env.status_view("Ana").splitlines()[1] == (
        "You are the foreman of the mill; its staff are Ben, at 10 crowns a day each, paid for the "
        "days they are there; it has a place to fill."
    )
    assert "You work at" not in env.status_view("Cai") and "foreman" not in env.status_view("Cai")
    events = env.end_day(time_at(1, "22:00"))
    wage = only(events, EventKind.WAGE_PAID)
    assert wage.audience == ("Ana", "Ben")
    assert wage.text == "The mill paid Ben the day's wage of 10 crowns."
    assert (
        wage.percept("Ben").text
        == "The mill paid you the day's wage of 10 crowns. You now have 110 crowns."
    )
    assert (
        wage.percept("Ana").text
        == "You paid Ben the day's wage of 10 crowns from your purse. You now have 90 crowns."
    )
    assert wage.payload == {
        "agent": "Ben",
        "foreman": "Ana",
        "place": "mill",
        "amount": 10,
        "balances": {"Ben": 110, "Ana": 90},
    }
    assert kinds(events).index(EventKind.WAGE_PAID) < kinds(events).index(EventKind.LIVING_COST)
    go(env, "office", "Ben", day=2)
    assert EventKind.WAGE_PAID not in kinds(
        env.end_day(time_at(2, "22:00"))
    )  # not at the mill today


async def test_the_wage_goes_at_night_to_the_staff_then_who_came_that_day(tmp_path):
    """Whoever comes to a firm has been there that day: at night each of its staff then who
    came is paid, so one taken on that day after coming is paid for it, wherever it was when
    taken on, and one dismissed after coming is not, nor one who stayed away or the foreman."""
    config = make_config()
    firm = {**MILL, "establishment": {**MILL["establishment"], "positions": 4}}
    places = (*config.places, Place.model_validate(firm))
    config = EnvironmentConfig.model_validate({**config.model_dump(), "places": places})
    env = Environment.create(config, AGENTS, Provider(), tmp_path / "events.jsonl")

    def paid(day: int) -> set[str]:
        ended = env.end_day(time_at(day, "22:00"))
        return {event.payload["agent"] for event in ended if event.kind is EventKind.WAGE_PAID}

    go(env, "mill", *AGENTS)
    await act(env, "Cai", Apply(firm="the mill"))
    await act(env, "Dan", Apply(firm="the mill"))
    go(env, "office", "Dan")
    await act(env, "Ana", Hire(who="Cai"))
    await act(env, "Ana", Hire(who="Dan"))  # at the office, having come to the mill
    assert paid(1) == {"Ben", "Cai", "Dan"}

    for agent in AGENTS:
        env.move(agent, env.config.homes[agent], time=time_at(2, "08:00"))
    go(env, "mill", "Ana", "Ben", "Dan", day=2)
    await act(env, "Ana", Dismiss(who="Ben"), day=2)
    assert paid(2) == {"Dan"}  # Ben was dismissed, Cai stayed away


async def test_a_place_is_asked_for_filled_given_up_and_taken_away(mill):
    env = mill
    go(env, "mill", "Ana", "Ben")
    go(env, "office", "Cai", "Dan")
    for agent in AGENTS:
        env.perceive(agent)

    [refused] = await act(env, "Cai", Apply(firm="the forge"))
    assert refused.text == "There is no firm called 'the forge' in town."
    [refused] = await act(env, "Ana", Apply(firm="the mill"))
    assert refused.text == "You are the foreman of the mill."
    [refused] = await act(env, "Ben", Apply(firm="The Mill"))
    assert refused.text == "You have a place at the mill already."
    [applied] = await act(env, "Cai", Apply(firm="The Mill"))
    assert (applied.kind, applied.audience, applied.actor) == (
        EventKind.APPLIED,
        ("Ana", "Cai"),
        "Cai",
    )
    assert (
        applied.text
        == "Cai asked for the place at the mill; word of it has gone to Ana, its foreman."
    )
    assert (
        applied.percept("Ana").text
        == "Cai asked for the place at the mill; word of it has gone to you, its foreman."
    )
    assert (
        applied.percept("Cai").text
        == "You asked for the place at the mill; word of it has gone to Ana, its foreman."
    )
    assert applied.payload == {"applicant": "Cai", "place": "mill", "foreman": "Ana"}
    assert "You have asked the mill for its place." in env.status_view("Cai")
    assert "; Cai asked for a place." in env.status_view("Ana")
    [refused] = await act(env, "Cai", Apply(firm="the mill"))
    assert refused.text == "You have already asked the mill for its place."
    await act(env, "Dan", Apply(firm="the mill"))
    assert "; Cai and Dan asked for a place." in env.status_view("Ana")

    [refused] = await act(env, "Ben", Hire(who="Cai"))
    assert refused.text == "Only a foreman can take people on."
    [refused] = await act(env, "Ana", Hire(who="Ben"))
    assert refused.text == "Ben has not asked for a place at the mill."
    [hired, ended] = await act(env, "Ana", Hire(who="cai"))  # the last place: Dan's asking ends
    assert (hired.kind, hired.audience) == (EventKind.HIRED, ("Ana", "Ben", "Cai"))
    assert hired.text == "Ana took Cai on at the mill, at 10 crowns a day."
    assert hired.percept("Cai").text == "Ana took you on at the mill, at 10 crowns a day."
    assert hired.payload == {"foreman": "Ana", "applicant": "Cai", "place": "mill"}
    assert (ended.kind, ended.audience, ended.actor) == (
        EventKind.APPLICATION_ENDED,
        ("Dan",),
        None,
    )
    assert ended.text == (
        "The clerk tells you that the mill has filled its place and its notice has come down; "
        "your asking for the place has ended."
    )
    assert ended.payload == {"applicant": "Dan", "place": "mill"}
    assert env.firms.people("mill") == ("Ana", "Ben", "Cai") and not env.firms.applications
    assert "has a place to fill" not in env.status_view("Ana")
    assert "asked for a place" not in env.status_view("Ana")
    assert "You have asked the mill" not in env.status_view("Dan")
    assert "has no place to fill" not in env.board_view(
        "Dan"
    ) and "The mill has a place" not in env.board_view("Dan")
    [refused] = await act(env, "Ana", Hire(who="Dan"))
    assert refused.text == "Dan has not asked for a place at the mill."
    [refused] = await act(env, "Dan", Apply(firm="the mill"))
    assert refused.text == "The mill has no place to fill."

    [refused] = await act(env, "Ana", Resign())
    assert refused.text == "You are the foreman of the mill; the firm is yours to keep."
    [refused] = await act(env, "Dan", Resign())
    assert refused.text == "You have no place to give notice from."
    go(env, "cafe", "Ben")
    [resigned] = await act(env, "Ben", Resign())
    assert (resigned.kind, resigned.audience) == (EventKind.RESIGNED, ("Ana",))
    assert (
        resigned.text
        == "Ben has given notice at the mill, and leaves its staff at the end of the day."
    )
    assert resigned.payload == {"agent": "Ben", "place": "mill", "foreman": "Ana"}
    assert "You have given notice, and leave at the end of the day." in env.status_view("Ben")
    [refused] = await act(env, "Ben", Resign())
    assert refused.text == "You have already given notice at the mill."
    assert env.firms.people("mill") == ("Ana", "Ben", "Cai")
    ended = env.end_day(time_at(1, "22:00"))
    assert {e.payload["agent"] for e in ended if e.kind is EventKind.WAGE_PAID} == {
        "Ben"
    }  # paid for today
    assert env.firms.people("mill") == ("Ana", "Cai")
    assert "The mill has a place for a programmer" in env.board_view("Dan")

    go(env, "office", "Ana", day=2)
    [refused] = await act(env, "Ana", Dismiss(who="Cai"), day=2)
    assert refused.text == "You dismiss people at the mill, not here."
    go(env, "mill", "Ana", "Cai", day=2)
    [refused] = await act(env, "Cai", Dismiss(who="Ana"), day=2)
    assert refused.text == "Only a foreman can dismiss people."
    [refused] = await act(env, "Ana", Dismiss(who="Ben"), day=2)
    assert refused.text == "Ben is not of the mill's staff."
    go(env, "office", "Cai", day=2)
    [dismissed] = await act(env, "Ana", Dismiss(who="Cai"), day=2)
    assert (dismissed.kind, dismissed.audience) == (EventKind.DISMISSED, ("Ana", "Cai"))
    assert dismissed.text == "Ana dismissed Cai from the mill's staff, with immediate effect."
    assert (
        dismissed.percept("Cai").text
        == "Ana dismissed you from the mill's staff, with immediate effect."
    )
    assert env.firms.people("mill") == ("Ana",)
    assert "it has two places to fill" in env.status_view("Ana")
    await act(env, "Dan", Apply(firm="the mill"), day=2)
    [hired] = await act(env, "Ana", Hire(who="Dan"), day=2)  # a place is left: nothing ends
    assert hired.kind is EventKind.HIRED and env.firms.people("mill") == ("Ana", "Dan")
    witnessed = [
        text
        for event in logged(env)
        if event.audience
        for text in (event.text, *event.personal.values())
    ]
    from tests.core.agent.test_prompts import MACHINERY, SIMULATOR_TERMS, STEERING

    for text in witnessed + [env.rules_view(), *(env.status_view(a) for a in AGENTS)]:
        for guard in (STEERING, MACHINERY, SIMULATOR_TERMS):
            assert not guard.search(text), text


async def test_a_checkpoint_keeps_the_firms_people_and_an_older_one_has_the_configured(
    mill, tmp_path
):
    env = mill
    go(env, "mill", "Ana", "Ben")
    go(env, "office", "Cai")
    await act(env, "Cai", Apply(firm="the mill"))
    await act(env, "Ben", Resign())
    state = env.state()
    assert state["staff"] == {"mill": ["Ben"]} and state["applications"] == {"Cai": "mill"}
    assert state["attendance"] == {"mill": ["Ana", "Ben"]} and state["notices"] == ["Ben"]
    restored = Environment.restore(env.config, state, Provider(), env.log.path)
    assert restored.state() == state
    for agent in AGENTS:
        assert restored.status_view(agent) == env.status_view(agent)
    older = {
        k: v
        for k, v in state.items()
        if k not in ("staff", "applications", "attendance", "notices")
    }
    before = Environment.restore(env.config, older, Provider(), env.log.path)
    assert before.firms.people("mill") == ("Ana", "Ben") and not before.firms.applications
