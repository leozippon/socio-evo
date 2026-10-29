"""Compaction: what the resident is asked for when its context is condensed, and what is kept.

The runtime compacts when the context exceeds its threshold or the resident calls `compact`;
a call is answered that there is nothing to set aside yet, and no notes are asked for, when the
exchanges kept whole would hold the whole context, the call's own reply with it (`sets_aside`).
It asks the model, in the same session (same system prompt, tools and messages, so that the
cached prefix serves) but with `tool_choice` "none", for notes under fixed headings, then
records in the session the notes and the ids of every message they replace. The context is
rebuilt as the system prompt, the notes as a user message and the most recent exchanges kept
whole, as many as a budget of tokens holds and at least one. Only notes without a `flaw` are
kept: a model asked for text may still answer with an empty reply, which is what vLLM leaves of
a tool call it strips, or write a call out as text.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent import texts
from agent.session import Entry, estimate_message
from infrastructure.llm import Message

INSTRUCTION = Message(role="user", content=texts.COMPACTION_REQUEST)
"""The request for the notes, appended to the context for that one call only."""
CALL_AS_TEXT = ("<tool_call>", "<function=")
"""The markup that opens a tool call written out as text, as the served model writes one."""


def flaw(notes: str) -> str | None:
    """Why the reply `notes` cannot be kept as the notes, or None when it can: it is empty,
    holds a tool call written out as text, or lacks one of the headings as a line of its own."""
    if not notes.strip():
        return "empty"
    if any(markup in notes for markup in CALL_AS_TEXT):
        return "a tool call written out as text"
    lines = {line.strip() for line in notes.splitlines()}
    missing = [heading for heading in texts.NOTES_HEADINGS if heading not in lines]
    return f"without {', '.join(missing)}" if missing else None


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


def sets_aside(entries: Sequence[Entry], reply: Sequence[Message], budget: int) -> bool:
    """Whether a compaction keeping `budget` tokens would set aside any of `entries`, the
    context, once `reply` (the reply that asks for it and the answers to its calls so far)
    follows it."""
    last = max((entry.id for entry in entries), default=0)
    coming = [Entry(last + n, message) for n, message in enumerate(reply, start=1)]
    return len(kept([*entries, *coming], budget)) < len(entries) + len(coming)


def kept(entries: Sequence[Entry], budget: int) -> list[int]:
    """The ids of the messages of the most recent exchanges of `entries` whose estimated tokens
    add up to at most `budget`, and of the last exchange at least, however long it is."""
    chosen: list[list[Entry]] = []
    total = 0
    for exchange in reversed(exchanges(entries)):
        total += sum(estimate_message(entry.message) for entry in exchange)
        if chosen and total > budget:
            break
        chosen.append(exchange)
    return [entry.id for exchange in reversed(chosen) for entry in exchange]
