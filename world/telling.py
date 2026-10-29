"""How the world's texts name people, things and money for whoever reads them.

An event is told once for nobody in particular (`witness` None), which names everyone, and once
for each resident it concerns, which names that resident "you". Texts are in the past tense, so
that "you" and a name take the same verb. Money is written by `money` alone, which
`TownConfig.money` gives with the town's currency.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from world.clock import parse_hour

if TYPE_CHECKING:
    from world.config import DayHours, Item


def you(person: str, witness: str | None) -> str:
    """`person` by name, or "you" if it is the witness."""
    return "you" if person == witness else person


def cap(text: str) -> str:
    """`text` with its first letter upper-case, to start a sentence."""
    return text[:1].upper() + text[1:]


def listed(items: Sequence[str], joiner: str = "and") -> str:
    """`a`, `a and b`, `a, b and c`; with `joiner` "or", `a, b or c`."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} {joiner} {items[-1]}"


def counted(n: int, thing: str, things: str | None = None) -> str:
    """`1 file`, `3 files`."""
    return f"{n} {thing if n == 1 else things or thing + 's'}"


def first_line(text: str, limit: int = 100) -> str:
    """The first non-blank line of `text`, cut to `limit` characters."""
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def duration(seconds: int) -> str:
    """`8 hours`, `7 hours and 30 minutes`, `45 minutes`, in whole minutes; empty under one."""
    hours, minutes = divmod(seconds // 60, 60)
    return listed([counted(n, unit) for n, unit in ((hours, "hour"), (minutes, "minute")) if n])


def money(currency: str, amount: int) -> str:
    """`amount` of `currency`, as the town writes it: `$40`."""
    return f"{currency}{amount}"


def bare(name: str) -> str:
    """An item's name without its article: `a phone` is `phone`."""
    for article in ("a ", "an ", "the "):
        if name.startswith(article):
            return name[len(article) :]
    return name


def amount(item: Item, units: int) -> str:
    """`units` of `item` as a sentence names them: `a phone`, `2 phones`, `3 helpings of bread`,
    `4 units of rice`, `stew`, `2 portions of stew`."""
    if item.kind == "durable" or (item.dish and units == 1):
        return item.name if units == 1 else counted(units, bare(item.name))
    return f"{counted(units, item.unit)} of {bare(item.name)}"


def fraction(factor: float) -> str:
    """`half`, `a quarter of`, `70% of`: the share of the time a journey takes."""
    if factor == 0.5:
        return "half"
    if factor == 0.25:
        return "a quarter of"
    return f"{round(factor * 100)}% of"


def comfort_word(comfort: float) -> str | None:
    """How a home's comfort is told beside its rent: `little comfort` below an ordinary home's,
    `comfortable` above it, nothing for an ordinary home."""
    if comfort < 1:
        return "little comfort"
    if comfort > 1:
        return "comfortable"
    return None


def share(rate: float) -> str:
    """`a tenth`, `a fifth`, `12%`: a share of money, as the town tells it."""
    return {0.5: "half", 0.25: "a quarter", 0.2: "a fifth", 0.1: "a tenth"}.get(rate, f"{rate:.0%}")


def longest_sleep(day: DayHours) -> str:
    """How long one sleep lasts at most, told: `12 hours`."""
    return duration(parse_hour(day.sleep_at_most))
