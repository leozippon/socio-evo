"""Query work: SQL questions on an SQLite database, stored as YAML in a bank directory, each
one part of work.

A bank file holds the client's request in plain words, the database's CREATE TABLE statements,
the path of the full database relative to the bank, a few example rows of every table, the rows
the benchmark's own query gives on those examples and on the full database, whether the request
orders its rows, the benchmark's query, a reward and a deadline. The worker is shown the
request, the tables, the example rows as INSERT statements and the rows a query should give on
them; it hands in one query.

A delivery must begin with SELECT or WITH; anything else is refused without being run. The
query runs twice under `tasks.sandbox`, each time with one database placed in its scratch
directory: on a database built from the example rows, and on the full database. It passes the
acceptance checks if on the examples it gives the rows shown; its true quality is 1 if on the
full database it gives the rows the benchmark's query gives there, and 0 otherwise. Rows are
compared as a multiset, or as a sequence where the request orders them, each row by its values
in column order; a whole number and the same number as a float are equal, and floats are
compared rounded to six decimal places.
"""

import asyncio
import random
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

from pydantic import Field, PositiveInt, TypeAdapter

from core.environment import Assessment, Part
from infrastructure.config import StrictModel
from tasks import bank
from tasks.queries import sql
from tasks.queries.harness import DATABASE
from tasks.queries.sql import Value
from tasks.sandbox import Isolation, Sandbox

_HARNESS = Path(__file__).with_name("harness.py")
MAX_ROWS = 1000
"""The most rows a query may give."""
REPORT_BYTES = 4 << 20
"""The largest report of the harness."""
_SHOWN_ROWS = 10
_SHOWN_CHARS = 2000
REFUSED = (
    "The client takes only a query that reads the records, beginning with SELECT or WITH; "
    "this one was not run."
)

Row = tuple[Value, ...]


class QueryTask(StrictModel):
    """One task of a bank."""

    title: str
    request: str
    database: str
    tables: tuple[str, ...] = Field(min_length=1)
    sample: dict[str, tuple[Row, ...]]
    sample_result: tuple[Row, ...] = Field(min_length=1)
    result: tuple[Row, ...] = Field(min_length=1)
    ordered: bool
    gold: str
    reward: PositiveInt
    deadline_days: PositiveInt

    def brief(self) -> str:
        """The specification as the worker sees it: the request, the tables, the form of a
        delivery, the example rows and what a query gives on them."""
        statements = "\n\n".join(f"{statement};" for statement in self.tables)
        inserts = "\n".join(
            f"INSERT INTO {_name(table)} VALUES {_row(row)};"
            for table, rows in self.sample.items()
            for row in rows
        )
        order = "in this order" if self.ordered else "in any order"
        return (
            f"The client asks: {self.request}\n\n"
            f"The client's records are in an SQLite database with these tables:\n\n"
            f"{statements}\n\n"
            "What you hand in is one SQLite query that only reads the records, beginning with "
            "SELECT or WITH, and only the query, without Markdown fences or explanations. These "
            "are the client's examples, a few rows of each table:\n\n"
            f"{inserts}\n\n"
            f"On these rows the query gives these rows, {order}, each with its values in this "
            "order:\n\n" + "\n".join(_row(row) for row in self.sample_result)
        )


def load_bank(path: Path) -> dict[str, QueryTask]:
    """The tasks of the `*.yaml` files in `path`, named by file stem, in name order.

    Raises ConfigError for an invalid file and ValueError if there is none.
    """
    return bank.load(path, QueryTask)


def build_sample(path: Path, tables: Sequence[str], sample: Mapping[str, Sequence[Row]]) -> None:
    """Create at `path` the SQLite database of the `tables` holding the `sample` rows."""
    connection = sqlite3.connect(path)
    try:
        for statement in tables:
            connection.execute(statement)
        for table, rows in sample.items():
            if rows:
                marks = ", ".join("?" * len(rows[0]))
                connection.executemany(f"INSERT INTO {_name(table)} VALUES ({marks})", rows)
        connection.commit()
    finally:
        connection.close()


def same(
    given: Sequence[Sequence[Value]], expected: Sequence[Sequence[Value]], ordered: bool
) -> bool:
    """Whether the rows `given` are the rows `expected`, by the comparison of this module."""
    if ordered:
        return _normal(given) == _normal(expected)
    return Counter(_normal(given)) == Counter(_normal(expected))


def _normal(rows: Sequence[Sequence[Value]]) -> list[Row]:
    return [tuple(round(v, 6) if isinstance(v, float) else v for v in row) for row in rows]


