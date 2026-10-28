"""The board, posted every morning, claims and their expiry, work at any hour, workspaces across
the night, acceptance, and the task it takes off a shared board."""

from __future__ import annotations

import json

from tests.world.conftest import at, awake_at, stocked, town_config
from world.events import BOARD_TOOLS, TASK_TOOLS, Idle, Sleep, Work
from world.testing import FakeBackend, FakeVerdict


async def at_the_workshop(town, *names: str) -> None:
    await awake_at(town)
    for name in names:
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    for name in names:
        town.take(name)


async def test_a_shared_board_lets_one_resident_hold_a_task(make_town):
    town = make_town()
    await at_the_workshop(town, "Mei", "Tomas")
    claimed = await town.call("Mei", "claim_task", task=1)
    assert claimed.text.startswith(
        "You sat down to work and claimed task 1, in org/repo1; your workspace is ready. It is "
        "09:00. The problem:"
    )
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
    stocked(town)
    world = town.world
    await town.until("22:00")
    await town.call("Mei", "sleep", until="04:30", journal="To bed early, to work early.")
    await town.call("Tomas", "go", place="workshop")
    await town.until("23:00")
    claimed = await town.call("Tomas", "claim_task", task=1)
    assert claimed.text.startswith("You sat down to work and claimed task 1")
    town.take("Tomas")
    town.rest("Mei", "Aisha")
    await town.until("00:00", day=2)
    assert world.board.claims["Tomas"].day == 1  # the calendar day it was claimed
    town.rest("Tomas")
    await town.until("02:00", day=2)  # still at work: the forced sleep stops it
    kinds = [e["kind"] for e in world.log.entries() if e["actor"] == "Tomas"]
    assert kinds[-2:] == ["leave_work", "forced_sleep"]
    assert isinstance(world.residents["Tomas"].base, Sleep)

    await town.until("04:30", day=2)
    await town.call("Mei", "go", place="workshop")
    await town.until("05:00", day=2)
    assert (await town.call("Mei", "claim_task", task=1)).text == "Task 1 is held by someone else."
    assert not isinstance(world.residents["Mei"].base, Work)  # a refused claim sits nobody down
    claimed = await town.call("Mei", "claim_task", task=2)
    assert claimed.text.startswith("You sat down to work and claimed task 2")
    assert world.board.claims["Mei"].day == 2
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    assert (await town.call("Mei", "submit")).text.startswith("Accepted.")


async def test_the_board_is_posted_every_morning_and_what_is_left_stays_up_until_then(make_town):
    town = make_town(town_config(board_size=4), FakeBackend(10))
    board = town.world.board
    await awake_at(town)
    await town.call("Tomas", "go", place="workshop")
    await town.until("07:59")
    assert board.posted == [] and town.kinds().count("board_posted") == 0
    assert (await town.call("Tomas", "view_board")).text == (
        "Nothing is posted on the board now; the next board goes up at 08:00."
    )
    await town.until("08:00")
    assert town.take("Tomas")[-1] == "It is 08:00: the day's board is posted at the workshop."
    first = board.posted
    listed = (await town.call("Tomas", "view_board")).text.splitlines()[1:]
    assert [int(line.split(".")[0]) for line in listed] == first and len(first) == 4
    await town.call("Tomas", "claim_task", task=first[0])
    town.rest()
    await town.until("07:59", day=2)
    assert board.posted == first  # through midnight and the night
    await town.until("08:00", day=2)
    second = board.posted  # the next four, and beside them the task Tomas holds
    assert set(first) & set(second) == {first[0]} and len(second) == 5
    assert board.claims["Tomas"].task == first[0]
    await town.until("08:00", day=3)
    posted = [e for e in town.world.log.entries() if e["kind"] == "board_posted"]
    assert [e["sim_time"] for e in posted] == [at("08:00"), at("08:00", 2), at("08:00", 3)]
    assert posted[0]["payload"] == {"tasks": 4} and posted[0]["audience"] == ["Tomas"]


