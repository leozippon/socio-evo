"""Regard: the number every resident carries, which it and everyone else can see, of how many of
the others like it.

Going to bed, a resident names the people it likes (`name`), every night anew, and the names
replace those it gave before; one the world puts to sleep (the night's end, its bed) keeps the
names it last gave, and the configuration gives the first (`Resident.likes`). The numbers shown
change once a night, at the night's end (`night`), to follow the names then given, and do not
move during the day; a resident reads its own in its situation and the others' wherever the
people present are described (`seen`), and on its first waking after the change it is told its
number beside yesterday's (`morning`). `liked_by` is every resident's number as the names given
now make it, which at the checkpoint, after the night's end, is the one the next day shows.

The number buys nothing and no rule refers to it. Each naming is logged for nobody but the one
who named (`likes`), and each morning's number as it is told (`regard`), so that the log gives
every resident's number on every day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from world.telling import listed

if TYPE_CHECKING:
    from world.config import TownConfig
    from world.world import Resident, World


def counts(likes: dict[str, list[str]]) -> dict[str, int]:
    """How many of the others like each resident, by the names each has given."""
    liked = dict.fromkeys(likes, 0)
    for names in likes.values():
        for name in names:
            liked[name] += 1
    return liked


@dataclass
class Regard:
    """The names each resident last gave (`likes`), the numbers shown since the last night's end
    (`shown`) and those shown the day before (`yesterday`, none on the first day), checkpointed;
    and who has been told this morning's numbers (`told`), which is empty at every checkpoint,
    since nobody wakes between the night's end and the checkpoint."""

    likes: dict[str, list[str]]
    shown: dict[str, int]
    yesterday: dict[str, int] | None = None
    told: set[str] = field(default_factory=set)

    @classmethod
    def of(cls, config: TownConfig) -> Regard:
        """The town at the start: the names the configuration gives."""
        likes = {r.name: list(r.likes) for r in config.residents}
        return cls(likes, counts(likes))

    def saved(self) -> dict[str, Any]:
        return {"likes": self.likes, "shown": self.shown, "yesterday": self.yesterday}

    @classmethod
    def restored(cls, saved: dict[str, Any]) -> Regard:
        return cls(
            {name: list(names) for name, names in saved["likes"].items()},
            dict(saved["shown"]),
            dict(saved["yesterday"]) if saved["yesterday"] is not None else None,
        )


def liked_by(world: World) -> dict[str, int]:
    """Every resident's number as the names given now make it."""
    return counts(world.regard.likes)


def refusal(world: World, r: Resident, names: list[str]) -> str | None:
    """Why `r` cannot name `names` as the people it likes, or None if it can."""
    for name in names:
        if name == r.name:
            return "You cannot name yourself among the people you like."
        if name not in world.residents:
            return f"There is nobody called {name} in the town."
    return None


def name(world: World, r: Resident, names: list[str]) -> str:
    """`r` names `names`, none of them itself, as the people it likes, in place of those it
    named before; logged for nobody else. What it is told of it."""
    world.regard.likes[r.name] = list(names)
    whom = "people" if len(names) > 1 else "someone"
    told = f"You named {listed(names) or 'nobody'} as {whom} you like."
    world.record(
        "likes",
        lambda w: told if w == r.name else f"{r.name} named whom it likes.",
        actor=r,
        payload={"names": list(names)},
    )
    return told


def night(world: World) -> None:
    """The night's end: the numbers shown follow the names now given, and yesterday's are kept
    beside them, for each resident to be told on waking."""
    regard = world.regard
    regard.yesterday, regard.shown = regard.shown, counts(regard.likes)
    regard.told.clear()


def own(world: World, r: Resident) -> str:
    """`r`'s number, as its situation tells it: `4 of the others like you.`"""
    return f"{_others(world.regard.shown[r.name])}."


def seen(world: World, r: Resident) -> str:
    """`r`'s number, as others see it on `r`: `liked by 4`."""
    return f"liked by {world.regard.shown[r.name]}"


def morning(world: World, r: Resident) -> None:
    """`r`, waking, is told its number beside yesterday's, once a day: on its first waking since
    the numbers last changed, or since the town began."""
    regard = world.regard
    if r.name in regard.told:
        return
    regard.told.add(r.name)
    now = regard.shown[r.name]
    before = regard.yesterday[r.name] if regard.yesterday is not None else None
    told = f"This morning {_others(now, start=False)}"
    if before is not None:
        told += f"; yesterday {'none' if not before else before} did"
    world.record(
        "regard",
        lambda w: f"{told}." if w == r.name else f"{r.name} is liked by {now} of the others.",
        actor=r,
        audience=[r],
        payload={"liked_by": now, "yesterday": before},
    )


def _others(n: int, *, start: bool = True) -> str:
    """`4 of the others like you`, `1 of the others likes you`, `None of the others likes
    you` (lower-case at no sentence's `start`)."""
    if not n:
        return f"{'N' if start else 'n'}one of the others likes you"
    return f"{n} of the others {'likes' if n == 1 else 'like'} you"
