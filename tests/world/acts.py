"""What the world's tests share about things and money: the town's open actions `take` and `give`
as a resident of a `tests.support.towns.Town` calls them, each returning what the resident reads,
and the counts that must be conserved, of every unit of every item and of the town's money."""

from __future__ import annotations

from collections import Counter

from tests.support.towns import Town
from world.economy import SUPPLIER
from world.world import World


async def take(town: Town, who: str, what: str, source: str, amount: int = 1) -> str:
    """`who` takes `amount` of `what` from `source`: a person, `shelves`, `counter`, `larder`
    or `here`."""
    return (await town.call(who, "take", what=what, amount=amount, **{"from": source})).text


async def give(town: Town, who: str, what: str, to: str, amount: int = 1) -> str:
    """`who` gives `amount` of `what` to `to`: a person, `shelves`, `counter`, `larder` or
    `here`."""
    return (await town.call(who, "give", what=what, amount=amount, to=to)).text


def keys(world: World) -> list[str]:
    """Every holder in the town: the residents, the places and the businesses' holders; not the
    supplier, which is outside it."""
    return [*world.residents, *(key for key in world.holders if key != SUPPLIER)]


def census(world: World) -> Counter[str]:
    """The units of each item in the town, in every holder."""
    held: Counter[str] = Counter()
    for key in keys(world):
        held.update(world.holder(key).items)
    return held


def money(world: World) -> int:
    """The town's money: the treasury, every purse, and whatever is left anywhere."""
    return world.treasury.balance + sum(world.holder(key).money for key in keys(world))


def moves(world: World) -> list[dict]:
    """The log's entries of things and money moved by a resident's hand."""
    return [entry for entry in world.log.entries() if entry["kind"] == "move"]
