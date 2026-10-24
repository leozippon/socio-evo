"""How the world's texts name people and things for whoever reads them.

An event is told once for nobody in particular (`witness` None), which names everyone, and once
for each resident it concerns, which names that resident "you". Texts are in the past tense, so
that "you" and a name take the same verb.
"""

from __future__ import annotations

from collections.abc import Sequence


def you(person: str, witness: str | None) -> str:
    """`person` by name, or "you" if it is the witness."""
    return "you" if person == witness else person


def cap(text: str) -> str:
    """`text` with its first letter upper-case, to start a sentence."""
    return text[:1].upper() + text[1:]


def listed(items: Sequence[str]) -> str:
    """`a`, `a and b`, `a, b and c`."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def counted(n: int, thing: str, things: str | None = None) -> str:
    """`1 file`, `3 files`."""
    return f"{n} {thing if n == 1 else things or thing + 's'}"


def first_line(text: str, limit: int = 100) -> str:
    """The first non-blank line of `text`, cut to `limit` characters."""
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
