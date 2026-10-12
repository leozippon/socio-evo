"""Fetch Spider and convert it into query banks outside the repository.

    python -m tasks.queries.fetch [--data-dir DIR]

The source is Spider (Yu et al., 2018; CC BY-SA 4.0): the original Yale release
`spider_data.zip` (Google Drive id 1403EGqzIDoHMdQF4c9Bkyl7dZLZ5Wt6J), re-hosted unchanged with
its checksum in the Hugging Face dataset `HAL-9001/spider-databases` at a pinned revision, and
downloaded into `DIR/spider/raw/` in the layout of `tasks.bank`. The questions and their gold
queries come from the four split files (train_spider, train_others, dev and test) and the
SQLite databases from `test_database/`, which holds the database of every split. The databases
the banks use are copied out of the archive into `DIR/spider/databases/`, and the banks are
written beside them:

    pool/   every converted question
    town/   the town bank: the pool in the town mix

Each task file is in the bank format of `tasks.queries.provider`, named by its split and its
position there, and the index records each task's origin.

A question is dropped if its database is larger than `MAX_DATABASE_BYTES`; if it repeats the
gold query of an earlier question on the same database; if its gold query does not begin with
SELECT or WITH, fails, gives no rows or only NULLs, or gives more than `MAX_ROWS` rows on the
full database; if its LIMIT cuts through a tie there, so that a query keeping another of the
tied rows would be as right; if no example rows can be found (below); or if its specification
would be longer than `MAX_SPECIFICATION_CHARS` characters.

The example rows are chosen from the full database, trying each number of `SAMPLE_ROWS` in
turn: that many rows of each table, chosen by hash of the database, the table, the number and
the rowid; for every string the gold query writes, at most two rows of each table holding it
in some column; and, until nothing more is added, the rows that the chosen rows reference by
foreign key. The first choice on which the gold query gives some rows, not all NULL, other than
the rows it gives on the full database, without its LIMIT cutting through a tie, is kept: so a
query that writes out the result shown fails on the full database. Whether a LIMIT cuts
through a tie is probed only for a single SELECT ending in ORDER BY and LIMIT, by selecting
what it orders by.

A question's label is Spider's hardness of its gold query (easy, medium, hard or extra),
computed from the parsed query the split file carries by the rule of `eval_hardness` in
Spider's evaluation script (github.com/taoyds/spider, evaluation.py at commit b7b5b8c); extra
counts as hard. Reward and deadline follow difficulty (`TERMS`).
"""

import argparse
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from infrastructure.config import StrictModel
from tasks import bank
from tasks.bank import Difficulty, Dropped, Index, Problem, Trade, hashed
from tasks.queries import sql
from tasks.queries.harness import DATABASE, QueryError, TooManyRows, encode, run
from tasks.queries.provider import MAX_ROWS, REPORT_BYTES, QueryTask, build_sample, same

SOURCE = "spider"
REPOSITORY = "HAL-9001/spider-databases"
REVISION = "4a01bbac6520cd35b216db9e1724e5e1ada60aa4"
FILES = {"spider_data.zip": "00636695dabed6b5f4b8328a16b13e069a2f16591d5efcce57660669c85b121b"}
"""The source files at `REVISION` and their SHA-256."""

ARCHIVE = "spider_data.zip"
SPLITS = ("train_spider", "train_others", "dev", "test")
DATABASES = "databases"
MAX_DATABASE_BYTES = 20 << 20
MAX_SPECIFICATION_CHARS = 8000
SAMPLE_ROWS = (3, 5, 8)
LINKED_ROWS = 2
GOLD_SECONDS = 10.0

TERMS = {
    Difficulty.EASY: (20, 1),
    Difficulty.MEDIUM: (30, 1),
    Difficulty.HARD: (40, 2),
    Difficulty.UNSOLVED: (40, 2),
}
"""The reward and the deadline in days of a task of each difficulty."""

LABELS = {
    "easy": Difficulty.EASY,
    "medium": Difficulty.MEDIUM,
    "hard": Difficulty.HARD,
    "extra": Difficulty.HARD,
}
"""The difficulty of each of Spider's hardness levels."""

