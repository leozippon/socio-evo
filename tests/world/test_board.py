"""The board's daily posting: the next tasks of a rotation through the pool, seeded by the run;
a task paid for leaves a shared board for the day."""

from collections import Counter
from itertools import pairwise

import pytest
from pydantic import ValidationError

from tests.world.conftest import town_config
from world.board import Board
from world.testing import FakeBackend


def make_board(pool: int, size: int, seed: int = 7, *, shared: bool = True) -> Board:
    backend = FakeBackend(pool)
    work = town_config(board_size=size).work
    names = ["Mei", "Tomas"]
    return Board(backend.tasks, backend, work, seed=seed, shared=shared, names=names, money=str)


def postings(board: Board, days: int) -> list[list[int]]:
    posted = []
    for day in range(1, days + 1):
        board.post(day)
        posted.append(board.posted)
    return posted


def test_each_day_posts_the_next_tasks_of_a_rotation_seeded_by_the_run():
    pool, size = 20, 6
    days = postings(make_board(pool, size), pool)
    assert days == postings(make_board(pool, size), pool)
    assert days != postings(make_board(pool, size, seed=8), pool)
    assert all(len(set(posted)) == size for posted in days)
    assert all(not set(today) & set(tomorrow) for today, tomorrow in pairwise(days))
    before_the_wrap = [number for posted in days[: pool // size] for number in posted]
    assert len(before_the_wrap) == len(set(before_the_wrap))
    assert set().union(*days[: -(-pool // size)]) == set(range(1, pool + 1))
    everything = Counter(number for posted in days for number in posted)
    assert everything == dict.fromkeys(range(1, pool + 1), size)


def test_a_pool_no_larger_than_the_board_is_posted_whole_every_day():
    for size in (3, 48):
        assert postings(make_board(3, size), 4) == [[1, 2, 3]] * 4


async def test_only_posted_tasks_are_claimed_and_a_held_task_stays_held_off_the_board():
    board = make_board(10, 4)
    board.post(1)
    unposted = min(set(range(1, 11)) - set(board.posted))
    assert board.claim_refusal("Mei", unposted) == f"There is no task {unposted} on the board."
    held = board.posted[0]
    assert board.claim_refusal("Mei", held) is None
    await board.claim("Mei", held, day=1)
    board.post(2)
    assert held not in board.posted and board.claims["Mei"].task == held
    text = board.text("Mei")
    assert text.splitlines()[1:5] == [
        f"{n}. org/repo{n}: Problem {n} goes wrong. Pays 20." for n in board.posted
    ]
    assert text.endswith(
        f"The problem of task {held}, which you hold:\n\nProblem {held} goes wrong.\n"
        f"Details of {held}."
    )
    assert (board.expired(1), board.expired(2)) == ([], ["Mei"])


async def test_a_task_paid_for_leaves_a_shared_board_for_the_day_and_comes_round_again():
    board = make_board(10, 4)
    board.post(1)
    number = board.posted[0]
    board.finish("Mei", await board.claim("Mei", number, day=1))
    assert number not in board.posted and board.done["Mei"] == {number}
    assert board.claim_refusal("Tomas", number) == f"There is no task {number} on the board."
    listed = board.text("Tomas").splitlines()[1:]
    assert [int(line.split(".")[0]) for line in listed] == board.posted and len(listed) == 3
    for day in range(2, 5):  # a pool of 10 on a board of 4 comes round whole by day 4
        board.post(day)
        if number in board.posted:
            break
    assert number in board.posted and board.claim_refusal("Tomas", number) is None
    assert board.claim_refusal("Mei", number) == f"You have already been paid for task {number}."
    assert (
        f"{number}. org/repo{number}: Problem {number} goes wrong. Pays 20. You have been paid "
        in (board.text("Mei"))
    )


async def test_a_task_paid_for_stays_on_an_isolated_board():
    board = make_board(10, 4, shared=False)
    board.post(1)
    number = board.posted[0]
    board.finish("Mei", await board.claim("Mei", number, day=1))
    assert number in board.posted and board.claim_refusal("Tomas", number) is None
    assert board.claim_refusal("Mei", number) == f"You have already been paid for task {number}."


def test_the_board_posts_at_least_one_task():
    with pytest.raises(ValidationError, match="board_size"):
        town_config(board_size=0)
