"""The persistent session: an append-only JSONL file of every message the resident's context has
held, each with an id, and of every compaction, with the ids of the messages it replaced and the
summary that took their place. The context of the next request is the fold of the file."""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from agent import texts
from infrastructure.config import StrictModel
from infrastructure.llm import Message
from infrastructure.storage import append_jsonl, read_jsonl

CHARS_PER_TOKEN = 3
"""The estimate of a token's length in characters, on the safe side: English prose runs near
four, code and other languages fewer."""


class MessageRecord(StrictModel):
    """A message appended to the context; an assistant message carries the prompt tokens the
    server reported for the request that it answered."""

    type: Literal["message"] = "message"
    id: int
    message: Message
    prompt_tokens: int | None = None


class CompactionRecord(StrictModel):
    """A compaction: the messages `replaced` leave the context, and `summary`, shown as a user
    message under this record's id, comes first in it, before the messages kept."""

    type: Literal["compaction"] = "compaction"
    id: int
    replaced: tuple[int, ...]
    summary: str


Record = Annotated[MessageRecord | CompactionRecord, Field(discriminator="type")]
_RECORD: TypeAdapter[MessageRecord | CompactionRecord] = TypeAdapter(Record)


@dataclass(frozen=True)
class Entry:
    """A message of the context and the id of the record it comes from."""

    id: int
    message: Message


class Session:
    """The session stored at `path`, loaded from it if it exists; a malformed file raises
    ValueError naming the problem."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: list[Entry] = []
        self._summary: int | None = None
        self._measured: tuple[int, int] | None = None
        self._next = 1
        if path.exists():
            for line, raw in enumerate(read_jsonl(path), start=1):
                try:
                    self._apply(_RECORD.validate_python(raw))
                except ValueError as error:
                    raise ValueError(f"{path}:{line}: {error}") from error

    def context(self) -> tuple[Entry, ...]:
        """The messages of the context, in order: the latest summary, if any, the messages it
        kept and those appended since."""
        return tuple(self._entries)

    def append(self, message: Message, *, prompt_tokens: int | None = None) -> int:
        """Append `message` and return its id; `prompt_tokens` is the server's count for the
        request an assistant message answered."""
        record = MessageRecord(id=self._next, message=message, prompt_tokens=prompt_tokens)
        self._write(record)
        return record.id

    def compact(self, summary: str, keep: Collection[int]) -> CompactionRecord:
        """Replace every message of the context but those in `keep`, and any earlier summary,
        with `summary`."""
        ids = [entry.id for entry in self._entries]
        if not set(keep) <= set(ids):
            raise ValueError(f"cannot keep messages outside the context: {set(keep) - set(ids)}")
        replaced = tuple(i for i in ids if i not in keep or i == self._summary)
        record = CompactionRecord(id=self._next, replaced=replaced, summary=summary)
        self._write(record)
        return record

    def size(self, prefix: str) -> int:
        """The size of the context in tokens: the prompt tokens the server reported for the
        latest request answered since the last compaction, plus an estimate of the messages
        appended since; with no such report, an estimate of `prefix` (what precedes the
        messages: the system prompt and the tools declared) and of every message."""
        if self._measured is None:
            return estimate(prefix) + sum(_estimate(entry.message) for entry in self._entries)
        tokens, position = self._measured
        return tokens + sum(_estimate(entry.message) for entry in self._entries[position:])

    def _write(self, record: MessageRecord | CompactionRecord) -> None:
        self._apply(record)
        append_jsonl(self._path, record.model_dump(mode="json", exclude_none=True))

    def _apply(self, record: MessageRecord | CompactionRecord) -> None:
        if record.id < self._next:
            raise ValueError(f"record id {record.id} does not follow {self._next - 1}")
        self._next = record.id + 1
        if isinstance(record, MessageRecord):
            self._entries.append(Entry(record.id, record.message))
            if record.prompt_tokens is not None:
                self._measured = (record.prompt_tokens, len(self._entries) - 1)
            return
        replaced = set(record.replaced)
        if not replaced <= {entry.id for entry in self._entries}:
            raise ValueError(f"compaction {record.id} replaces messages outside the context")
        summary = Message(role="user", content=texts.SUMMARY.format(summary=record.summary))
        kept = [entry for entry in self._entries if entry.id not in replaced]
        self._entries = [Entry(record.id, summary), *kept]
        self._summary = record.id
        self._measured = None


def estimate(text: str) -> int:
    """An estimate of the tokens in `text`, on the safe side."""
    return len(text) // CHARS_PER_TOKEN + 1


def _estimate(message: Message) -> int:
    calls = "".join(
        call.name + json.dumps(call.arguments, ensure_ascii=False) for call in message.tool_calls
    )
    return estimate(message.content + calls) + 4