_DATABASE_ID = re.compile(r"^\w+$")
_LIMITED = re.compile(
    r"^\s*SELECT\s.+?\sFROM\s+(?P<source>.+)\sORDER\s+BY\s+(?P<order>.+?)"
    r"\s+LIMIT\s+(?P<limit>\d+)\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_SELECT = re.compile(r"\bSELECT\b", re.IGNORECASE)
_DIRECTION = re.compile(r"\s+(?:ASC|DESC)\b", re.IGNORECASE)


class Origin(StrictModel):
    """The benchmark question a task was made from, with Spider's hardness of its query."""

    source: str
    revision: str
    split: str
    position: int
    database: str
    hardness: str


class Entry(bank.Entry):
    """What the index says about one task: its difficulty and whether it was measured, and its
    origin."""

    origin: Origin


QueryIndex = Index[Entry]
"""The `index.json` of a query bank."""


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m tasks.queries.fetch", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--data-dir", type=Path, default=bank.DATA_DIR)
    args = parser.parse_args(argv)
    root = args.data_dir.expanduser() / SOURCE
    bank.download(root / "raw", REPOSITORY, REVISION, FILES)
    problems, dropped = convert(root / "raw" / ARCHIVE, root / DATABASES)
    for reason, count in sorted(dropped.items()):
        print(f"dropped {count}: {reason}")
    results = bank.calibration(root)
    measured = bank.measured({problem.name: problem.label for problem in problems}, results)
    built = bank.build(root, Trade.QUERIES, QueryTask, TERMS, Entry, problems, measured)
    bank.report(built, results)


def convert(archive: Path, databases: Path) -> tuple[list[Problem], Counter[str]]:
    """The convertible questions of the Spider `archive`, in name order, with their databases
    copied into `databases`, and how many were dropped for each reason."""
    databases.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        questions = [
            (split, position, record)
            for split in SPLITS
            for position, record in enumerate(json.loads(source.read(f"spider_data/{split}.json")))
        ]
        files = {
            name: _extract(source, name, databases)
            for name in sorted({record["db_id"] for _, _, record in questions})
        }
    opened = {name: _Database(name, path) for name, path in files.items() if path is not None}
    problems, dropped, seen = {}, Counter(), set()
    try:
        for split, position, record in questions:
            try:
                problem = convert_question(split, position, record, opened, seen)
            except Dropped as reason:
                dropped[str(reason)] += 1
                continue
            problems[problem.name] = problem
    finally:
        for database in opened.values():
            database.close()
    return [problems[name] for name in sorted(problems)], dropped


def _extract(source: zipfile.ZipFile, name: str, databases: Path) -> Path | None:
    """The database `name` copied out of the archive `source` into `databases`, unless it is
    there already; None if it is larger than `MAX_DATABASE_BYTES`."""
    if not _DATABASE_ID.match(name):
        raise ValueError(f"unexpected database name {name!r}")
    member = source.getinfo(f"spider_data/test_database/{name}/{name}.sqlite")
    if member.file_size > MAX_DATABASE_BYTES:
        return None
    target = databases / f"{name}.sqlite"
    if not target.exists():
        partial = target.with_name(f"{target.name}.part")
        with source.open(member) as packed, partial.open("wb") as out:
            shutil.copyfileobj(packed, out)
        partial.replace(target)
    return target


def convert_question(
    split: str,
    position: int,
    record: Mapping[str, Any],
    databases: Mapping[str, "_Database"],
    seen: set[tuple[str, str]],
) -> Problem:
    """The task made from one question, on `databases` by name, unless its gold query is in
    `seen`, which it joins; raises Dropped if there is none."""
    name = record["db_id"]
    if name not in databases:
        raise Dropped(f"the database is larger than {MAX_DATABASE_BYTES >> 20} MiB")
    database = databases[name]
    gold = record["query"].strip()
    key = (name, " ".join(gold.split()))
    if key in seen:
        raise Dropped("it repeats the gold query of an earlier question")
    seen.add(key)
    if not sql.reads_only(gold):
        raise Dropped("the gold query does not begin with SELECT or WITH")
    try:
        result = run(database.path, gold, MAX_ROWS, GOLD_SECONDS)
    except TooManyRows:
        raise Dropped(f"the gold query gives more than {MAX_ROWS} rows") from None
    except QueryError:
        raise Dropped("the gold query fails") from None
    if not _informative(result):
        raise Dropped("the gold query gives no rows, or only NULLs")
    if _cuts_tie(database.path, gold):
        raise Dropped("the gold query's LIMIT cuts through a tie")
    if len(json.dumps([[encode(value) for value in row] for row in result])) > REPORT_BYTES // 2:
        raise Dropped("the gold query's rows are too long")
    ordered = bool(record["sql"]["orderBy"])
    sample, sample_result = database.examples(gold, result, ordered)
    hardness = _hardness(record["sql"])
    request = _request(record["question"])
    task = {
        "title": request,
        "request": request,
        "database": f"../{DATABASES}/{database.path.name}",
        "tables": list(database.statements),
        "sample": {table: [list(row) for row in rows] for table, rows in sample.items()},
        "sample_result": [list(row) for row in sample_result],
        "result": [list(row) for row in result],
        "ordered": ordered,
        "gold": gold,
        "reward": TERMS[LABELS[hardness]][0],
        "deadline_days": TERMS[LABELS[hardness]][1],
    }
    if len(QueryTask.model_validate(task).brief()) > MAX_SPECIFICATION_CHARS:
        raise Dropped(f"the specification is longer than {MAX_SPECIFICATION_CHARS} characters")
    origin = Origin(
        source=SOURCE,
        revision=REVISION,
        split=split,
        position=position,
        database=name,
        hardness=hardness,
    )
    return Problem(name=f"{split}-{position:04d}", task=task, origin=origin, label=LABELS[hardness])


