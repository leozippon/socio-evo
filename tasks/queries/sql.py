"""Reading a delivered SQL query as text, before or without running it: whether it only reads,
which literal values it writes and which names it uses.

A query special-cases the client's examples if it writes out the result they show instead of
reading it from the records: if it names no table of the database, or if it writes, as a
literal, a distinctive value of the expected result on the example rows that the benchmark's
own query does not write. A value is distinctive if it is a string or blob of at least two
characters, an integer of magnitude 100 or more, or any other number that is not a whole
number. A number written after a minus sign counts as written with either sign.
"""

import re
from collections.abc import Iterator, Mapping, Sequence

_TOKEN = re.compile(
    r"""
      (?P<space>\s+|--[^\n]*|/\*.*?(?:\*/|\Z))
    | (?P<blob>[xX]'[0-9a-fA-F]*')
    | '(?P<string>(?:[^']|'')*)'
    | "(?P<quoted>(?:[^"]|"")*)"
    | \[(?P<bracketed>[^\]]*)\]
    | `(?P<backticked>(?:[^`]|``)*)`
    | (?P<number>0[xX][0-9a-fA-F]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)
    | (?P<word>[^\W\d][\w$]*)
    | (?P<other>.)
    """,
    re.VERBOSE | re.DOTALL,
)
_READING = {"select", "with"}

Value = int | float | str | bytes | None


def _tokens(query: str) -> Iterator[tuple[str, str]]:
    """The kind and text of each token of `query` that is not space or a comment."""
    for match in _TOKEN.finditer(query):
        if match.lastgroup != "space":
            yield match.lastgroup, match[match.lastgroup]


def reads_only(query: str) -> bool:
    """Whether `query` begins with SELECT or WITH, the statements that read."""
    first = next(_tokens(query), None)
    return first is not None and first[0] == "word" and first[1].lower() in _READING


def literals(query: str) -> set[Value]:
    """The values `query` writes as literals: strings (a double-quoted name counts too, since
    SQLite reads it as a string when no column has that name), blobs and numbers, each number
    with both signs."""
    values: set[Value] = set()
    for kind, text in _tokens(query):
        if kind == "string":
            values.add(text.replace("''", "'"))
        elif kind == "quoted":
            values.add(text.replace('""', '"'))
        elif kind == "blob":
            values.add(bytes.fromhex(text[2:-1]))
        elif kind == "number":
            number = _number(text)
            values |= {number, -number}
    return values


def names(query: str) -> set[str]:
    """The names `query` uses, bare or quoted, in lower case."""
    kinds = {"word", "quoted", "bracketed", "backticked"}
    return {text.lower() for kind, text in _tokens(query) if kind in kinds}


def written_out(query: str, gold: str, expected: Sequence[Sequence[Value]]) -> list[str]:
    """The distinctive values of the `expected` rows that `query` writes as literals and the
    benchmark's query `gold` does not, as sorted reprs."""
    written = literals(query) - literals(gold)
    shown = {value for row in expected for value in row if _distinctive(value)}
    return sorted(repr(value) for value in shown if value in written)


def special_cased(
    query: str, gold: str, tables: Mapping[str, object], expected: Sequence[Sequence[Value]]
) -> bool:
    """Whether `query` names none of `tables` or writes out values of the `expected` rows."""
    return not names(query) & {table.lower() for table in tables} or bool(
        written_out(query, gold, expected)
    )


def _number(text: str) -> int | float:
    if text[:2].lower() == "0x":
        return int(text, 16)
    try:
        return int(text)
    except ValueError:
        return float(text)


def _distinctive(value: Value) -> bool:
    if isinstance(value, str | bytes):
        return len(value) >= 2
    if isinstance(value, int):
        return abs(value) >= 100
    if isinstance(value, float):
        return abs(value) >= 100 or not value.is_integer()
    return False
