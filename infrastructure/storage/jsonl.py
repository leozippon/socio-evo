"""Durable line-at-a-time JSONL appending and strict reading."""

import json
import os
from collections.abc import Iterator, Mapping
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