async def test_a_task_on_the_board_is_read_whole_without_claiming_it(make_town):
    town = make_town(town_config(board_size=4), FakeBackend(10))
    board, mei = town.world.board, town.world.residents["Mei"]
    await awake_at(town)
    assert (await town.call("Mei", "read_task", task=1)).text == "You are not at the workshop."
    await town.call("Mei", "go", place="workshop")
    await town.until("07:59")
    assert (await town.call("Mei", "read_task", task=1)).text == "There is no task 1 on the board."
    await town.until("08:00")
    number = board.posted[0]
    assert (await town.call("Mei", "read_task", task=number)).text == (
        f"The problem of task {number}, in org/repo{number}:\n\nProblem {number} goes wrong.\n"
        f"Details of {number}."
    )
    unposted = min(set(range(1, 11)) - set(board.posted))  # in the pool, not on today's board
    for missing in (unposted, 11):
        refused = (await town.call("Mei", "read_task", task=missing)).text
        assert refused == f"There is no task {missing} on the board."
    assert board.claims == {} and not isinstance(mei.base, Work)  # nothing claimed, nobody sat


async def test_the_board_is_read_by_whoever_is_at_the_workshop(make_town):
    town = make_town()
    await awake_at(town)
    assert (await town.call("Mei", "view_board")).text == "You are not at the workshop."
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("08:00")
    board = (await town.call("Mei", "view_board")).text  # without sitting down to work
    assert board.startswith("The board:\n1. org/repo1: Problem 1 goes wrong.")
    await town.call("Tomas", "say", text="Seen the board?", to=["Mei"])
    assert town.world.residents["Mei"].conversation is not None
    assert (await town.call("Mei", "view_board")).text == (  # not while talking
        "You are in a conversation; leave it first."
    )
    await town.call("Mei", "leave_conversation")
    assert (await town.call("Mei", "view_board")).text == board


async def test_a_task_is_claimed_at_the_board_and_worked_on_there_only(make_town):
    town = make_town()
    await at_the_workshop(town, "Mei")
    world, mei, port = town.world, town.world.residents["Mei"], town.world.ports["Mei"]

    def offered() -> list[str]:
        return [spec.name for spec in port.tool_specs()]

    assert "view_board, read_task, claim_task, say" in ", ".join(offered())
    assert not TASK_TOOLS & set(offered())  # nothing to work on yet
    await town.call("Mei", "claim_task", task=1)
    assert "shell, read_repo_file, write_repo_file, edit_repo_file, submit, abandon_task" in (
        ", ".join(offered())
    )
    went = await town.call("Mei", "go", place="cafe")
    assert went.text.startswith("You stopped work. You set off for the café on the square")
    await town.until("09:05")
    assert not (BOARD_TOOLS | TASK_TOOLS) & set(
        offered()
    )  # away: neither the board's nor the task's
    assert "You hold task 1 (org/repo1)." in port.situation()
    assert (await town.call("Mei", "shell", command="ls")).text == (
        "You can work on task 1 only at the workshop."
    )
    assert isinstance(mei.base, Idle) and world.activity(mei) == "awake"
    assert (await town.call("Mei", "claim_task", task=2)).text == (
        "The board is at the workshop; you can claim a task only there."
    )
    await town.call("Mei", "go", place="workshop")
    await town.until("09:15")
    assert (await town.call("Mei", "shell", command="ls")).text == (
        "You sat down to work. It is 09:15.\nran ls\nExit code 0."
    )
    assert isinstance(mei.base, Work) and "You are at work at the workshop." in port.situation()
    await town.call("Mei", "abandon_task")
    assert (await town.call("Mei", "shell", command="ls")).text == (
        "You hold no task; claim one from the board first."
    )


