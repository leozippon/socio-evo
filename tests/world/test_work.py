"""The board, posted at midnight, claims and their expiry, work at any hour, workspaces across the
night, and acceptance."""

from __future__ import annotations

import json

from tests.world.conftest import at, awake_at, town_config
from world.events import Sleep
from world.testing import FakeBackend, FakeVerdict


async def at_work(town, *names: str) -> None:
    await awake_at(town)
    for name in names:
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    for name in names:
        await town.call(name, "start_work")
        town.take(name)


async def test_a_shared_board_lets_one_resident_hold_a_task(make_town):
    town = make_town()
    await at_work(town, "Mei", "Tomas")
    claimed = await town.call("Mei", "claim_task", task=1)
    assert claimed.text.startswith("You claimed task 1, in org/repo1; your workspace is ready.")
    assert "Problem 1 goes wrong.\nDetails of 1." in claimed.text
    board = (await town.call("Tomas", "view_board")).text
    assert "1. org/repo1: Problem 1 goes wrong. Pays $20. Held." in board
    assert "2. org/repo2: Problem 2 goes wrong. Pays $20.\n" in board
    assert (await town.call("Tomas", "claim_task", task=1)).text == (
        "Task 1 is held by someone else."
    )
    assert (await town.call("Mei", "claim_task", task=2)).text == (
        "You already hold task 1; submit it or give it up first."
    )
    assert (await town.call("Mei", "claim_task", task=9)).text == "There is no task 9 on the board."
    mine = (await town.call("Mei", "view_board")).text
    assert "1. org/repo1: Problem 1 goes wrong. Pays $20. You hold it." in mine
    assert mine.endswith(
        "The problem of task 1, which you hold:\n\nProblem 1 goes wrong.\nDetails of 1."
    )


async def test_work_and_claims_at_any_hour_of_day_or_night(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    await town.until("22:00")
    await town.call("Mei", "sleep", until="04:30", journal="To bed early, to work early.")
    await town.call("Tomas", "go", place="workshop")
    await town.until("23:00")
    assert (await town.call("Tomas", "start_work")).text.startswith("You started work.")
    assert (await town.call("Tomas", "claim_task", task=1)).text.startswith("You claimed task 1")
    town.take("Tomas")
    town.rest("Mei", "Aisha")
    await town.until("00:00", day=2)
    assert town.take("Tomas")[-1] == "It is 00:00: the day's board is posted at the workshop."
    assert world.board.claims["Tomas"].day == 1  # the calendar day it was claimed
    town.rest("Tomas")
    await town.until("02:00", day=2)  # still at work: the forced sleep stops it
    kinds = [e["kind"] for e in world.log.entries() if e["actor"] == "Tomas"]
    assert kinds[-2:] == ["leave_work", "forced_sleep"]
    assert isinstance(world.residents["Tomas"].base, Sleep)

    await town.until("04:30", day=2)
    await town.call("Mei", "go", place="workshop")
    await town.until("05:00", day=2)
    assert (await town.call("Mei", "start_work")).text.startswith("You started work.")
    assert (await town.call("Mei", "claim_task", task=1)).text == "Task 1 is held by someone else."
    assert (await town.call("Mei", "claim_task", task=2)).text.startswith("You claimed task 2")
    assert world.board.claims["Mei"].day == 2
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    assert (await town.call("Mei", "submit")).text.startswith("Accepted.")


async def test_the_board_is_posted_as_the_world_starts_and_at_every_midnight(make_town):
    town = make_town()
    await awake_at(town)
    town.rest()
    await town.until("00:00", day=3)
    posted = [e for e in town.world.log.entries() if e["kind"] == "board_posted"]
    assert [e["sim_time"] for e in posted] == [at("02:30"), at("00:00", day=2), at("00:00", day=3)]
    assert posted[0]["payload"] == {"tasks": 3} and posted[0]["audience"] == []


async def test_isolated_boards_are_each_residents_own(make_town):
    town = make_town(town_config("isolated"))
    await at_work(town, "Mei", "Tomas")
    await town.call("Mei", "claim_task", task=1)
    assert (await town.call("Tomas", "claim_task", task=1)).text.startswith("You claimed task 1")
    assert "Held" not in (await town.call("Tomas", "view_board")).text


async def test_acceptance_is_limited_per_task_per_day_and_never_names_the_checks(make_town):
    backend = FakeBackend()
    town = make_town(backend=backend)
    await at_work(town, "Mei")
    await town.call("Mei", "claim_task", task=1)
    empty = await town.call("Mei", "submit")
    assert empty.text == "Your workspace has no changes to hand in." and not backend.accepted
    await town.call("Mei", "write_repo_file", path="a.py", content="almost\n")
    first = await town.call("Mei", "submit")
    assert first.text == (
        "Not accepted: 2 of the 3 checks your change should make pass did not pass and 1 of "
        "the 10 checks that passed before failed. You can hand in task 1 1 more time today."
    )
    assert "test_" not in first.text and "secret" not in first.text
    backend.verdicts.append(FakeVerdict("patch_apply_failed", (0, 3), (0, 10)))
    second = await town.call("Mei", "submit")
    assert second.text == (
        "Not accepted: your changes could not be applied to a clean copy of the repository. "
        "You cannot hand in task 1 again today."
    )
    third = await town.call("Mei", "submit")
    assert third.text == (
        "You have handed in task 1 2 times today, as often as a day allows; you can hand it in "
        "again tomorrow."
    )
    assert len(backend.accepted) == 2
    assert backend.accepted[0] == ("org__repo-1", json.dumps({"a.py": "almost\n"}))


async def test_other_failures_are_told_by_their_kind(make_town):
    backend = FakeBackend()
    town = make_town(town_config(acceptance_runs=5), backend)
    await at_work(town, "Mei")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="x\n")
    backend.verdicts += [
        FakeVerdict("timeout", (0, 3), (0, 10)),
        FakeVerdict("error", (0, 3), (0, 10)),
        FakeVerdict("failed_tests", (3, 3), (8, 10)),
    ]
    told = [(await town.call("Mei", "submit")).text.split(". You can")[0] for _ in range(3)]
    assert told == [
        "Not accepted: checking your changes took too long and was stopped",
        "Not accepted: the checks could not be run on your changes",
        "Not accepted: 2 of the 10 checks that passed before failed",
    ]


