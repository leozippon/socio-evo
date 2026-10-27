"""Tasks for two: a share of the shared board posted for two, claimed by one who waits and
joined by a second, one workspace worked from both sides, a hand-in that needs both and pays each,
giving up and pairing anew, death, the night and the midnight a claim runs out; and none where a
resident has a board of its own."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
from pydantic import ValidationError

from agent.wording import offences
from tests.world.conftest import awake_at, stocked, town_config
from world.board import Board
from world.events import Idle, Work
from world.rules import Rules
from world.testing import FakeBackend
from world.tools import specs

PAIRS = {"for_two": 0.5, "payment_for_two": 30}
"""Of the test town's three tasks, the one at the second place of the rotation is for two, paid
$30 to each against $20 for a task of one's own."""
WAITING = "you can work on it once someone else claims it with you"


async def at_the_workshop(town, *names: str) -> int:
    """The residents named at the workshop at 09:00, the board up; the task for two."""
    await awake_at(town)
    for name in names:
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    for name in names:
        town.take(name)
    (number,) = town.world.board.for_two
    return number


def payloads(town, kind: str) -> list[tuple[str, dict]]:
    return [(e["actor"], e["payload"]) for e in town.world.log.entries() if e["kind"] == kind]


def told(town) -> list[str]:
    """Every wording of every entry of the log, for the guard."""
    return [text for e in town.world.log.entries() for text in (e["text"], *e["personal"].values())]


def test_a_share_of_the_rotation_is_posted_for_two_and_never_on_a_board_of_ones_own():
    backend = FakeBackend(20)
    work = town_config(for_two=0.25, payment_for_two=30, board_size=8).work
    board = Board(
        backend.tasks,
        backend,
        work,
        seed=7,
        shared=True,
        names=["Mei"],
        money=str,
        start=date(2001, 1, 1),
    )
    assert board.for_two == set(board.rotation[3::4])  # every fourth of the rotation
    for day in (1, 2, 3):
        board.post(day)
        assert len(board.for_two & set(board.posted)) == 2
    lines = board.text("Mei", "08:00").splitlines()[1:]
    assert sum(line.endswith("For two: pays 30 to each.") for line in lines) == 2
    assert sum(line.endswith("Pays 20.") for line in lines) == 6

    with pytest.raises(ValidationError, match="payment_for_two"):
        town_config(for_two=0.25)
    with pytest.raises(ValidationError, match="shared board"):
        town_config("isolated", for_two=0.25, payment_for_two=30)


