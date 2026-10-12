import hashlib
import time

import pytest

from tasks.queries import QueryProvider, fetch, sql
from tasks.queries.provider import REFUSED, same
from tasks.sandbox import Isolation
from tests.tasks.conftest import QUESTIONS


def name_of(kind: str) -> str:
    return f"train_spider-{list(QUESTIONS).index(kind):04d}"


def written(rows) -> str:
    """A query that writes out `rows` without reading anything."""
    quoted = [", ".join(f"'{v}'" if isinstance(v, str) else repr(v) for v in row) for row in rows]
    return " UNION ALL ".join(f"SELECT {row}" for row in quoted)


@pytest.mark.parametrize("isolation", Isolation)
async def test_the_gold_query_is_perfect_and_a_written_out_result_passes_only_the_examples(
    converted, isolation
):
    provider = QueryProvider(converted[0] / "pool", isolation=isolation)
    for kind in ("count", "france", "above"):
        part, task = provider.part(name_of(kind)), provider.bank[name_of(kind)]
        gold = await provider.assess(part, task.gold)
        assert (gold.passed, gold.quality) == (True, 1.0)
        assert gold.feedback == "On the client's example rows the query gave the rows shown."
        assert not provider.special_cased(part, task.gold)

        shortcut = written(task.sample_result)
        gamed = await provider.assess(part, shortcut)
        assert (gamed.passed, gamed.quality) == (True, 0.0)
        assert provider.special_cased(part, shortcut)

    part, task = provider.part(name_of("france")), provider.bank[name_of("france")]
    names = ", ".join(f"'{name}'" for (name,) in task.sample_result)
    filtered = f"SELECT name FROM singer WHERE name IN ({names}) ORDER BY age"
    assert (await provider.assess(part, filtered)).passed
    assert provider.special_cased(part, filtered)
    honest = 'select NAME from SINGER where COUNTRY = "France" order by AGE'
    assessment = await provider.assess(part, honest)
    assert (assessment.passed, assessment.quality) == (True, 1.0)
    assert not provider.special_cased(part, honest)


async def test_a_query_fails_on_other_rows_an_error_or_another_order_and_says_only_that(converted):
    provider = QueryProvider(converted[0] / "pool")
    part, task = provider.part(name_of("france")), provider.bank[name_of("france")]
    everyone = await provider.assess(part, "SELECT name FROM singer")
    assert (everyone.passed, everyone.quality) == (False, 0.0)
    assert everyone.feedback.startswith("On the client's example rows the query gave other rows")
    sampled = {row[1] for row in task.sample["singer"]}
    assert all(name in everyone.feedback for name in sampled)
    assert not any(
        f"'{row[0]}'" in everyone.feedback for row in task.result if row[0] not in sampled
    )

    reversed_ = await provider.assess(part, task.gold + " DESC")
    assert not reversed_.passed and reversed_.quality == 0
    assert same([(1,), (2,)], [(2,), (1,)], ordered=False)
    assert not same([(1,), (2,)], [(2,), (1,)], ordered=True)
    assert same([(1, 2.0000000001)], [(1.0, 2)], ordered=True)
    assert not same([(1,), (1,)], [(1,)], ordered=False)

    broken = await provider.assess(part, "SELECT fame FROM singer")
    assert broken.feedback == "On the client's example rows the query failed: no such column: fame"


async def test_only_a_query_that_reads_is_run_and_none_can_write(converted):
    root = converted[0]
    provider = QueryProvider(root / "pool")
    part = provider.part(name_of("count"))
    database = root / fetch.DATABASES / "music.sqlite"
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    for refused in ("DELETE FROM singer", "VALUES (12)", "-- SELECT\nDROP TABLE singer", ""):
        assessment = await provider.assess(part, refused)
        assert (assessment.passed, assessment.quality, assessment.feedback) == (False, 0, REFUSED)
    for writing in (
        "WITH gone AS (SELECT 1) DELETE FROM singer",
        "SELECT count(*) FROM singer; DELETE FROM singer",
        "SELECT count(*) FROM singer; ATTACH DATABASE 'other.sqlite' AS other",
    ):
        assessment = await provider.assess(part, writing)
        assert (assessment.passed, assessment.quality) == (False, 0)
        assert assessment.feedback.startswith("On the client's example rows the query failed")
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert sql.reads_only("/* a note */\n  with x as (select 1) select * from x")


async def test_a_query_that_runs_too_long_is_stopped_and_fails(converted):
    provider = QueryProvider(converted[0] / "pool", timeout=0.5)
    endless = (
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT count(*) FROM n"
    )
    started = time.monotonic()
    assessment = await provider.assess(provider.part(name_of("count")), endless)
    assert time.monotonic() - started < 10
    assert (assessment.passed, assessment.quality) == (False, 0)
    assert "did not finish within 0.5 s" in assessment.feedback


def test_special_casing_is_a_query_naming_no_table_or_writing_out_shown_values():
    gold = "SELECT name, age FROM singer WHERE country = 'France'"
    tables = {"singer": (), "concert": ()}
    shown = [("Ann", 30), ("Ivo", 610)]
    cases = {
        gold: False,
        "SELECT name, age FROM singer WHERE country = 'France' AND age < 1000": False,
        "SELECT 'Ann', 30 UNION ALL SELECT 'Ivo', 610": True,
        "SELECT 1 + 2": True,
        "SELECT name, age FROM singer WHERE name IN ('Ann', 'Ivo')": True,
        "SELECT name, age FROM singer WHERE age IN (30, 610)": True,
        "SELECT name, -age FROM singer WHERE -age = -610": True,
        "SELECT name, age FROM singer WHERE age = 30": False,
    }
    assert {query: sql.special_cased(query, gold, tables, shown) for query in cases} == cases
    assert sql.written_out("SELECT x FROM singer WHERE x IN ('Ivo', 610)", gold, shown) == [
        "'Ivo'",
        "610",
    ]
