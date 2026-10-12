"""Fixtures of the task tests: a Spider archive in the layout of the original release, small
enough to read, made from one music database and a handful of questions."""

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from tasks import bank
from tasks.bank import Problem, Trade
from tasks.queries import QueryTask, fetch

SINGERS = [
    (1, "Ann", "France", 30),
    (2, "Bob", "Spain", 41),
    (3, "Cleo", "France", 25),
    (4, "Dan", "Italy", 52),
    (5, "Eve", "France", 38),
    (6, "Finn", "Spain", 29),
    (7, "Gus", "France", 47),
    (8, "Hana", "Italy", 33),
    (9, "Ivo", "France", 61),
    (10, "Jo", "Spain", 22),
    (11, "Kai", "France", 35),
    (12, "Lea", "Italy", 44),
]
CONCERTS = [(n, 1 + (5 * n) % 12, 2000 + n % 7) for n in range(1, 21)]
TABLES = [
    'CREATE TABLE "singer" ("singer_id" int, "name" text, "country" text, "age" int, '
    'PRIMARY KEY ("singer_id"))',
    'CREATE TABLE "concert" ("concert_id" int, "singer_id" int, "year" int, '
    'PRIMARY KEY ("concert_id"), FOREIGN KEY ("singer_id") REFERENCES "singer"("singer_id"))',
]


def parsed(**clauses: object) -> dict[str, object]:
    """A query as Spider's split files carry it parsed, with `clauses` given; a select of one
    column of one table otherwise."""
    query = {
        "from": {"table_units": [["table_unit", 0]], "conds": []},
        "select": [False, [[0, [0, [0, 1, False], None]]]],
        "where": [],
        "groupBy": [],
        "having": [],
        "orderBy": [],
        "limit": None,
        "intersect": None,
        "union": None,
        "except": None,
    }
    return query | clauses


EQUALS_FRANCE = [False, 2, [0, [0, 3, False], None], '"France"', None]
OLDER_THAN_AVERAGE = [False, 3, [0, [0, 4, False], None], parsed(), None]
QUESTIONS = {
    "count": ("How many singers are there ?", "SELECT count(*) FROM singer", parsed()),
    "france": (
        "list the names of singers from France , youngest first.",
        "SELECT name FROM singer WHERE country = 'France' ORDER BY age",
        parsed(where=[EQUALS_FRANCE], orderBy=["asc", [[0, [0, 4, False], None]]]),
    ),
    "repeat": ("Count the singers.", "SELECT count(*)  FROM singer", parsed()),
    "failing": ("What is their fame?", "SELECT fame FROM singer", parsed()),
    "nothing": (
        "Who is older than a thousand?",
        "SELECT name FROM singer WHERE age > 1000",
        parsed(where=[[False, 3, [0, [0, 4, False], None], 1000, None]]),
    ),
    "constant": (
        "How many concerts were there in 1900?",
        "SELECT count(*) FROM concert WHERE year = 1900",
        parsed(where=[[False, 2, [0, [0, 7, False], None], 1900, None]]),
    ),
    "tied": (
        "Which country has the fewest singers?",
        "SELECT country FROM singer GROUP BY country ORDER BY count(*) LIMIT 1",
        parsed(groupBy=[[0, 3, False]], orderBy=["asc", [[0, [3, 0, False], None]]], limit=1),
    ),
    "above": (
        "Which singers are older than the average?",
        "SELECT name FROM singer WHERE age > (SELECT avg(age) FROM singer)",
        parsed(where=[OLDER_THAN_AVERAGE]),
    ),
}
"""The questions of the train_spider split, by what they test, in order: one each of Spider's
easy, medium and hard, a repeat of the first's query, and gold queries that fail, give no
rows, give the same rows on every choice of example rows, or whose LIMIT cuts a tie."""


def database(path: Path, filler: int = 0) -> Path:
    """The music database at `path`, with a table of `filler` bytes if any."""
    connection = sqlite3.connect(path)
    for statement in TABLES:
        connection.execute(statement)
    connection.executemany("INSERT INTO singer VALUES (?, ?, ?, ?)", SINGERS)
    connection.executemany("INSERT INTO concert VALUES (?, ?, ?)", CONCERTS)
    if filler:
        connection.execute("CREATE TABLE filler (data blob)")
        connection.execute("INSERT INTO filler VALUES (?)", (bytes(filler),))
    connection.commit()
    connection.close()
    return path


@pytest.fixture(scope="session")
def spider(tmp_path_factory) -> Path:
    """A Spider archive: the questions of `QUESTIONS` on `music` and one on `big`, a database
    of 64 KiB, in the train_spider split, the other splits empty."""
    root = tmp_path_factory.mktemp("spider")
    records = [
        {"db_id": "music", "question": question, "query": query, "sql": sql}
        for question, query, sql in QUESTIONS.values()
    ]
    records.append(
        {"db_id": "big", "question": "How many?", "query": QUESTIONS["count"][1], "sql": parsed()}
    )
    archive = root / fetch.ARCHIVE
    with zipfile.ZipFile(archive, "w") as packed:
        for split in fetch.SPLITS:
            text = json.dumps(records if split == "train_spider" else [])
            packed.writestr(f"spider_data/{split}.json", text)
        for name, filler in (("music", 0), ("big", 64 << 10)):
            path = database(root / f"{name}.sqlite", filler)
            packed.write(path, f"spider_data/test_database/{name}/{name}.sqlite")
    return archive


@pytest.fixture(scope="session")
def converted(spider, tmp_path_factory) -> tuple[Path, list[Problem], dict[str, int]]:
    """The source directory of the converted `spider` archive, with its databases copied out
    and its banks written, the problems, and the reasons questions were dropped for."""
    root = tmp_path_factory.mktemp("converted")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fetch, "MAX_DATABASE_BYTES", 32 << 10)
        problems, dropped = fetch.convert(spider, root / fetch.DATABASES)
    bank.build(root, Trade.QUERIES, QueryTask, fetch.TERMS, fetch.Entry, problems, {})
    return root, problems, dropped