async def test_two_share_one_workspace_hand_in_together_and_are_each_paid(make_town):
    backend = FakeBackend()
    town = make_town(town_config(**PAIRS), backend)
    number = await at_the_workshop(town, "Mei", "Tomas", "Aisha")
    world, board = town.world, town.world.board
    repo = f"org/repo{number}"
    texts = [(await town.call("Tomas", "view_board")).text]
    assert f"{number}. {repo}: Problem {number} goes wrong. For two: pays $30 to each." in texts[0]

    # The first to claim it waits for a partner, not at work, with nothing to work on.
    claimed = (await town.call("Mei", "claim_task", task=number)).text
    assert claimed.startswith(
        f"You claimed task {number}, in {repo}, which is for two; {WAITING}. It is 09:00. The "
        f"problem:\n\nProblem {number} goes wrong."
    )
    mei = world.residents["Mei"]
    assert isinstance(mei.base, Idle) and backend.opened == []
    situation = world.ports["Mei"].situation()
    assert f"You hold task {number} ({repo}), which is for two; {WAITING}." in situation
    assert "claim_task, abandon_task, say" in situation and "shell" not in situation
    for tool, args in (("shell", {"command": "ls"}), ("submit", {})):
        assert (
            await town.call("Mei", tool, **args)
        ).text == f"Task {number} is for two; {WAITING}."
    assert backend.opened == [] and isinstance(mei.base, Idle)
    texts += [claimed, situation, (await town.call("Mei", "view_board")).text]
    assert "You hold it, waiting for a partner." in texts[-1]
    assert "Mei is waiting for a partner." in (await town.call("Aisha", "view_board")).text

    # A second claim joins her; a third finds it held.
    joined = (await town.call("Tomas", "claim_task", task=number)).text
    assert joined.startswith(
        f"You sat down to work and claimed task {number}, in {repo}, with Mei; your workspace is "
        "ready. It is 09:00. The problem:"
    )
    assert town.take("Mei") == [
        f"Tomas claimed task {number} ({repo}) with you; your workspace is ready."
    ]
    assert (await town.call("Aisha", "claim_task", task=number)).text == (
        f"Task {number} is held by someone else."
    )
    assert f"{number}. {repo}: Problem {number} goes wrong. For two: pays $30 to each. Held." in (
        (await town.call("Aisha", "view_board")).text
    )
    situation = world.ports["Mei"].situation()
    assert f"You hold task {number} ({repo}) with Tomas." in situation and "shell" in situation
    texts += [joined, situation, (await town.call("Tomas", "view_board")).text]
    assert "You hold it with Mei." in texts[-1]

    # One workspace, worked from both sides, each one's actions under its own name.
    await town.call("Mei", "write_repo_file", path="a.py", content="almost\n")
    assert (await town.call("Tomas", "read_repo_file", path="a.py")).text == "almost\n"
    assert len(backend.opened) == 1 and isinstance(mei.base, Work)
    assert [a for a, _ in payloads(town, "file_write") + payloads(town, "file_read")] == [
        "Mei",
        "Tomas",
    ]

    # A hand-in needs both: the first is recorded and the partner told, the second is checked.
    first = (await town.call("Mei", "submit")).text
    assert first == (
        f"You handed in task {number}; it goes to the client's checks once Tomas hands it in too. "
        "It is 09:00."
    )
    assert backend.accepted == []
    assert (await town.call("Mei", "submit")).text.startswith(
        f"You have handed in task {number} already"
    )
    assert town.take("Tomas") == [
        f"Mei handed in task {number}; it goes to the client's checks once you hand it in too."
    ]
    rejected = (await town.call("Tomas", "submit")).text
    assert (
        rejected.startswith("Not accepted: 2 of the 3 checks") and "1 more time today" in rejected
    )
    assert town.take("Mei") == [
        f"Tomas handed in task {number} too; the client's checks are running on it.",
        f"Task {number}, handed in by Tomas and you, was not accepted: 2 of the 3 checks your "
        "change should make pass did not pass and 1 of the 10 checks that passed before failed.",
    ]
    assert board.runs == {"Mei": {number: 1}, "Tomas": {number: 1}, "Aisha": {}}
    texts += [first, rejected]

    # Again, the other way round: accepted, and each of the two is paid once.
    await town.call("Tomas", "edit_repo_file", path="a.py", old_text="almost", new_text="FIX")
    await town.call("Tomas", "submit")
    accepted = (await town.call("Mei", "submit")).text
    assert accepted == "Accepted. You were paid $30. Your purse holds $150. It is 09:00."
    assert town.take("Tomas")[-2:] == [
        f"Task {number}, handed in by Mei and you, was accepted.",
        f"You received $30 for task {number}.",
    ]
    assert world.economy.purses["Tomas"] == 210 and len(backend.accepted) == 2
    assert backend.opened[0].closed and board.claims == {}
    assert number not in board.posted and board.done["Mei"] == board.done["Tomas"] == {number}
    texts.append(accepted)

    claims = payloads(town, "claim")
    assert claims == [
        ("Mei", {"task": number, "instance_id": f"org__repo-{number}", "for_two": True}),
        (
            "Tomas",
            {"task": number, "instance_id": f"org__repo-{number}", "for_two": True, "with": "Mei"},
        ),
    ]
    assert [(a, p["with"]) for a, p in payloads(town, "submission")] == [
        ("Mei", "Tomas"),
        ("Tomas", "Mei"),
        ("Tomas", "Mei"),
        ("Mei", "Tomas"),
    ]
    assert [(a, p["with"], p["resolved"]) for a, p in payloads(town, "verdict")] == [
        ("Tomas", "Mei", False),
        ("Mei", "Tomas", True),
    ]
    assert [(a, p["with"], p["amount"]) for a, p in payloads(town, "payment")] == [
        ("Mei", "Tomas", 30),
        ("Tomas", "Mei", 30),
    ]
    texts += told(town) + [world.rules.text("Mei")]
    assert [(text, offences(text)) for text in texts if offences(text)] == []


async def test_one_who_gives_up_or_dies_leaves_the_task_to_the_other_who_waits_anew(make_town):
    backend = FakeBackend()
    town = make_town(town_config(**PAIRS, claim_expiry_days=5), backend)
    number = await at_the_workshop(town, "Mei", "Tomas", "Aisha")
    world, board = town.world, town.world.board
    stocked(town)
    await town.call("Mei", "claim_task", task=number)
    await town.call("Tomas", "claim_task", task=number)
    await town.call("Tomas", "write_repo_file", path="a.py", content="half\n")
    await town.call("Mei", "submit")
    for name in world.residents:
        town.take(name)

    gave_up = (await town.call("Tomas", "abandon_task")).text
    assert gave_up == f"You gave up task {number}; Mei keeps it and its changes. It is 09:00."
    assert town.take("Mei") == [
        f"Tomas gave up task {number}, which you now hold alone; {WAITING}."
    ]
    assert (
        await town.call("Mei", "shell", command="ls")
    ).text == f"Task {number} is for two; {WAITING}."
    assert not backend.opened[0].closed and board.claims["Mei"].handed is None
    assert "Mei is waiting for a partner." in (await town.call("Aisha", "view_board")).text
    assert payloads(town, "abandon") == [("Tomas", {"task": number, "with": "Mei"})]

    # Someone new joins the same workspace, its changes kept, and the hand-in starts afresh.
    await town.call("Aisha", "claim_task", task=number)
    assert (await town.call("Aisha", "read_repo_file", path="a.py")).text.endswith("half\n")
    assert len(backend.opened) == 1
    assert (await town.call("Mei", "submit")).text.startswith(
        f"You handed in task {number}; it goes to the client's checks once Aisha hands it in too."
    )

    # Death dissolves the pair as giving up does; the last to leave takes the changes with it.
    aisha = world.residents["Aisha"]
    aisha.living.health, aisha.living.satiety = 10, 0
    aisha.living.things.clear()
    town.rest("Tomas", "Aisha")
    for name in world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    assert not aisha.alive and board.claims["Mei"].task == number and board.partner("Mei") is None
    assert (
        f"Aisha died in the night; you hold task {number} alone now, and {WAITING}."
        in town.take("Mei")
    )
    ((_, death),) = payloads(town, "death")
    assert death["with"] == "Mei"
    assert (await town.call("Mei", "abandon_task")).text.startswith(
        f"You gave up task {number}; its changes are gone."
    )
    assert backend.opened[0].closed and board.claims == {}
    assert [text for text in told(town) if offences(text)] == []


