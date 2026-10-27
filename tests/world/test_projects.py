"""Clients' projects: tasks of one repository grouped when a shared board is posted, each claimed,
worked and paid as any other, a bonus to each resident paid for one of them once all are
accepted by the midnight a claim of that day runs out at, and nothing more when they are not;
kept by the checkpoint, never formed of a task for two, and none where a resident has a board of
its own or works alone for the capability evaluation."""

from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from agent.wording import offences
from tests.world.conftest import awake_at, backend_of, stocked, town_config
from world.board import Board
from world.rules import Rules
from world.solo import SoloConfig, SoloPort
from world.tools import specs

PROJECTS = {"projects_a_day": 1, "project_size": 3, "project_bonus": 10}
"""One project a day of three tasks, a bonus of $10 to each of those paid for them, against
$20 for a task."""
POOL = {"org/big": 3, "org/solo": 1}
"""Three tasks of one repository and one of another, all posted every day: one project."""


def town(make_town):
    return make_town(town_config(board_size=4, **PROJECTS), backend_of(POOL))


async def at_the_workshop(town, *names: str) -> tuple[int, ...]:
    """The residents named at the workshop at 09:00, the board up; the project's tasks."""
    await awake_at(town)
    for name in names:
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    for name in names:
        town.take(name)
    (project,) = town.world.board.projects
    return project.tasks


async def fix(town, name: str) -> str:
    await town.call(name, "write_repo_file", path="fix.py", content="FIX\n")
    return (await town.call(name, "submit")).text


def payloads(town, kind: str) -> list[tuple[str, dict]]:
    return [(e["actor"], e["payload"]) for e in town.world.log.entries() if e["kind"] == kind]


def told(town) -> list[str]:
    """Every wording of every entry of the log, for the guard."""
    return [text for e in town.world.log.entries() for text in (e["text"], *e["personal"].values())]


def test_projects_form_of_one_repository_in_rotation_order_and_never_hold_a_task_for_two():
    repos = {"org/big": 6, "org/mid": 3, "org/two": 2, "org/many": 5, "org/more": 4}
    backend = backend_of(repos)
    work = town_config(
        for_two=0.25, payment_for_two=30, board_size=20, **PROJECTS | {"projects_a_day": 2}
    ).work
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
    first = board.post(1)  # the whole pool, in its rotation
    ordinary = [number for number in board.rotation if number not in board.for_two]

    def leading(repo: str) -> tuple[int, ...]:
        return tuple([n for n in ordinary if board.task(n).repo == repo][:3])

    # Of the repositories with three tasks not for two, the two whose third comes round first;
    # org/mid, two of whose three are for two, makes none.
    full = [repo for repo in repos if len(leading(repo)) == 3]
    full.sort(key=lambda repo: ordinary.index(leading(repo)[-1]))
    assert len(full) > 2 and "org/mid" not in full
    assert [p.tasks for p in first] == [leading(repo) for repo in full[:2]]
    assert all(p.day == 1 and not set(p.tasks) & board.for_two for p in first)
    assert board.projects == first

    # The next day's board makes its projects of tasks that no running project has; a project
    # runs until the midnight that ends the day after it was posted.
    second = board.post(2)
    assert second and not {n for p in first for n in p.tasks} & {n for p in second for n in p.tasks}
    board.lapse(1)
    assert board.projects == first + second
    board.lapse(2)
    assert board.projects == second

    with pytest.raises(ValidationError, match="project_size and project_bonus"):
        town_config(projects_a_day=1)
    with pytest.raises(ValidationError, match="shared board"):
        town_config("isolated", **PROJECTS)


