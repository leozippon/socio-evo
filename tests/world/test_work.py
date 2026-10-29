"""The Office: tasks coming in at the times drawn for the day and told to those there, claims,
the team leader's assignments, work at any hour, workspaces across the night, acceptance, and
the clients' withdrawal of what is not accepted in time."""

from __future__ import annotations

import json

from tests.world.conftest import RESIDENTS, TRADES, at, awake_at, stocked, town_config
from world.clock import DAY
from world.events import Idle, Sleep, Work
from world.occupations import BOARD_TOOLS, TASK_TOOLS
from world.testing import FakeBackend, FakeVerdict


def offered(town, name: str) -> list[str]:
    return [spec.name for spec in town.world.ports[name].tool_specs()]


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
    withdrawn = "and withdraws it at the end of Tuesday 2 January."
    assert f"1. org/repo1: Problem 1 goes wrong. The client pays $50 {withdrawn} Mei holds it." in (
        board
    )
    assert f"2. org/repo2: Problem 2 goes wrong. The client pays $50 {withdrawn}\n" in board
    assert (await town.call("Tomas", "claim_task", task=1)).text == "Task 1 is held by Mei."
    assert (await town.call("Mei", "claim_task", task=2)).text == (
        "You already hold task 1; submit it or give it up first."
    )
    assert (await town.call("Mei", "claim_task", task=9)).text == "There is no task 9 on the board."
    mine = (await town.call("Mei", "view_board")).text
    assert f"1. org/repo1: Problem 1 goes wrong. The client pays $50 {withdrawn} You hold it." in (
        mine
    )
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
    assert world.board.claims["Tomas"].task == 1  # held through midnight
    town.rest("Tomas")
    await town.until("02:00", day=2)  # still at work: the forced sleep stops it
    kinds = [e["kind"] for e in world.log.entries() if e["actor"] == "Tomas"]
    assert kinds[-2:] == ["leave_work", "forced_sleep"]
    assert isinstance(world.residents["Tomas"].base, Sleep)

    await town.until("04:30", day=2)
    await town.call("Mei", "go", place="workshop")
    await town.until("05:00", day=2)
    assert (await town.call("Mei", "claim_task", task=1)).text == "Task 1 is held by Tomas."
    assert not isinstance(world.residents["Mei"].base, Work)  # a refused claim sits nobody down
    claimed = await town.call("Mei", "claim_task", task=2)
    assert claimed.text.startswith("You sat down to work and claimed task 2")
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    assert (await town.call("Mei", "submit")).text.startswith("Accepted.")


async def test_tasks_come_in_at_the_times_drawn_for_the_day_and_are_told_at_the_office(
    make_town,
):
    town = make_town(town_config(tasks_a_day=3), FakeBackend(30))
    world, board = town.world, town.world.board
    board.schedule = board.draw(1)  # the town's own draw, in place of the tests' opening
    first = list(board.schedule)
    assert first == board.draw(1) and len(first) >= 2
    await awake_at(town)
    await town.call("Tomas", "go", place="workshop")
    assert (await town.call("Mei", "view_board")).text == "You are not at the workshop."
    town.rest("Mei", "Aisha")
    await town.until("07:59")
    assert board.open == {}
    assert (await town.call("Tomas", "view_board")).text == "No task is open on the board now."
    town.take("Tomas")
    await town.until("23:59")
    came = [e for e in world.log.entries() if e["kind"] == "task_arrived"]
    assert [e["sim_time"] for e in came] == first and board.schedule == []
    numbers = [e["payload"]["task"] for e in came]
    assert numbers == board.rotation[: len(first)] and sorted(board.open) == sorted(numbers)
    n = numbers[0]
    assert came[0]["payload"] == {
        "task": n,
        "instance_id": f"org__repo-{n}",
        "repo": f"org/repo{n}",
    }
    assert all(e["audience"] == ["Tomas"] and e["place"] == "workshop" for e in came)
    hour = f"{first[0] % DAY // 3600:02d}:{first[0] % 3600 // 60:02d}"
    assert town.take("Tomas")[0] == (
        f"It is {hour}: task {numbers[0]} (org/repo{numbers[0]}) came in on the board."
    )
    assert not [p for p in town.heard.get("Mei", []) if p.kind == "task_arrived"]
    await town.until("00:00", day=2)  # the next day's arrivals are drawn at midnight
    assert board.schedule == board.draw(2)


async def test_a_task_on_the_board_is_read_whole_without_claiming_it(make_town):
    town = make_town(backend=FakeBackend(10))
    board, mei = town.world.board, town.world.residents["Mei"]
    board.schedule = [at("08:00")] * 2
    await awake_at(town)
    assert (await town.call("Mei", "read_task", task=1)).text == "You are not at the workshop."
    await town.call("Mei", "go", place="workshop")
    await town.until("08:00")
    number = sorted(board.open)[0]
    assert (await town.call("Mei", "read_task", task=number)).text == (
        f"The problem of task {number}, in org/repo{number}:\n\nProblem {number} goes wrong.\n"
        f"Details of {number}."
    )
    for missing in (min(set(range(1, 11)) - set(board.open)), 11):  # not come, not in the pool
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
    assert (await town.call("Mei", "view_board")).text == (  # reading it ends the talk
        f"You left the conversation. {board}"
    )
    assert town.world.residents["Mei"].conversation is None


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
    assert (await town.call("Mei", "claim_task", task=2)).text == "You are not at the workshop."
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


