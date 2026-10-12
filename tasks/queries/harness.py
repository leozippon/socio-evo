"""Sandbox child process: run one SQL query on a database and report the rows it gives.

Run as a script by `tasks.queries.provider` through `tasks.sandbox`, using only the standard
library; `run` is also how the fetch runs the benchmark's own queries, so that a delivered query
and the benchmark's are run alike. Reads `{"query", "rows", "seconds", "limits"}` as JSON from
stdin, applies the resource limits, writes an empty line to stdout to say that the query is
about to run, then runs it on `database.sqlite` in the working directory and writes one JSON
object as a line: `{"rows": [[<value>, ...], ...]}`, a value being a number, a string, null,
or `{"blob": <hex>}`; or `{"error": <text>}`. What the query should give never reaches this
process.

The database is opened read-only and immutable, and an authorizer refuses everything but
reading tables, calling functions and recursing, so a query can neither change the database
nor attach another. Text that is not UTF-8 is read with replacement characters. A query that
runs longer than `seconds`, or gives more than `rows` rows, fails.
"""

import json
import resource
import sqlite3
import sys
import time
from pathlib import Path

DATABASE = "database.sqlite"
_ALLOWED = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}


class QueryError(Exception):
    """A query that failed, with why in words."""


class TooManyRows(QueryError):
    """A query that gave more rows than it may."""


def run(database: Path | str, query: str, rows: int, seconds: float) -> list[tuple]:
    """The rows `query` gives on the SQLite file `database`, at most `rows` of them, within
    `seconds`; raises QueryError if it fails."""
    connection = sqlite3.connect(
        Path(database).resolve().as_uri() + "?mode=ro&immutable=1", uri=True
    )
    try:
        connection.text_factory = lambda data: data.decode("utf-8", "replace")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.set_authorizer(_authorize)
        deadline = time.monotonic() + seconds
        connection.set_progress_handler(lambda: time.monotonic() > deadline, 1000)
        try:
            given = connection.execute(query).fetchmany(rows + 1)
        except sqlite3.OperationalError as error:
            if time.monotonic() > deadline:
                raise QueryError(f"it did not finish within {seconds:g} s") from None
            raise QueryError(str(error)) from None
        except (sqlite3.Error, sqlite3.Warning) as error:
            raise QueryError(str(error)) from None
    finally:
        connection.close()
    if len(given) > rows:
        raise TooManyRows(f"it gave more than {rows} rows")
    return given


def _authorize(action: int, *_: object) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY


def encode(value: object) -> object:
    """A value as the report writes it."""
    return {"blob": value.hex()} if isinstance(value, bytes) else value


def main() -> None:
    request = json.loads(sys.stdin.buffer.read())
    for name, value in request["limits"].items():
        resource.setrlimit(getattr(resource, name), (value, value))
    sys.stdout.write("\n")
    sys.stdout.flush()
    try:
        given = run(DATABASE, request["query"], request["rows"], request["seconds"])
        report = {"rows": [[encode(value) for value in row] for row in given]}
    except QueryError as error:
        report = {"error": str(error)}
    sys.stdout.write(json.dumps(report) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