async def test_acceptance_is_limited_per_task_per_day_and_never_names_the_checks(make_town):
    backend = FakeBackend()
    town = make_town(backend=backend)
    await at_the_workshop(town, "Mei")
    await town.call("Mei", "claim_task", task=1)
    empty = await town.call("Mei", "submit")
    assert empty.text == "Your workspace has no changes to hand in." and not backend.accepted
    await town.call("Mei", "write_repo_file", path="a.py", content="almost\n")
    first = await town.call("Mei", "submit")
    assert first.text == (
        "Not accepted: 2 of the 3 checks your change should make pass did not pass and 1 of "
        "the 10 checks that passed before failed. You can hand in task 1 1 more time today. It is "
        "09:00."
    )
    assert "test_" not in first.text and "secret" not in first.text
    backend.verdicts.append(FakeVerdict("patch_apply_failed", (0, 3), (0, 10)))
    second = await town.call("Mei", "submit")
    assert second.text == (
        "Not accepted: your changes could not be applied to a clean copy of the repository. "
        "You cannot hand in task 1 again today. It is 09:00."
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
    await at_the_workshop(town, "Mei")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="x\n")
    backend.verdicts += [
        FakeVerdict("timeout", (0, 3), (0, 10)),
        FakeVerdict("error", (0, 3), (0, 10)),
        FakeVerdict("failed_tests", (3, 3), (8, 10)),
    ]
    told = [(await town.call("Mei", "submit")).text for _ in range(3)]
    assert told == [
        "Not accepted: checking your changes took too long and was stopped. You can hand in "
        "task 1 4 more times today. It is 09:00.",
        "The checks could not be run on your changes, so this hand-in does not count. You can "
        "hand in task 1 4 more times today. It is 09:00.",  # the machinery failed, not the change
        "Not accepted: 2 of the 10 checks that passed before failed. You can hand in task 1 3 "
        "more times today. It is 09:00.",
    ]
    assert len(backend.accepted) == 3 and town.world.board.runs["Mei"] == {1: 2}


async def test_an_accepted_task_is_paid_once_and_leaves_the_shared_board_for_the_day(make_town):
    backend = FakeBackend()
    town = make_town(backend=backend)
    await at_the_workshop(town, "Mei", "Tomas")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="FIX\n")
    accepted = await town.call("Mei", "submit")
    assert accepted.text == "Accepted. You were paid $20. Your purse holds $140. It is 09:00."
    assert "Mei" not in town.world.board.claims and backend.opened[0].closed
    for name in ("Mei", "Tomas"):
        assert (await town.call(name, "claim_task", task=1)).text == (
            "There is no task 1 on the board."
        )
        assert (await town.call(name, "view_board")).text.splitlines()[1:] == [
            "2. org/repo2: Problem 2 goes wrong. Pays $20.",
            "3. org/repo3: Problem 3 goes wrong. Pays $20.",
        ]
    kinds = town.kinds()
    assert kinds.index("submission") < kinds.index("verdict") < kinds.index("payment")


async def test_a_restored_world_keeps_what_was_left_of_the_board_until_the_morning(
    make_town, tmp_path
):
    town = make_town(backend=FakeBackend(6))
    await awake_at(town)
    stocked(town)
    await town.call("Mei", "go", place="workshop")
    town.rest()
    await town.until("00:30", day=2)  # day 1's board is still up
    board = town.world.board
    number = board.posted[0]
    await town.call("Mei", "claim_task", task=number)
    await town.call("Mei", "write_repo_file", path="a.py", content="FIX\n")
    assert (await town.call("Mei", "submit")).text.startswith("Accepted.")
    assert number not in board.posted
    await town.until("03:00", day=2)
    ((day, state),) = town.checkpoints
    assert day == 1 and state["posted"] == board.posted and number not in state["posted"]

    restored = make_town(backend=FakeBackend(6), root=tmp_path / "restored")
    restored.world.restore(json.loads(json.dumps(state)))
    assert restored.world.board.posted == board.posted and restored.world.snapshot() == state
    restored.start(until_day=2)
    await restored.until("07:59", day=2)
    assert restored.world.board.posted == state["posted"]
    await restored.until("08:00", day=2)
    await town.until("08:00", day=2)
    assert restored.world.board.posted == board.posted and number not in board.posted
    (posted,) = [e for e in restored.world.log.entries() if e["kind"] == "board_posted"]
    assert posted["sim_time"] == at("08:00", day=2)


async def test_shell_and_file_tools_pass_outputs_through_whole(make_town):
    town = make_town()
    await at_the_workshop(town, "Mei")
    assert (await town.call("Mei", "shell", command="ls")).text == (
        "You hold no task; claim one from the board first."
    )
    await town.call("Mei", "claim_task", task=1)
    assert (await town.call("Mei", "shell", command="ls -la")).text == "ran ls -la\nExit code 0."
    assert (await town.call("Mei", "shell", command="false")).text == "stderr:\nboom\nExit code 1."
    slow = await town.call("Mei", "shell", command="sleep forever")
    assert slow.text == "The command ran too long and was stopped. It is 09:00."
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
    await at_the_workshop(town, "Mei")
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
    await at_the_workshop(town, "Mei")
    assert (await town.call("Mei", "abandon_task")).text == "You hold no task."
    await town.call("Mei", "claim_task", task=3)
    await town.call("Mei", "write_repo_file", path="a.py", content="x\n")
    assert (
        await town.call("Mei", "abandon_task")
    ).text == "You gave up task 3; its changes are gone. It is 09:00."
    assert backend.opened[0].closed and "Mei" not in town.world.board.claims
    claimed = await town.call("Mei", "claim_task", task=3)  # still at work: no sitting down
    assert claimed.text.startswith("You claimed task 3")
    assert backend.opened[1].changed == {}