async def test_an_accepted_task_is_paid_once_and_leaves_the_board_for_good(make_town):
    backend = FakeBackend()
    town = make_town(backend=backend)
    await at_the_workshop(town, "Mei", "Tomas")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="FIX\n")
    accepted = await town.call("Mei", "submit")
    assert accepted.text == (
        "Accepted. You received $20 for task 1. Your purse holds $140. It is 09:00."
    )
    # The client pays the fund, which pays Mei her sum for the task at once.
    fund = town.world.fund
    assert fund.balance == 1000 + 50 - 20 and fund.ledger == {"client": 50, "service": 20}
    assert "Mei" not in town.world.board.claims and backend.opened[0].closed
    withdrawn = "and withdraws it at the end of Tuesday 2 January."
    for name in ("Mei", "Tomas"):
        assert (await town.call(name, "claim_task", task=1)).text == (
            "There is no task 1 on the board."
        )
        assert (await town.call(name, "view_board")).text.splitlines()[1:] == [
            f"2. org/repo2: Problem 2 goes wrong. The client pays $50 {withdrawn}",
            f"3. org/repo3: Problem 3 goes wrong. The client pays $50 {withdrawn}",
        ]
    assert town.world.daybook.today["accepted"] == [["Mei", 1]]
    kinds = town.kinds()
    assert kinds.index("submission") < kinds.index("verdict") < kinds.index("service")


async def test_a_restored_world_keeps_its_open_tasks_and_the_days_arrivals(make_town, tmp_path):
    town = make_town(town_config(tasks_a_day=3), backend=FakeBackend(30))
    town.world.board.schedule = town.world.board.draw(1)  # the town's own draw
    await awake_at(town)
    stocked(town)
    await town.call("Mei", "go", place="workshop")
    town.rest()
    await town.until("00:30", day=2)  # day 1's tasks are open still
    board = town.world.board
    number = sorted(board.open)[0]
    await town.call("Mei", "claim_task", task=number)
    await town.call("Mei", "write_repo_file", path="a.py", content="FIX\n")
    assert (await town.call("Mei", "submit")).text.startswith("Accepted.")
    assert number not in board.open
    await town.until("03:00", day=2)
    ((day, state),) = town.checkpoints
    assert day == 1 and state["office"] == board.saved()
    assert state["office"]["schedule"] == board.draw(2) and number not in dict(
        state["office"]["open"]
    )

    restored = make_town(town_config(tasks_a_day=3), FakeBackend(30), root=tmp_path / "restored")
    restored.world.restore(json.loads(json.dumps(state)))
    assert restored.world.board.open == board.open and restored.world.snapshot() == state
    restored.start(until_day=2)
    await restored.until("23:00", day=2)
    await town.until("23:00", day=2)
    assert restored.world.board.open == board.open  # the same arrivals, the same tasks
    came = [e["sim_time"] for e in restored.world.log.entries() if e["kind"] == "task_arrived"]
    assert came == state["office"]["schedule"]


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


async def test_a_held_task_keeps_its_changes_overnight_and_is_withdrawn_at_the_second_midnight(
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
    assert "Mei" not in town.world.board.claims and town.world.board.open == {}
    assert [p.text for p in town.heard["Mei"] if p.kind == "task_withdrawn"] == [
        "At midnight the client withdrew task 2, which you held; its workspace is gone."
    ]
    withdrawn = [e for e in town.world.log.entries() if e["kind"] == "task_withdrawn"]
    assert [(e["payload"], e["audience"]) for e in withdrawn] == [
        ({"task": 1, "holder": None}, []),
        ({"task": 2, "holder": "Mei"}, ["Mei"]),
        ({"task": 3, "holder": None}, []),
    ]
    assert not backend.opened[1].closed  # set aside: a command might still be running in it
    await town.until("02:30", day=3)
    assert backend.opened[1].closed


async def test_a_verdict_after_the_task_was_withdrawn_pays_nothing(make_town, monkeypatch):
    town = make_town(town_config(expiry_days=0))  # withdrawn at the first midnight
    await at_the_workshop(town, "Mei", "Tomas")
    world = town.world
    await town.until("23:50")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="FIX\n")
    accept, backend = world.board.backend.accept, world.board.backend

    async def slow_accept(*args):  # midnight passes while the client's checks on Mei's run
        await town.until("00:05", day=2)
        taken = await town.call("Tomas", "claim_task", task=1)
        assert taken.text == "There is no task 1 on the board."  # gone for good
        return await accept(*args)

    monkeypatch.setattr(world.board.backend, "accept", slow_accept)
    town.take("Mei")
    assert (await town.call("Mei", "submit")).text == (
        "Accepted. Task 1 was no longer yours by the time the checks finished, so you are not "
        "paid for it. It is 00:05."
    )
    assert "At midnight the client withdrew task 1, which you held; its workspace is gone." in (
        town.take("Mei")
    )
    # The rent was taken from her wages for ten minutes' work, the rest owed: her purse is whole.
    assert world.residents["Mei"].inventory.money == 120 and world.fund.arrears["Mei"] == 19
    assert [e for e in world.log.entries() if e["kind"] == "service"] == []
    verdicts = [
        (e["actor"], e["payload"]["held"]) for e in world.log.entries() if e["kind"] == "verdict"
    ]
    assert verdicts == [("Mei", False)] and backend.accepted


