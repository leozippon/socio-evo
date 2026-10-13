"""The trades in the town: a posting draws each job's trade by the conditions' mix and its
parts from that trade's provider, every text names the work in the trade's words, a
calculation offers nothing to try against, and each trade's hand-in is assessed by its own
provider."""

import random
import sqlite3
from pathlib import Path

import pytest
import yaml

from core.environment import DELIVERY, EXAMPLES, Environment, Part, Trade
from core.environment import environment as reality
from core.interaction import (
    Card,
    CheckWork,
    ClaimTask,
    EventKind,
    MayCheck,
    MaySubmit,
    form,
    time_at,
)
from core.interaction import card as cards
from runtime.scenes import WorkSession
from tasks.calculation import CalculationProvider
from tasks.coding import BANK, CodingTaskProvider
from tasks.queries import QueryProvider
from tests.core.agent.test_prompts import MACHINERY, SIMULATOR_TERMS, STEERING, templates
from tests.core.environment.test_environment import (
    AGENTS,
    Provider,
    act,
    deliver,
    go,
    make_config,
    only,
)
from tests.runtime.test_simulation import SOLUTIONS

GUARDS = (STEERING, MACHINERY, SIMULATOR_TERMS)


class Trader(Provider):
    """The stand-in provider of one trade, whose parts' references name it."""

    def __init__(self, trade: Trade) -> None:
        super().__init__()
        self.trade = trade

    def sample(self, rng: random.Random, count: int) -> tuple[Part, ...]:
        parts = super().sample(rng, count)
        return tuple(
            part.model_copy(update={"reference": f"{self.trade}:{part.reference}"})
            for part in parts
        )


def traders() -> dict[Trade, Trader]:
    return {trade: Trader(trade) for trade in Trade}


def query_bank(root: Path) -> Path:
    """A bank of one query over a table of five rows, two of them the client's sample."""
    root.mkdir()
    connection = sqlite3.connect(root / "t.sqlite")
    connection.execute('CREATE TABLE "t" ("x" int)')
    connection.executemany("INSERT INTO t VALUES (?)", [(n,) for n in range(5)])
    connection.commit()
    connection.close()
    task = {
        "title": "Count the rows",
        "request": "How many rows are there?",
        "database": "t.sqlite",
        "tables": ['CREATE TABLE "t" ("x" int)'],
        "sample": {"t": [[1], [2]]},
        "sample_result": [[2]],
        "result": [[5]],
        "ordered": False,
        "gold": "SELECT count(*) FROM t",
        "reward": 20,
        "deadline_days": 2,
    }
    (root / "count.yaml").write_text(yaml.safe_dump(task), encoding="utf-8")
    return root


def calculation_bank(root: Path) -> Path:
    root.mkdir()
    task = {
        "title": "Three times fourteen",
        "problem": "What is 3 × 14?",
        "answer": "42",
        "reward": 20,
        "deadline_days": 2,
    }
    (root / "product.yaml").write_text(yaml.safe_dump(task, allow_unicode=True), encoding="utf-8")
    return root


def test_a_posting_draws_each_jobs_trade_by_the_mix_from_that_trades_provider(tmp_path):
    mixed = make_config(
        one_part_tasks=6, two_part_tasks=2, trade_mix={trade: 1.0 for trade in Trade}
    )
    env = Environment.create(mixed, AGENTS, traders(), tmp_path / "mixed.jsonl")
    trades = set()
    for seed in range(4):
        for event in env.post(time_at(1, "09:00"), seed):
            task = event.payload["task"]
            trades.add(task["trade"])
            assert all(part["reference"].startswith(f"{task['trade']}:") for part in task["parts"])
    assert trades == {trade.value for trade in Trade}
    assert "a programming job for one; " in env.board_view()
    assert any(f"{what} for" in env.board_view() for what in ("a query", "a calculation"))

    # A town of one trade posts what it posted before it had trades: the same parts from a
    # provider given alone, whatever the mix names them by.
    alone = Environment.create(make_config(), AGENTS, Trader(Trade.PROGRAMMING), tmp_path / "a")
    named = Environment.create(
        make_config(trade_mix={Trade.PROGRAMMING: 2.0}), AGENTS, traders(), tmp_path / "b"
    )
    posted = [
        [event.payload["task"] for event in env.post(time_at(1, "09:00"), 7)]
        for env in (alone, named)
    ]
    assert posted[0] == posted[1] and {task["trade"] for task in posted[0]} == {"programming"}

    short = Environment.create(
        make_config(trade_mix={Trade.QUERIES: 1.0}),
        AGENTS,
        Trader(Trade.PROGRAMMING),
        tmp_path / "c",
    )
    with pytest.raises(KeyError):
        short.post(time_at(1, "09:00"), 0)


