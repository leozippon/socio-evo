"""Items and their holders: the one way units change hands, and the one place presence is checked.

Every unit of an item is held by one holder (`holder`): a resident, by its inventory; a place, by
what is left there for anyone and, at the Store and the Restaurant, by what the business keeps there
(the shelves, the larder and the portions); or the supplier outside the town. `move` is the only way
units change hands, and the one place that enforces presence: the resident who moves them is at the
place of every holder that is a place's, and any other resident it moves them to or from is awake
there with it (`reach`). A resident who hands units over (`hand`, for `get`, `put` and `pass`) has
its body and the receiver's reckoned first, and the receiver takes them in: a dish is eaten where it
is served (`eat_now`), ready food at once by one who could eat.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from world.businesses import BUSINESSES
from world.config import Item
from world.economy import LARDER, PORTIONS, SHELVES, SUPPLIER, Holder
from world.telling import amount, bare, cap, you

if TYPE_CHECKING:
    from world.world import Resident, Tell, World


def holder(world: World, key: str) -> Holder:
    """The holder named `key`: a resident by its name, what is left at a place by the place's
    id, or `SHELVES`, `LARDER`, `PORTIONS` or `SUPPLIER`."""
    r = world.residents.get(key)
    return r.inventory if r is not None else world.holders[key]


def _where(world: World, key: str) -> str | None:
    """The place of the holder `key`, which is no resident: a place's own, a business's for
    what it holds (the Store's shelves, the kitchen's larder and portions); none for the
    supplier."""
    if key == SUPPLIER:
        return None
    owner = next((b for b in BUSINESSES.values() if key in b.holds), None)
    return owner.place(world.config).id if owner is not None else key


def reach(world: World, by: Resident, key: str) -> str | None:
    """Why `by` cannot move units from or to the holder `key`, or None if it can: a place's
    holder it reaches at that place, another resident only awake at its own place."""
    other = world.residents.get(key)
    if other is not None:
        if other is by:
            return None
        if not world.visible(by, other):
            return f"{other.name} is not here."
        return None if other.awake else f"{other.name} is asleep."
    place = _where(world, key)
    if place is not None and place != by.place:
        return f"You are not at {world.config.place(place).name}."
    return None


def move(
    world: World,
    item: str,
    units: int,
    source: str | None,
    target: str | None,
    *,
    by: Resident | None = None,
) -> str | None:
    """Move `units` of `item` from the holder `source` to the holder `target` (`holder`):
    the only way units change hands. A `source` of None brings units into being (portions
    cooked); a `target` of None takes them out of it (eaten, cooked with, perished). `by`,
    the resident who moves them, must reach both holders (`reach`); the world's own moves (a
    delivery, what the chef bought sent to the kitchen, midnight) have none. Returns the
    refusal, nothing moved: a holder out of reach, a source that does not hold the units, or
    a resident who would hold more than one of a durable; or None once moved."""
    thing = world.config.item(item)
    for key in (source, target):
        if by is not None and key is not None and (refused := reach(world, by, key)):
            return refused
    if source is not None and (held := holder(world, source).units(item)) < units:
        return _short(world, source, thing, held, by)
    if target in world.residents and thing.kind == "durable":
        w = by.name if by is not None else None
        who, verb = cap(you(target, w)), "have" if target == w else "has"
        if holder(world, target).units(item):
            return f"{who} already {verb} {thing.name}."
        if units > 1:
            return f"{who} can have only one {bare(thing.name)}."
    if source is not None:
        holder(world, source).take(item, units)
    if target is not None:
        holder(world, target).add(item, units)
    return None


def moved(refusal: str | None) -> None:
    """A move the world makes of its own, or once its conditions are checked, is never
    refused."""
    if refusal is not None:
        raise RuntimeError(f"a move the world makes was refused: {refusal}")


def _short(world: World, source: str, thing: Item, held: int, by: Resident | None) -> str:
    """Why the holder `source`, holding `held` units of `thing`, cannot give more."""
    what = f"only {amount(thing, held)}" if held else f"no {bare(thing.name)}"
    if by is not None and source == by.name:
        return f"You have {what}."
    if source in world.residents:
        return f"{source} has {what}."
    if source == SHELVES:
        return f"{cap(world.config.workplace('store').name)} has {what} left."
    if source == LARDER:
        return f"The kitchen holds {what}."
    if source == PORTIONS:
        return f"The kitchen has {what} ready."
    return f"You find {what} here."


def record_move(
    world: World,
    reason: str,
    tell: Tell,
    *,
    by: Resident,
    audience: list[Resident] | tuple[Resident, ...] = (),
    item: str | None = None,
    units: int = 0,
    source: str | None = None,
    target: str | None = None,
    money: int = 0,
    seller: str | None = None,
    tax: int = 0,
) -> None:
    """Log a move `by` made, told as `tell` to `audience`: `units` of `item` from the holder
    `source` to the holder `target` (None: into or out of nothing), with the `money` that
    went with it, if any, and why (`reason`: get, put, pass, eat or buy); `seller` is who
    was serving at a purchase, and `tax` what was withheld from what it took. Money alone,
    handed over, has no item."""
    payload = {"item": item, "units": units, "source": source, "target": target}
    payload |= {"money": money, "reason": reason, "seller": seller, "tax": tax}
    world.record("move", tell, actor=by, audience=audience, payload=payload)


def hand(
    world: World,
    r: Resident,
    reason: str,
    thing: Item,
    units: int,
    source: str,
    target: str,
    tell: Tell,
    *,
    audience: list[Resident],
) -> str | None:
    """`r` moves `units` of `thing` from the holder `source` to the holder `target` for
    `reason` (`get`, `put` or `pass`), told as `tell` to `audience`: the bodies of `r` and of
    the resident it hands them to are reckoned first, so that what either would have eaten
    by now is eaten; the move (`move`, which needs `r` where the holders are) is logged
    (`record_move`); and a resident who receives them takes them in, a dish eaten where it
    is served (`eat_now`), food eaten at once if it could eat (`take_in`, told to a receiver
    other than `r`). Returns the refusal, nothing moved, or None."""
    receiver = world.residents.get(target)
    world.reckon(r)
    if receiver is not None and receiver is not r:
        world.reckon(receiver)
    if refusal := move(world, thing.id, units, source, target, by=r):
        return refusal
    record_move(
        world,
        reason,
        tell,
        by=r,
        audience=audience,
        item=thing.id,
        units=units,
        source=source,
        target=target,
    )
    if receiver is not None and thing.dish:
        eat_now(world, receiver, thing.id, units)
    elif receiver is not None:
        world.take_in(receiver, tell=receiver is not r)
    return None


def eat_now(world: World, r: Resident, item: str, units: int = 1) -> None:
    """`r` eats `units` of the ready food or the dish `item` it holds, there and then: by its
    own choice (`eat`), or a dish it has just been served, which is eaten where it is served.
    Each need that crossed into another band is noted, untold, since the result or what `r`
    is told of the serving tells it. `take_in` is the body's own eating, as hunger asks."""
    before = world.body.bands(r.living)
    world.eat(r, item, units)
    world.note_bands(r, before, tell=False)


def held_told(world: World, held: dict[str, int]) -> list[str]:
    """The units of each item of `held`, in the catalogue's order, as a sentence names them."""
    return [amount(item, held[item.id]) for item in world.config.items if held.get(item.id)]