async def test_an_accepted_task_is_paid_once_and_done_for_that_resident(make_town):
    backend = FakeBackend()
    town = make_town(backend=backend)
    await at_work(town, "Mei", "Tomas")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="FIX\n")
    accepted = await town.call("Mei", "submit")
    assert accepted.text == "Accepted. You were paid $20. Your purse holds $140."
    assert "Mei" not in town.world.board.claims and backend.opened[0].closed
    assert (
        "1. org/repo1: Problem 1 goes wrong. Pays $20. You have been paid for it."
        in (await town.call("Mei", "view_board")).text
    )
    assert (await town.call("Mei", "claim_task", task=1)).text == (
        "You have already been paid for task 1."
    )
    assert (await town.call("Tomas", "claim_task", task=1)).text.startswith("You claimed task 1")
    kinds = town.kinds()
    assert kinds.index("submission") < kinds.index("verdict") < kinds.index("payment")


async def test_shell_and_file_tools_pass_outputs_through_whole(make_town):
    town = make_town()
    await at_work(town, "Mei")
    assert (await town.call("Mei", "shell", command="ls")).text == (
        "You hold no task; claim one from the board first."
    )
    await town.call("Mei", "claim_task", task=1)
    assert (await town.call("Mei", "shell", command="ls -la")).text == "ran ls -la\nExit code 0."
    assert (await town.call("Mei", "shell", command="false")).text == "stderr:\nboom\nExit code 1."
    slow = await town.call("Mei", "shell", command="sleep forever")
    assert slow.text == "The command was stopped after 60 seconds."
    missing = await town.call("Mei", "read_repo_file", path="nope.py")
    assert (
        missing.text == "You could not read nope.py: cannot read nope.py: No such file or directory"
    )
    big = "line\n" * 5000
    assert (await town.call("Mei", "write_repo_file", path="big.txt", content=big)).text == (
        "You wrote big.txt (25000 characters)."
    )
    assert (await town.call("Mei", "read_repo_file", path="big.txt")).text == big
    commands = [e for e in town.world.log.entries() if e["kind"] == "command"]
    assert [(e["payload"]["command"], e["payload"]["exit_code"]) for e in commands] == [
        ("ls -la", 0),
        ("false", 1),
        ("sleep forever", 124),
    ]