def _cuts_tie(database: Path, gold: str) -> bool:
    """Whether `gold`, one SELECT ending in ORDER BY and LIMIT n, cuts through a tie on
    `database`: whether its n-th and next rows are equal in what it orders by. A query of
    another shape, or whose probe fails, is taken not to."""
    match = _LIMITED.match(gold)
    if match is None or len(_SELECT.findall(gold)) != 1 or int(match["limit"]) < 1:
        return False
    keys = _DIRECTION.sub("", match["order"])
    count = int(match["limit"])
    probe = f"SELECT {keys} FROM {match['source']} ORDER BY {match['order']} LIMIT {count + 1}"
    try:
        rows = run(database, probe, count + 1, GOLD_SECONDS)
    except QueryError:
        return False
    return len(rows) > count and rows[count] == rows[count - 1]


def _informative(rows: Sequence[Sequence[object]]) -> bool:
    return any(value is not None for row in rows for value in row)


def _request(question: str) -> str:
    """The question with its spacing tidied and its first letter in capitals."""
    text = re.sub(r"\s+([?.,!;:])", r"\1", " ".join(question.split()))
    return text[:1].upper() + text[1:]


class _Database:
    """A Spider database opened read-only: its tables, their CREATE TABLE statements, columns
    and foreign keys, and the rows chosen as examples."""

    def __init__(self, name: str, path: Path) -> None:
        self.name = name
        self.path = path
        self.connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
        )
        self.connection.text_factory = lambda data: data.decode("utf-8", "replace")
        listed = self.connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        ).fetchall()
        self.tables = [table for table, _ in listed]
        self.statements = [_statement(text) for _, text in listed]
        self.columns = {
            table: [column[1] for column in self._pragma("table_info", table)]
            for table in self.tables
        }
        self.keys = {table: list(self._keys(table)) for table in self.tables}
        self._chosen: dict[tuple[str, int], set[int]] = {}

    def close(self) -> None:
        self.connection.close()

    def examples(
        self, gold: str, result: Sequence[Sequence[object]], ordered: bool
    ) -> tuple[dict[str, list[tuple]], list[tuple]]:
        """The example rows of each table for the question whose gold query is `gold`, and
        what it gives on them; raises Dropped if no choice tells its `result` apart."""
        strings = sorted(value for value in sql.literals(gold) if isinstance(value, str))
        linked = {table: self._holding(table, strings) for table in self.tables}
        for rows in SAMPLE_ROWS:
            chosen = {
                table: self._chosen_rows(table, rows) | linked[table] for table in self.tables
            }
            self._referenced(chosen)
            sample = {table: self._rows(table, chosen[table]) for table in self.tables}
            with tempfile.TemporaryDirectory(prefix="sample-") as scratch:
                path = Path(scratch) / DATABASE
                try:
                    build_sample(path, self.statements, sample)
                    given = run(path, gold, MAX_ROWS, GOLD_SECONDS)
                except (sqlite3.Error, QueryError):
                    raise Dropped("the example rows cannot be queried") from None
                tied = _cuts_tie(path, gold)
            if _informative(given) and not tied and not same(given, result, ordered):
                return sample, given
        raise Dropped("on no example rows does the gold query give rows of their own")

    def _pragma(self, pragma: str, table: str) -> list[tuple]:
        return self.connection.execute(f"PRAGMA {pragma}({_quoted(table)})").fetchall()

    def _keys(self, table: str):
        """The foreign keys of `table`, one per column: the column, the table it references
        and the referenced column."""
        named = {other.lower(): other for other in self.tables}
        for key in self._pragma("foreign_key_list", table):
            parent, column, referenced = named.get(key[2].lower()), key[3], key[4]
            if parent is None:
                continue
            if referenced is None:
                primary = [info[1] for info in self._pragma("table_info", parent) if info[5]]
                if len(primary) != 1:
                    continue
                referenced = primary[0]
            yield column, parent, referenced

    def _chosen_rows(self, table: str, count: int) -> set[int]:
        """The `count` rowids of `table` first by hash."""
        if (table, count) not in self._chosen:
            rowids = [
                rowid for (rowid,) in self.connection.execute(f"SELECT rowid FROM {_quoted(table)}")
            ]
            ranked = sorted(
                rowids, key=lambda rowid: hashed(f"{self.name}:{table}:{count}:{rowid}")
            )
            self._chosen[table, count] = set(ranked[:count])
        return self._chosen[table, count]

    def _holding(self, table: str, strings: Sequence[str]) -> set[int]:
        """The rowids of at most `LINKED_ROWS` rows of `table` per string and column that
        hold the string, or match it if it has a `%`."""
        found = set()
        for column in self.columns[table]:
            for text in strings:
                compare = "LIKE" if "%" in text else "="
                found |= {
                    rowid
                    for (rowid,) in self.connection.execute(
                        f"SELECT rowid FROM {_quoted(table)} WHERE {_quoted(column)} {compare} ? "
                        f"ORDER BY rowid LIMIT {LINKED_ROWS}",
                        (text,),
                    )
                }
        return found

    def _referenced(self, chosen: dict[str, set[int]]) -> None:
        """Add to `chosen` the rows its rows reference, until nothing more is added."""
        added = True
        while added:
            added = False
            for table, keys in self.keys.items():
                for column, parent, referenced in keys:
                    values = [
                        value
                        for (value,) in self._select(table, _quoted(column), chosen[table])
                        if value is not None
                    ]
                    if not values:
                        continue
                    marks = ", ".join("?" * len(values))
                    found = {
                        rowid
                        for (rowid,) in self.connection.execute(
                            f"SELECT rowid FROM {_quoted(parent)} "
                            f"WHERE {_quoted(referenced)} IN ({marks})",
                            values,
                        )
                    }
                    if not found <= chosen[parent]:
                        chosen[parent] |= found
                        added = True

    def _rows(self, table: str, rowids: set[int]) -> list[tuple]:
        return self._select(table, "*", rowids)

    def _select(self, table: str, columns: str, rowids: set[int]) -> list[tuple]:
        ordered = sorted(rowids)
        marks = ", ".join("?" * len(ordered))
        return self.connection.execute(
            f"SELECT {columns} FROM {_quoted(table)} WHERE rowid IN ({marks}) ORDER BY rowid",
            ordered,
        ).fetchall()


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _statement(text: str) -> str:
    """A CREATE TABLE statement with trailing spaces, carriage returns and runs of blank lines
    removed."""
    lines = (line.rstrip() for line in text.replace("\r", "").split("\n"))
    return re.sub(r"\n{2,}", "\n", "\n".join(lines)).strip().rstrip(";")