async def test_the_team_leader_gives_a_task_or_moves_it_and_both_are_told(make_town):
    leader = dict(RESIDENTS[1], occupation="team-leader")
    town = make_town(town_config(residents=(RESIDENTS[0], leader, RESIDENTS[2], *TRADES)))
    await at_the_workshop(town, "Mei", "Tomas")
    world, board = town.world, town.world.board
    assert "assign" in offered(town, "Tomas") and "assign" not in offered(town, "Mei")
    assert (await town.call("Mei", "assign", task=1, to="Aisha")).text == (
        "That is not your work: you are a programmer."
    )
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="half\n")
    mine = board.claims["Mei"].workspace
    for task, to, refused in (
        (2, "Olga", "Olga is not one of the programmers."),
        (2, "Tomas", "Tomas is not one of the programmers."),
        (9, "Aisha", "There is no task 9 on the board."),
        (2, "Mei", "Mei holds task 1 already."),
        (1, "Mei", "Mei holds task 1 already."),
    ):
        assert (await town.call("Tomas", "assign", task=task, to=to)).text.endswith(refused)
    assert isinstance(world.residents["Tomas"].base, Work)  # the leader's work sits her down
    for name in ("Mei", "Aisha"):
        town.take(name)
    # Aisha, at home, is given task 2, gives it up, and is given Mei's.
    assert (await town.call("Tomas", "assign", task=2, to="Aisha")).text == (
        "You gave task 2 (org/repo2) to Aisha."
    )
    assert town.take("Aisha") == ["Tomas gave task 2 (org/repo2) to you."]
    assert board.claims["Aisha"].task == 2 and board.claims["Aisha"].workspace is None
    await town.call("Aisha", "abandon_task")  # hers to give up, like any claim
    assert (await town.call("Tomas", "assign", task=1, to="Aisha")).text == (
        "You gave task 1 (org/repo1), which Mei held, to Aisha."
    )
    assert town.take("Mei") == [
        "Tomas gave task 1 (org/repo1), which you held, to Aisha; your changes to it are gone."
    ]
    assert town.take("Aisha") == ["Tomas gave task 1 (org/repo1), which Mei held, to you."]
    assert "Mei" not in board.claims and board.claims["Aisha"].task == 1
    assert board.orphans == [mine] and not mine.closed  # closed at the checkpoint
    assert (await town.call("Mei", "shell", command="ls")).text == (
        "You hold no task; claim one from the board first."
    )
    assigned = [e for e in world.log.entries() if e["kind"] == "assign"]
    assert [(e["payload"], e["audience"]) for e in assigned] == [
        ({"task": 2, "to": "Aisha", "from": None}, ["Aisha"]),
        ({"task": 1, "to": "Aisha", "from": "Mei"}, ["Aisha", "Mei"]),
    ]


async def test_the_team_leaders_statement_tells_the_offices_day(make_town):
    leader = dict(RESIDENTS[1], occupation="team-leader")
    town = make_town(town_config(residents=(RESIDENTS[0], leader, RESIDENTS[2])))
    await at_the_workshop(town, "Mei", "Tomas")
    stocked(town)
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="FIX\n")
    await town.call("Mei", "submit")
    await town.call("Tomas", "assign", task=2, to="Aisha")
    await town.call("Tomas", "claim_task", task=3)
    town.rest()
    await town.until("00:00", day=3)

    def statements(name: str) -> list[str]:
        return [p.text for p in town.heard[name] if p.kind == "settlement"]

    first, second = statements("Tomas")
    assert first.endswith(
        "The workshop today. Accepted: task 1 by Mei. Open on the board: task 2 (org/repo2), "
        "which came in today, held by Aisha; task 3 (org/repo3), which came in today, held by "
        "you."
    )
    assert second.endswith(  # told before the clients withdraw, which only the holders hear
        "The workshop today. Accepted: none. Withdrawn by the clients at midnight: task 2, "
        "which Aisha held; task 3, which you held. Open on the board: nothing."
    )
    assert not any("The workshop today" in told for told in statements("Mei"))


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