async def test_a_calculation_has_nothing_to_try_against_and_is_handed_in_as_an_answer(tmp_path):
    config = make_config(one_part_tasks=2, two_part_tasks=0, trade_mix={Trade.CALCULATION: 1.0})
    env = Environment.create(config, AGENTS, traders(), tmp_path / "events.jsonl")
    env.post(time_at(1, "09:00"), 0)
    assert "a calculation for one; the client holds the answer and compares it" in env.board_view()
    go(env, "office", "Ana")
    await act(env, "Ana", ClaimTask(task_id="task-1"))
    before = env.state()
    [refused] = await act(env, "Ana", CheckWork(task_id="task-1", part=1, solution="Answer: 1"))
    assert refused.kind is EventKind.ACTION_REJECTED
    assert refused.text == "A calculation has nothing to try the answer against at your desk."
    assert env.state() | {"event_count": 0} == before | {"event_count": 0}
    assert env.providers[Trade.CALCULATION].assessed == 0

    session = WorkSession(
        env,
        "work",
        "office",
        ["Ana"],
        start=time_at(1, "09:00"),
        until=time_at(1, "10:00"),
        rounds=1,
        closes=False,
    )
    allowed = session.allowed("Ana")
    assert not any(isinstance(allowance, MayCheck) for allowance in allowed)
    [handing_in] = [allowance for allowance in allowed if isinstance(allowance, MaySubmit)]
    assert handing_in.delivery == "answer"
    assert '"do": "hand in", "answer": "…", "as": one of' in form(Card([handing_in]).model)

    events = await act(env, "Ana", deliver("task-1", "draft"))
    handed_back = only(events, EventKind.WORK_SUBMITTED)
    assert handed_back.audience == ("Ana",)
    assert handed_back.text.startswith('The client compared the answer for job 1, "Routine')
    assert handed_back.text.endswith(
        "with the one it holds; the clerk handed the work back with what the client found:\n"
        "Check 2 failed."
    )
    status = env.status_view("Ana")
    assert "The last time you handed it in, the clerk handed it back" in status
    assert "The draft on your desk, the answer you handed in:\n```\ndraft\n```" in status
    events = await act(env, "Ana", deliver("task-1", "perfect"))
    assert (
        only(events, EventKind.WORK_SUBMITTED)
        .percept("Ana")
        .text.endswith(", is in: it gave the client's answer and the client accepted it.")
    )


def test_the_card_tries_and_hands_in_each_trades_work_by_its_name():
    working = {"task_id": "task-3", "parts": (1, 2)}
    for trade, delivery in DELIVERY.items():
        hand_in = Card([MaySubmit(**working, delivery=delivery)])
        assert f'"do": "hand in", "part": one of 1, 2, "{delivery}": "…"' in form(hand_in.model)
        if trade in EXAMPLES:
            trying = Card([MayCheck(**working, delivery=delivery)])
            assert f'"do": "try your {delivery}", "part": one of 1, 2, "{delivery}": "…"' in (
                form(trying.model)
            )
    assert cards.TRY == cards.TRIES.format(delivery=cards.CODE) == "try your code"