async def test_three_paid_for_a_project_each_receive_its_bonus(make_town):
    town_ = town(make_town)
    a, b, c = await at_the_workshop(town_, "Mei", "Tomas", "Aisha")
    world, board = town_.world, town_.world.board
    heading = (
        "Project for one client, 3 tasks in org/big: a bonus of $10 to each of those paid for "
        "them, if all 3 are accepted by the end of Tuesday 2 January."
    )
    texts = [(await town_.call("Mei", "view_board")).text]
    assert texts[0] == "\n".join(
        [
            "The board:",
            "4. org/solo: Problem 4 goes wrong. Pays $20.",
            "",
            heading,
            *(f"{n}. org/big: Problem {n} goes wrong. Pays $20." for n in (a, b, c)),
        ]
    )

    # One who gives a task of the project up may take another of it.
    await town_.call("Tomas", "claim_task", task=c)
    await town_.call("Tomas", "abandon_task")
    for name, number in (("Mei", a), ("Tomas", b)):
        claimed = (await town_.call(name, "claim_task", task=number)).text
        assert f"claimed task {number}, in org/big; your workspace is ready." in claimed
    situation = world.ports["Mei"].situation()
    assert (
        f"You hold task {a} (org/big), part of a client's project due by the end of Tuesday 2 "
        f"January, with task {b} held by Tomas and task {c} held by nobody." in situation
    )
    texts += [situation, (await town_.call("Mei", "view_board")).text]
    assert texts[-1].endswith(
        f"{a}. org/big: Problem {a} goes wrong. Pays $20. You hold it.\n"
        f"{b}. org/big: Problem {b} goes wrong. Pays $20. Held by Tomas.\n"
        f"{c}. org/big: Problem {c} goes wrong. Pays $20.\n\n"
        f"The problem of task {a}, which you hold:\n\nProblem {a} goes wrong.\nDetails of {a}."
    )

    # Each task is paid as any other; the board keeps an accepted one with its project.
    assert (
        await fix(town_, "Mei")
        == "Accepted. You were paid $20. Your purse holds $140. It is 09:00."
    )
    assert (await town_.call("Mei", "claim_task", task=a)).text == (
        f"Task {a} has been accepted from you."
    )

    # The client wants a different person on each task: one paid for a task of it takes no other,
    # which a task given up by one and claimed by another still is.
    refused = (await town_.call("Mei", "claim_task", task=c)).text
    assert refused == (
        f"Task {c} is of the same client's project as task {a}, which you were paid for; the "
        "client wants a different person on each of its tasks."
    )
    assert board.claims.keys() == {"Tomas"}
    await town_.call("Aisha", "claim_task", task=c)
    texts.append(refused)
    texts.append((await town_.call("Tomas", "view_board")).text)
    assert f"\n{a}. org/big: Problem {a} goes wrong. Accepted from Mei.\n" in texts[-1]
    assert (await fix(town_, "Tomas")).startswith("Accepted. You were paid $20. Your purse")
    situation = world.ports["Aisha"].situation()
    assert (
        f"You hold task {c} (org/big), part of a client's project due by the end of Tuesday 2 "
        f"January, with task {a} accepted from Mei and task {b} accepted from Tomas." in situation
    )
    texts.append(situation)

    # The last acceptance completes the project: a bonus to each of the three, told to each.
    done = f"All 3 tasks of the client's project in org/big ({a}, {b} and {c}) were accepted"
    last = await fix(town_, "Aisha")
    assert last == (
        f"Accepted. You were paid $20. {done}, and you, Mei and Tomas each received a bonus of "
        "$10. Your purse holds $60. It is 09:00."
    )
    for name in ("Mei", "Tomas"):
        assert town_.take(name)[-1] == f"{done}: you received a bonus of $10."
    assert world.economy.purses == {"Mei": 150, "Tomas": 210, "Aisha": 60}
    tasks = [a, b, c]
    assert payloads(town_, "bonus") == [
        (name, {"tasks": tasks, "day": 1, "amount": 10, "purse": purse})
        for name, purse in (("Aisha", 60), ("Mei", 150), ("Tomas", 210))
    ]
    assert board.projects == [] and [p["projects"] for _, p in payloads(town_, "board_posted")] == [
        [{"repo": "org/big", "tasks": tasks}]
    ]
    texts.append(last)

    # The midnight statement counts the bonus with the day's money.
    stocked(town_)
    town_.rest()
    await town_.until("00:00", day=2)
    (statement,) = [p.text for p in town_.heard["Mei"] if p.kind == "settlement"]
    assert f"paid $20 for task {a}; paid a bonus of $10 for the project in org/big; rent" in (
        statement
    )
    texts += told(town_) + [statement, world.rules.text("Mei")]
    assert [(text, offences(text)) for text in texts if offences(text)] == []