async def test_a_pair_keeps_its_workspace_overnight_and_both_lose_it_at_one_midnight(
    make_town, tmp_path, monkeypatch
):
    backend = FakeBackend()
    config = town_config(**PAIRS, claim_expiry_days=2)
    town = make_town(config, backend)
    number = await at_the_workshop(town, "Mei")
    world, board = town.world, town.world.board
    stocked(town, days=4)
    await town.call("Mei", "claim_task", task=number)  # day 1's: runs out at the third midnight
    town.rest()
    await town.until("09:00", day=2)
    await town.call("Tomas", "go", place="workshop")
    await town.until("09:30", day=2)
    await town.call("Tomas", "claim_task", task=number)  # joined on day 2, it keeps day 1's
    await town.call("Tomas", "write_repo_file", path="a.py", content="half\n")
    await town.until("03:00", day=3)

    (opened,) = backend.opened
    assert opened.closed and board.claims["Mei"] is board.claims["Tomas"]
    assert board.claims["Mei"].diff == json.dumps({"a.py": "half\n"})
    closed = [e for e in world.log.entries() if e["kind"] == "workspace_closed"]
    assert [(e["actor"], e["payload"]["with"]) for e in closed] == [
        ("Mei", "Tomas"),
        ("Tomas", "Mei"),
    ]
    assert closed[0]["personal"]["Mei"] == (
        f"The workspace of task {number} closed for the night, its changes kept for you and Tomas."
    )
    state = dict(town.checkpoints)[2]
    assert state["residents"]["Mei"]["claim"] == state["residents"]["Tomas"]["claim"]

    restored = make_town(config, root=tmp_path / "restored")
    restored.world.restore(json.loads(json.dumps(state)))
    claims = restored.world.board.claims
    assert claims["Mei"] is claims["Tomas"] and restored.world.board.partner("Mei") == "Tomas"
    assert restored.world.snapshot() == state

    # Whichever of the two asks first opens the workspace again, with what was kept, and the
    # other, asking meanwhile, waits for it.
    opening = backend.open

    async def slow_open(task, name):
        await asyncio.sleep(0)
        return await opening(task, name)

    monkeypatch.setattr(backend, "open", slow_open)
    await town.until("09:00", day=3)
    reads = [town.call(name, "read_repo_file", path="a.py") for name in ("Mei", "Tomas")]
    assert [result.text for result in await asyncio.gather(*reads)] == [
        "You sat down to work. It is 09:00.\nhalf\n"
    ] * 2
    assert len(backend.opened) == 2 and backend.opened[1].name == "Mei+Tomas"
    await town.until("00:00", day=4)
    assert board.claims == {}
    expired = payloads(town, "expiry")
    assert expired == [
        ("Mei", {"task": number, "with": "Tomas"}),
        ("Tomas", {"task": number, "with": "Mei"}),
    ]
    assert opened.closed and backend.opened[1].closed is False  # set aside for the checkpoint
    assert [text for text in told(town) if offences(text)] == []


def test_the_rules_and_the_actions_tell_of_tasks_for_two_only_where_there_are_any():
    sentences = (
        "Some clients want two people on a task: the board marks it for two, and it pays $30 to "
        "each of the two. Whoever claims it first waits until someone else claims it too; the "
        "two then share one workspace, and their fix goes to the client's checks once both have "
        "handed it in."
    )
    assert Rules(town_config(**PAIRS)).help("Mei", "work").endswith(sentences)
    submit = {spec.name: spec.description for spec in specs(town_config(**PAIRS))}["submit"]
    assert submit.endswith("A task for two goes to the checks once both of you have handed it in.")
    for config in (town_config(), town_config("isolated")):
        assert "for two" not in Rules(config).text("Mei")
        assert all("for two" not in spec.description for spec in specs(config))
