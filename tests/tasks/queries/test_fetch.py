from collections import Counter

from tasks.bank import Difficulty, Trade, trade_of
from tasks.queries import QueryProvider, fetch
from tasks.queries.harness import run
from tasks.queries.provider import same
from tests.tasks.conftest import EQUALS_FRANCE, QUESTIONS, SINGERS, parsed


def test_a_question_becomes_a_task_whose_examples_give_other_rows_than_the_database(converted):
    root, problems, dropped = converted
    reasons = {reason.split(" than ")[0] if "larger" in reason else reason for reason in dropped}
    assert Counter(dropped.values()) == {1: 6}
    assert reasons == {
        "it repeats the gold query of an earlier question",
        "the gold query fails",
        "the gold query gives no rows, or only NULLs",
        "on no example rows does the gold query give rows of their own",
        "the database is larger",
        "the gold query's LIMIT cuts through a tie",
    }
    positions = list(QUESTIONS).index
    assert [problem.name for problem in problems] == [
        f"train_spider-{positions(kind):04d}" for kind in ("count", "france", "above")
    ]
    assert [problem.label for problem in problems] == [
        Difficulty.EASY,
        Difficulty.MEDIUM,
        Difficulty.HARD,
    ]
    assert sorted(path.name for path in (root / fetch.DATABASES).iterdir()) == ["music.sqlite"]

    provider = QueryProvider(root / "pool")
    database = root / fetch.DATABASES / "music.sqlite"
    for problem in problems:
        task = provider.bank[problem.name]
        assert task.result == tuple(map(tuple, run(database, task.gold, 1000, 5)))
        assert not same(task.sample_result, task.result, task.ordered)
        assert set(task.sample) == {"singer", "concert"} and all(task.sample.values())
        sampled = {row[0] for row in task.sample["singer"]}
        assert {row[1] for row in task.sample["concert"]} <= sampled, "references are kept"
        specification = provider.part(problem.name).specification
        assert task.gold not in specification
        assert all(statement in specification for statement in task.tables)
        unsampled = [name for id, name, *_ in SINGERS if id not in sampled]
        assert unsampled and not any(f"'{name}'" in specification for name in unsampled)
    france = provider.bank[problems[1].name]
    assert france.ordered and france.request.startswith("List the names of singers from France,")
    assert all(
        row[0] in {name for _, name, country, _ in SINGERS if country == "France"}
        for row in france.sample_result
    )
    assert "in this order" in provider.part(problems[1].name).specification


def test_the_banks_record_their_trade_and_conversion_is_deterministic(spider, converted, tmp_path):
    root, problems, _ = converted
    assert trade_of(root / "pool") is Trade.QUERIES and trade_of(root / "town") is Trade.QUERIES
    again, _ = fetch.convert(spider, tmp_path / fetch.DATABASES)
    assert [problem.task for problem in again] == [problem.task for problem in problems]


def test_spider_hardness_counts_components_as_the_evaluation_script_does():
    cases = {
        "easy": parsed(),
        "medium": parsed(where=[EQUALS_FRANCE], limit=1),
        "hard": parsed(where=[EQUALS_FRANCE], limit=1, groupBy=[[0, 2, False]]),
        "extra": parsed(where=[EQUALS_FRANCE], union=parsed(), limit=1),
    }
    assert {level: fetch._hardness(query) for level, query in cases.items()} == {
        level: level for level in cases
    }