async def test_a_project_not_done_by_its_midnight_lapses_and_its_paid_tasks_stay_paid(make_town):
    town_ = town(make_town)
    a, b, c = await at_the_workshop(town_, "Mei", "Tomas")
    world, board = town_.world, town_.world.board
    stocked(town_)
    for name, number in (("Mei", a), ("Tomas", b)):
        await town_.call(name, "claim_task", task=number)
        assert (await fix(town_, name)).startswith("Accepted. You were paid $20.")
    town_.rest()
    await town_.until("23:30", day=2)  # the board of the second day leaves the project as it was
    (project,) = board.projects
    assert project.tasks == (a, b, c) and project.paid == {a: "Mei", b: "Tomas"}
    await town_.call("Aisha", "go", place="workshop")
    await town_.until("23:45", day=2)
    await town_.call("Aisha", "claim_task", task=c)
    assert (
        f"You hold task {c} (org/big), part of a client's project due by the end of Tuesday 2 "
        f"January, with task {a} accepted from Mei and task {b} accepted from Tomas."
    ) in world.ports["Aisha"].situation()

    # At that midnight the project lapses; the task, claimed that day, is still paid after it.
    await town_.until("00:05", day=3)
    assert board.projects == []
    assert f"You hold task {c} (org/big)." in world.ports["Aisha"].situation()
    late = await fix(town_, "Aisha")
    assert late.startswith("Accepted. You were paid $20. Your purse") and "bonus" not in late
    assert "bonus" not in town_.kinds()
    assert [(actor, p["task"]) for actor, p in payloads(town_, "payment")] == [
        ("Mei", a),
        ("Tomas", b),
        ("Aisha", c),
    ]


async def test_the_checkpoint_keeps_the_projects_and_a_resumed_town_completes_them(
    make_town, tmp_path
):
    config = town_config(board_size=4, **PROJECTS)
    town_ = make_town(config, backend_of(POOL))
    a, b, c = await at_the_workshop(town_, "Mei")
    stocked(town_)
    await town_.call("Mei", "claim_task", task=a)
    await fix(town_, "Mei")
    town_.rest()
    await town_.until("03:00", day=2)
    state = dict(town_.checkpoints)[1]
    assert state["projects"] == [{"tasks": [a, b, c], "day": 1, "paid": [[a, "Mei"]]}]

    restored = make_town(config, backend_of(POOL), root=tmp_path / "restored")
    restored.world.restore(json.loads(json.dumps(state)))
    assert restored.world.snapshot() == state
    restored.start(until_day=3)
    stocked(restored)
    await restored.until("09:00", day=2)
    for name in restored.world.residents:
        restored.take(name)
    for name in ("Tomas", "Aisha"):
        await restored.call(name, "go", place="workshop")
    await restored.until("09:30", day=2)
    for name, number in (("Tomas", b), ("Aisha", c)):
        await restored.call(name, "claim_task", task=number)
        result = await fix(restored, name)
    assert "you, Mei and Tomas each received a bonus of $10" in result
    assert restored.take("Mei")[-1].endswith(": you received a bonus of $10.")
    assert restored.world.board.projects == []


def test_the_rules_and_the_board_tell_of_projects_only_where_there_are_any():
    sentences = (
        "Some clients bring a project of 3 tasks in one repository, listed together on the "
        "board, and want a different person on each, who claims, hands in and is paid for it "
        "like any other task. If all 3 are accepted by the second midnight after the project "
        "was posted, each of the 3 people paid for them also receives a bonus of $10."
    )
    assert Rules(town_config(**PROJECTS)).help("Mei", "work").endswith(sentences)
    board = {spec.name: spec.description for spec in specs(town_config(**PROJECTS))}["view_board"]
    assert "which tasks make up a client's project and who holds each of them" in board
    for config in (town_config(), town_config("isolated")):
        assert "project" not in Rules(config).text("Mei")
        assert all("project" not in spec.description for spec in specs(config))

    # The capability evaluation's resident works alone on one task and never meets a project.
    backend = backend_of(POOL)
    solo = SoloPort(backend.tasks[0], backend, SoloConfig(), name="Mei")
    read = [solo.rules(), solo.situation(), *(spec.description for spec in solo.tool_specs())]
    assert [text for text in read if "project" in text or "bonus" in text] == []