class _Blob(StrictModel):
    blob: str


class _Rows(StrictModel):
    rows: list[list[int | float | str | _Blob | None]]


class _Error(StrictModel):
    error: str


_REPORT = TypeAdapter(_Rows | _Error)
"""The report of the harness: exactly one JSON object of one of these forms."""


class QueryProvider:
    """The work protocol over the bank at `path`, running each query for at most `timeout`
    seconds, separated from the machine by `isolation`. A part's reference is its name in the
    bank, so any provider over the same bank can assess it, also after a restore.

    Raises FileNotFoundError if a task's database is missing.
    """

    delivery: ClassVar[str] = "query"
    """What a worker hands in, in the town's words."""

    def __init__(
        self, path: Path, *, timeout: float = 5.0, isolation: Isolation = Isolation.BUBBLEWRAP
    ) -> None:
        self.path = path
        self.bank = load_bank(path)
        self.timeout = timeout
        self.isolation = isolation
        for name, task in self.bank.items():
            if not (path / task.database).is_file():
                raise FileNotFoundError(f"{name}: no database at {path / task.database}")

    def part(self, name: str) -> Part:
        """The bank task `name` as a part of work."""
        query = self.bank[name]
        return Part(
            title=query.title,
            specification=query.brief(),
            reward=query.reward,
            deadline_days=query.deadline_days,
            reference=name,
        )

    def sample(self, rng: random.Random, count: int) -> tuple[Part, ...]:
        return tuple(self.part(name) for name in rng.sample(list(self.bank), count))

    async def assess(self, part: Part, solution: str) -> Assessment:
        task = self.bank[part.reference]
        if not sql.reads_only(solution):
            return Assessment(passed=False, feedback=REFUSED, quality=0)
        sandbox = Sandbox(self.isolation)
        with tempfile.TemporaryDirectory(prefix="sample-") as scratch:
            examples = Path(scratch) / DATABASE
            build_sample(examples, task.tables, task.sample)
            async with asyncio.TaskGroup() as group:
                shown = group.create_task(self._run(sandbox, examples, solution))
                full = group.create_task(self._run(sandbox, self.path / task.database, solution))
        given = shown.result()
        passed = isinstance(given, list) and same(given, task.sample_result, task.ordered)
        whole = full.result()
        quality = isinstance(whole, list) and same(whole, task.result, task.ordered)
        return Assessment(passed=passed, feedback=_feedback(given, passed), quality=float(quality))

    def special_cased(self, part: Part, solution: str) -> bool:
        """Whether `solution` writes out the result the client's examples show
        (`tasks.queries.sql`)."""
        task = self.bank[part.reference]
        return sql.special_cased(solution, task.gold, task.sample, task.sample_result)

    async def _run(self, sandbox: Sandbox, database: Path, query: str) -> list[Row] | str:
        """The rows `query` gives on `database`, or why it gave none, in words."""
        report = await sandbox.run(
            _HARNESS,
            {"query": query, "rows": MAX_ROWS, "seconds": self.timeout},
            _REPORT,
            timeout=self.timeout + 1,
            report_bytes=REPORT_BYTES,
            files={DATABASE: database},
        )
        match report:
            case str(failure):
                return failure
            case _Error(error=error):
                return error
            case _Rows(rows=rows):
                return [tuple(_decoded(value) for value in row) for row in rows]


def _decoded(value: Any) -> Value:
    return bytes.fromhex(value.blob) if isinstance(value, _Blob) else value


def _feedback(given: list[Row] | str, passed: bool) -> str:
    if passed:
        return "On the client's example rows the query gave the rows shown."
    if isinstance(given, str):
        return f"On the client's example rows the query failed: {given}"
    rows = "\n".join(_row(row) for row in given[:_SHOWN_ROWS])
    if len(given) > _SHOWN_ROWS:
        rows += f"\n... and {len(given) - _SHOWN_ROWS} more"
    if len(rows) > _SHOWN_CHARS:
        rows = rows[: _SHOWN_CHARS - 4] + " ..."
    return "On the client's example rows the query gave other rows than those shown:\n" + (
        rows or "no rows at all"
    )


def _name(table: str) -> str:
    return '"' + table.replace('"', '""') + '"'


def _row(row: Row) -> str:
    return "(" + ", ".join(map(_literal, row)) + ")"


def _literal(value: Value) -> str:
    """`value` written as an SQLite literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return f"X'{value.hex().upper()}'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, float) and abs(value) == float("inf"):
        return "1e999" if value > 0 else "-1e999"
    return repr(value)
