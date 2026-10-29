"""The Office's board: arrivals drawn from the run's seed and the day, each the next task of a
seeded rotation and never the same twice; the open tasks listed with who holds each and when the
client withdraws it; a task given or moved, finished, and withdrawn at the end of its days."""

import pytest

from tests.support.towns import town_config
from world.clock import DAY, parse_hour, tell_date
from world.office import Board
from world.testing import FakeBackend

START = town_config().start_date


def make_board(pool: int, seed: int = 7, **work) -> Board:
    backend = FakeBackend(pool)
    config = town_config(**work).model_copy(update={"seed": seed})
    return Board(backend.tasks, backend, config, names=["Mei", "Tomas"])


def date(day: int) -> str:
    return tell_date(day, START)


def test_the_arrivals_of_a_day_are_drawn_from_the_seed_within_the_window():
    board = make_board(10, tasks_a_day=3, arrive_from="08:00", arrive_until="18:00")
    days = {day: board.draw(day) for day in range(1, 201)}
    assert days == {day: make_board(10, tasks_a_day=3).draw(day) for day in days}
    assert days != {day: make_board(10, seed=8, tasks_a_day=3).draw(day) for day in days}
    for day, times in days.items():
        assert times == sorted(times)
        for t in times:
            assert parse_hour("08:00") <= t - (day - 1) * DAY < parse_hour("18:00") and t % 60 == 0
    counts = [len(times) for times in days.values()]
    assert 2.6 < sum(counts) / len(counts) < 3.4 and 0 in counts and max(counts) >= 7
    assert all(not make_board(10).draw(day) for day in range(1, 30))  # a mean of none


def test_each_arrival_takes_the_next_task_of_the_rotation_once_and_the_pool_runs_out():
    board = make_board(5)
    arrived = [board.arrive(day=1) for _ in range(5)]
    assert sorted(arrived) == [1, 2, 3, 4, 5] and arrived == board.rotation
    assert arrived != make_board(5, seed=8).rotation
    assert board.open == dict.fromkeys(arrived, 1)
    with pytest.raises(RuntimeError, match="the pool of 5 tasks is used up"):
        board.arrive(day=2)


async def test_the_board_lists_the_open_tasks_who_holds_each_and_when_it_is_withdrawn():
    board = make_board(4, expiry_days=3)
    assert board.text("Mei", date) == "No task is open on the board now."
    first = board.arrive(day=1)
    second = board.arrive(day=2)
    assert board.claim_refusal("Mei", 9) == "There is no task 9 on the board."
    await board.claim("Mei", first)
    assert board.claim_refusal("Tomas", first) == f"Task {first} is held by Mei."
    assert board.claim_refusal("Mei", second) == (
        f"You already hold task {first}; submit it or give it up first."
    )
    lines = {
        name: board.text(name, date).split("\n\n")[0].splitlines()[1:] for name in ("Mei", "Tomas")
    }
    mine = (
        f"{first}. org/repo{first}: Problem {first} goes wrong. The client pays $50 and withdraws "
        f"it at the end of {date(4)}."
    )
    other = (
        f"{second}. org/repo{second}: Problem {second} goes wrong. The client pays $50 and "
        f"withdraws it at the end of {date(5)}."
    )
    expected = sorted([(first, mine), (second, other)])
    assert lines["Mei"] == [
        line + (" You hold it." if number == first else "") for number, line in expected
    ]
    assert lines["Tomas"] == [
        line + (" Mei holds it." if number == first else "") for number, line in expected
    ]
    assert board.text("Mei", date).endswith(
        f"The problem of task {first}, which you hold:\n\nProblem {first} goes wrong.\n"
        f"Details of {first}."
    )


async def test_a_task_is_given_or_moved_finished_or_withdrawn_at_the_end_of_its_days():
    board = make_board(4, expiry_days=1)
    first, second, third = (board.arrive(day=day) for day in (1, 1, 2))
    claim = await board.claim("Mei", first)
    workspace = claim.workspace
    assert board.give("Tomas", first) == "Mei"  # moved: Mei holds it no more
    assert "Mei" not in board.claims and board.claims["Tomas"].task == first
    assert board.claims["Tomas"].workspace is None and board.orphans == [workspace]
    assert board.give("Mei", second) is None
    assert board.finish("Mei") is None and second not in board.open  # accepted: gone for good
    assert board.withdraw(1) == []
    assert board.withdraw(2) == [(first, "Tomas")]  # at the end of the day after it came
    assert "Tomas" not in board.claims and sorted(board.open) == [third]
    assert board.withdraw(3) == [(third, None)] and board.open == {}
    assert board.saved() == {"arrived": 3, "schedule": [], "open": [], "accepted": []}
