"""Compaction: what the resident is asked for when its context is condensed, and what is kept.

The runtime compacts when the context exceeds its threshold or the resident calls `compact`.
It asks the model, in the same session (same system prompt, tools and messages, so that the
cached prefix serves), for a summary under fixed headings, then records in the session the
summary and the ids of every message it replaces. The context is rebuilt as the system prompt,
the summary as a user message and the last few exchanges kept whole.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent import texts
from agent.session import Entry
from infrastructure.llm import Message

INSTRUCTION = Message(role="user", content=texts.COMPACTION_REQUEST)
"""The request for the summary, appended to the context for that one call only."""


def exchanges(entries: Sequence[Entry]) -> list[list[Entry]]:
    """`entries` cut into exchanges: the user messages that lead up to a reply, the reply and
    the results of the tool calls it made. An exchange never separates a tool call from its
    result; user messages with no reply after them form the last exchange."""
    cut: list[list[Entry]] = []
    for entry in entries:
        role = entry.message.role
        current = cut[-1] if cut else None
        replied = current is not None and any(e.message.role == "assistant" for e in current)
        if role == "tool" or (current is not None and not replied):
            if current is None:
                raise ValueError(f"message {entry.id} answers a tool call outside the context")
            current.append(entry)
        else:
            cut.append([entry])
    return cut


def kept(entries: Sequence[Entry], count: int) -> list[int]:
    """The ids of the messages of the last `count` exchanges of `entries`."""
    return [entry.id for exchange in exchanges(entries)[-count:] for entry in exchange]