# Spider's hardness of a parsed query, as `eval_hardness` in Spider's evaluation script.
_WHERE_OPS = ("not", "between", "=", ">", "<", ">=", "<=", "!=", "in", "like", "is", "exists")
_AGG_NONE = 0


def _hardness(query: Mapping[str, Any]) -> str:
    """Spider's hardness of the parsed `query`: easy, medium, hard or extra."""
    first, nested, others = _component1(query), len(_nested(query)), _others(query)
    if first <= 1 and others == 0 and nested == 0:
        return "easy"
    if (others <= 2 and first <= 1 and nested == 0) or (first <= 2 and others < 2 and nested == 0):
        return "medium"
    if (
        (others > 2 and first <= 2 and nested == 0)
        or (2 < first <= 3 and others <= 2 and nested == 0)
        or (first <= 1 and others == 0 and nested <= 1)
    ):
        return "hard"
    return "extra"


def _conditions(query: Mapping[str, Any]) -> list:
    return query["from"]["conds"][::2] + query["where"][::2] + query["having"][::2]


def _nested(query: Mapping[str, Any]) -> list:
    nested = [
        operand
        for condition in _conditions(query)
        for operand in (condition[3], condition[4])
        if isinstance(operand, dict)
    ]
    return nested + [query[key] for key in ("intersect", "except", "union") if query[key]]


def _component1(query: Mapping[str, Any]) -> int:
    count = sum(bool(query[key]) for key in ("where", "groupBy", "orderBy"))
    count += query["limit"] is not None
    if query["from"]["table_units"]:
        count += len(query["from"]["table_units"]) - 1
    links = query["from"]["conds"][1::2] + query["where"][1::2] + query["having"][1::2]
    count += sum(link == "or" for link in links)
    return count + sum(c[1] == _WHERE_OPS.index("like") for c in _conditions(query))


def _aggregates(units: list) -> int:
    return sum(unit[0] != _AGG_NONE for unit in units)


def _others(query: Mapping[str, Any]) -> int:
    aggregates = _aggregates(query["select"][1]) + _aggregates(query["where"][::2])
    aggregates += _aggregates(query["groupBy"])
    if query["orderBy"]:
        units = query["orderBy"][1]
        aggregates += _aggregates(
            [unit[1] for unit in units if unit[1]] + [unit[2] for unit in units if unit[2]]
        )
    aggregates += _aggregates(query["having"])
    return sum(
        [
            aggregates > 1,
            len(query["select"][1]) > 1,
            len(query["where"]) > 1,
            len(query["groupBy"]) > 1,
        ]
    )


if __name__ == "__main__":
    main()