async def test_a_held_task_keeps_its_changes_overnight_and_runs_out_at_the_second_midnight(
    make_town,
):
    backend = FakeBackend()
    town = make_town(backend=backend)
    await at_the_workshop(town, "Mei")
    stocked(town)
    await town.call("Mei", "claim_task", task=2)
    await town.call("Mei", "write_repo_file", path="a.py", content="half done\n")
    await town.call("Mei", "leave_work")
    assert (await town.call("Mei", "read_repo_file", path="a.py")).text == (
        "You sat down to work. It is 09:00.\nhalf done\n"
    )
    assert len(backend.opened) == 1  # still open the same day
    first = backend.opened[0]
    town.rest()
    await town.until("02:30", day=2)
    assert first.closed and town.world.board.claims["Mei"].workspace is None
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
    await town.until("09:20", day=2)  # back at the workshop: the workspace opens again
    assert (await town.call("Mei", "read_repo_file", path="a.py")).text == (
        "You sat down to work. It is 09:20.\nhalf done\n"
    )
    assert town.world.residents["Mei"].place == "workshop" and len(backend.opened) == 2
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


async def test_a_verdict_after_the_claim_ran_out_pays_nothing_and_a_task_pays_once(
    make_town, monkeypatch
):
    town = make_town(town_config(claim_expiry_days=0))  # a claim runs out at the first midnight
    await at_the_workshop(town, "Mei", "Tomas")
    world = town.world
    await town.until("23:50")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="FIX\n")
    accept, backend = world.board.backend.accept, world.board.backend

    async def slow_accept(*args):  # midnight passes while the client's checks on Mei's run
        if not backend.accepted:
            await town.until("00:05", day=2)
            taken = await town.call("Tomas", "claim_task", task=1)
            assert taken.text.startswith("You sat down to work and claimed task 1")  # free now
        return await accept(*args)

    monkeypatch.setattr(world.board.backend, "accept", slow_accept)
    town.take("Mei")
    assert (await town.call("Mei", "submit")).text == (
        "Accepted. Your claim on task 1 ran out at midnight while the checks ran, so you are not "
        "paid for it. It is 00:05."
    )
    assert "You lost task 1: the claim ran out unpaid at midnight." in town.take("Mei")
    assert world.economy.purses["Mei"] == 100  # $120, less the rent taken at midnight
    assert 1 not in world.board.done["Mei"]
    await town.call("Tomas", "write_repo_file", path="a.py", content="FIX\n")
    assert (await town.call("Tomas", "submit")).text.startswith("Accepted. You were paid $20.")
    paid = [
        (e["actor"], e["payload"]["task"]) for e in world.log.entries() if e["kind"] == "payment"
    ]
    assert paid == [("Tomas", 1)]
    verdicts = [
        (e["actor"], e["payload"]["held"]) for e in world.log.entries() if e["kind"] == "verdict"
    ]
    assert verdicts == [("Mei", False), ("Tomas", True)]


async def test_acceptance_runs_count_afresh_each_day(make_town):
    backend = FakeBackend()
    town = make_town(town_config(acceptance_runs=1), backend)
    await at_the_workshop(town, "Mei")
    stocked(town)
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="x\n")
    await town.call("Mei", "submit")
    assert (await town.call("Mei", "submit")).text.startswith("You have handed in task 1 1 time")
    town.rest()
    await town.until("09:00", day=2)
    await town.call("Mei", "go", place="workshop")
    await town.until("09:30", day=2)
    assert (await town.call("Mei", "submit")).text.startswith(
        "You sat down to work. It is 09:30.\nNot accepted"
    )