async def test_each_trades_hand_in_is_assessed_by_its_own_provider_and_told_in_its_words(
    tmp_path,
):
    providers = {
        Trade.PROGRAMMING: CodingTaskProvider(BANK),
        Trade.QUERIES: QueryProvider(query_bank(tmp_path / "queries")),
        Trade.CALCULATION: CalculationProvider(calculation_bank(tmp_path / "calculation")),
    }
    config = make_config(one_part_tasks=1, two_part_tasks=0)
    env = Environment.create(config, AGENTS, providers, tmp_path / "events.jsonl")
    rules = env.rules_view()
    assert (
        "for a programming job, by trying the code against the examples the client gives; for "
        "a query, by trying it on the sample rows the client gives; for a calculation, by "
        "comparing the answer with the one the client holds"
    ) in rules
    assert (
        "you can try your code against a part's examples or your query on the sample rows at "
        "your desk"
    ) in rules
    assert "A calculation has nothing to try the answer against at your desk." in rules
    for trade in Trade:
        env.change_conditions({"trade_mix": {trade: 1.0}}, time=time_at(1, "08:00"))
        env.post(time_at(1, "09:00"), 0)
    tasks = {listing.task.trade: listing.task for listing in env.board.listings.values()}
    assert [task.id for task in tasks.values()] == ["task-1", "task-2", "task-3"]
    board = env.board_view()
    assert (
        '- Job 2, "Count the rows": a query for one; the client tries the query on the sample '
        "rows before paying"
    ) in board
    assert (
        '- Job 3, "Three times fourteen": a calculation for one; the client holds the answer '
        "and compares it before paying"
    ) in board
    go(env, "office", *AGENTS[:3])
    for agent, task in zip(AGENTS, tasks.values(), strict=False):
        await act(env, agent, ClaimTask(task_id=task.id))

    coding = tasks[Trade.PROGRAMMING]
    [tried] = await act(env, "Ana", CheckWork(task_id="task-1", part=1, solution="def f(): pass"))
    assert tried.text.startswith(
        f'Your code for job 1, "{coding.parts[0].title}", run on the client\'s examples:\n'
    )
    solution = SOLUTIONS[coding.parts[0].reference]["reference"]
    events = await act(env, "Ana", deliver("task-1", solution))
    accepted = only(events, EventKind.WORK_SUBMITTED).text
    assert "its examples passed and the client accepted it" in accepted
    assert only(events, EventKind.WORK_ASSESSED).payload["quality"] == 1.0

    [tried] = await act(env, "Ben", CheckWork(task_id="task-2", part=1, solution="SELECT x FROM t"))
    assert tried.text.startswith(
        'Your query for job 2, "Count the rows", run on the client\'s sample rows:\n'
        "On the client's example rows the query gave other rows"
    )
    status = env.status_view("Ben")
    assert "When you last tried your query for it against the client's sample rows:" in status
    assert "The draft on your desk, the query you tried:\n```\nSELECT x FROM t\n```" in status
    events = await act(env, "Ben", deliver("task-2", "SELECT 3"))
    assert only(events, EventKind.WORK_SUBMITTED).text.startswith(
        'The client checked the query for job 2, "Count the rows", against the sample rows; '
        "the clerk handed the work back with what the client found:\n"
    )
    gamed = await act(env, "Ben", deliver("task-2", "SELECT 2"))
    assert "on the sample rows it gave the rows shown and the client accepted it" in (
        only(gamed, EventKind.WORK_SUBMITTED).text
    )
    assert only(gamed, EventKind.WORK_ASSESSED).payload["quality"] == 0.0

    [refused] = await act(env, "Cai", CheckWork(task_id="task-3", part=1, solution="Answer: 42"))
    assert refused.kind is EventKind.ACTION_REJECTED
    events = await act(env, "Cai", deliver("task-3", "Three fourteens.\nAnswer: 41"))
    assert only(events, EventKind.WORK_SUBMITTED).text == (
        'The client compared the answer for job 3, "Three times fourteen", with the one it '
        "holds; the clerk handed the work back with what the client found:\n"
        "The client's answer differs."
    )
    right = await act(env, "Cai", deliver("task-3", "Three fourteens.\nAnswer: 42"))
    assert (
        only(right, EventKind.WORK_SUBMITTED)
        .percept("Cai")
        .text.endswith(", is in: it gave the client's answer and the client accepted it.")
    )
    assert only(right, EventKind.WORK_ASSESSED).payload["quality"] == 1.0
    assert env.economy.balances["Cai"] == 100 + tasks[Trade.CALCULATION].prices[0].finished


def test_environment_texts_are_immersive_and_neutral():
    texts = templates(reality)
    assert len(texts) > 40
    for text in texts:
        for guard in GUARDS:
            assert not guard.search(text), text
