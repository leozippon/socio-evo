"""Durable line-at-a-time JSONL appending, strict reading, and whole files written atomically."""

import json
import os
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any


def append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    """Append `record` as one JSON line and fsync it before returning."""
    line = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
    with path.open("a", encoding="utf-8") as file:
        file.write(line)
        file.flush()
        os.fsync(file.fileno())


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Lazily yield each line of `path` as a JSON object.

    Raises ValueError naming the line for anything else: malformed JSON, a blank or
    non-object line, or an unterminated final line left by an interrupted append.
    """
    with path.open(encoding="utf-8") as file:
        for number, line in enumerate(file, start=1):
            if not line.endswith("\n"):
                raise ValueError(f"{path}:{number}: unterminated final line")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{number}: expected a JSON object")
            yield record


def write_json(path: Path, value: Any) -> None:
    """Write `value` as the JSON document `path`, all of it or, should the writing be cut
    short, nothing: a file there is either the old one or the whole new one."""
    _replace(path, json.dumps(value, ensure_ascii=False, allow_nan=False, indent=1) + "\n")


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    """Write `records` as the JSONL file `path`, one line each, atomically as `write_json`."""
    _replace(
        path, "".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in records)
    )


def _replace(path: Path, text: str) -> None:
    staging = path.with_name(path.name + ".tmp")
    with staging.open("w", encoding="utf-8") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    os.replace(staging, path)