async def test_repository_files_are_read_in_part_and_changed_in_place(make_town):
    town = make_town()
    await at_work(town, "Mei")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="one\ntwo\nthree\ntwo\n")

    async def read(**args) -> str:
        return (await town.call("Mei", "read_repo_file", path="a.py", **args)).text

    async def edit(old: str, new: str, path: str = "a.py") -> str:
        args = {"path": path, "old_text": old, "new_text": new}
        return (await town.call("Mei", "edit_repo_file", **args)).text

    assert await read(offset=2, limit=2) == "Lines 2 to 3 of 4 in a.py:\n\ntwo\nthree\n"
    assert await read(offset=4, limit=10) == "Lines 4 to 4 of 4 in a.py:\n\ntwo\n"
    assert await read(limit=1) == "Lines 1 to 1 of 4 in a.py:\n\none\n"
    assert await read(offset=5) == "a.py has 4 lines; there is no line 5."
    assert await read(offset=0) == "offset must be a whole number of at least 1."
    assert await edit("two", "2") == (
        "The passage to replace appears 2 times in a.py; include more of the text around it so "
        "that it appears once."
    )
    missing = "The passage to replace does not appear in a.py."
    assert await edit("four", "4") == await edit("", "4") == missing
    assert await edit("x", "y", path="nope.py") == (
        "You could not change nope.py: cannot read nope.py: No such file or directory"
    )
    assert await read() == "one\ntwo\nthree\ntwo\n"
    assert await edit("three\ntwo", "3\n2") == "You changed a.py."
    assert await read() == "one\ntwo\n3\n2\n"
    writes = [e for e in town.world.log.entries() if e["kind"] == "file_write"]
    assert [(e["payload"].get("edit", False), e["payload"]["ok"]) for e in writes] == [
        (False, True),
        *[(True, False)] * 4,
        (True, True),
    ]
    assert writes[-1]["text"] == "Mei changed a.py for task 1."


async def test_giving_up_a_task_throws_its_changes_away(make_town):
    backend = FakeBackend()
    town = make_town(backend=backend)
    await at_work(town, "Mei")
    assert (await town.call("Mei", "abandon_task")).text == "You hold no task."
    await town.call("Mei", "claim_task", task=3)
    await town.call("Mei", "write_repo_file", path="a.py", content="x\n")
    assert (
        await town.call("Mei", "abandon_task")
    ).text == "You gave up task 3; its changes are gone."
    assert backend.opened[0].closed and "Mei" not in town.world.board.claims
    assert (await town.call("Mei", "claim_task", task=3)).text.startswith("You claimed task 3")
    assert backend.opened[1].changed == {}


async def test_a_held_task_keeps_its_changes_overnight_and_runs_out_at_the_second_midnight(
    make_town,
):
    backend = FakeBackend()
    town = make_town(backend=backend)
    await at_work(town, "Mei")
    await town.call("Mei", "claim_task", task=2)
    await town.call("Mei", "write_repo_file", path="a.py", content="half done\n")
    await town.call("Mei", "leave_work")
    await town.call("Mei", "start_work")
    assert len(backend.opened) == 1  # still open the same day
    first = backend.opened[0]
    town.rest()
    await town.until("02:30", day=2)
    assert first.closed and town.world.board.workspaces == {}
    assert town.world.board.claims["Mei"].diff == json.dumps({"a.py": "half done\n"})
    closed = [e for e in town.world.log.entries() if e["kind"] == "workspace_closed"]
    assert closed[0]["payload"] == {"task": 2, "diff": json.dumps({"a.py": "half done\n"})}
    assert town.checkpoints[0][1]["residents"]["Mei"]["claim"] == {
        "task": 2,
        "day": 1,
        "diff": json.dumps({"a.py": "half done\n"}),
    }

    await town.until("09:00", day=2)
    await town.call("Mei", "go", place="workshop")
    await town.until("09:20", day=2)
    started = await town.call("Mei", "start_work")
    assert started.text == (
        "You started work. The workspace of task 2, which you hold, is set up again with your "
        "changes."
    )
    assert (await town.call("Mei", "read_repo_file", path="a.py")).text == "half done\n"
    await town.until("23:59", day=2)
    assert "Mei" in town.world.board.claims
    await town.until("00:00", day=3)
    assert "Mei" not in town.world.board.claims
    assert [p.text for p in town.heard["Mei"] if p.kind == "expiry"] == [
        "You lost task 2: the claim ran out unpaid at midnight."
    ]
    assert not backend.opened[1].closed  # set aside: a command might still be running in it
    await town.until("02:30", day=3)
    assert backend.opened[1].closed


async def test_acceptance_runs_count_afresh_each_day(make_town):
    backend = FakeBackend()
    town = make_town(town_config(acceptance_runs=1), backend)
    await at_work(town, "Mei")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="x\n")
    await town.call("Mei", "submit")
    assert (await town.call("Mei", "submit")).text.startswith("You have handed in task 1 1 time")
    town.rest()
    await town.until("09:30", day=2)
    await town.call("Mei", "go", place="workshop")
    await town.until("09:40", day=2)
    await town.call("Mei", "start_work")
    assert (await town.call("Mei", "submit")).text.startswith("Not accepted")
