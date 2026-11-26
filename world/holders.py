"""Things and their holders: how units and money change hands, who sees it, and what an owner
who did not is told.

Every unit of an item is held by one holder, with whatever money is there (`holder`): a resident,
by its inventory; a place, by what is left there; at the Store and the Restaurant, what the
business keeps there (the shelves, the counter and the larder); or the supplier outside the town.

A resident takes and gives with `transfer`, the one way things and money pass between holders
by a resident's hand, and the one place where presence is checked and the act is told. Reach is
being there (`reach`): a resident reaches what is left at the place where it is, what a business
keeps at that place, and anyone else there, awake or asleep. Nothing else is asked: a thing or
money that is there can be taken, whoever's it is, and nothing is charged for it; a price posted
where it stood is recorded and told to the one who took it, no more. A take gives as much as is
asked or as much as is there, if that is less, so that how much another holds is learnt only by
an act the others see (that there is none is a refusal, which is no act and which nobody sees);
a gift is of what one has, or refused. Money given to a resident who is at work is payment for
its work, and the tax is withheld from it (`World.earn`); money given otherwise, and whatever is
taken, is not taxed.

Everyone at the place and awake perceives the act, each in the words of its part in it: the one
who acts, the one taken from or given to, one whose business the shelves are, anyone else. One
asleep or elsewhere perceives nothing. For each owner of a holder (`owners`: a resident of what
it carries, a business's keepers of what the business keeps) the world counts what left the
holder unseen by it, less what was put back unseen (`Resident.missing`), and tells it what is
gone, never by whom, when it next sees for itself (`notice`): waking, what went from its own
person; coming back to its business's place, what went from the shelves, the counter or the
larder.

The world's own moves, which nobody makes by hand (a delivery, cooking, eating, what perishes at
midnight), go through `move`, and each is logged by whoever makes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from world.businesses import keeping, posted
from world.economy import COUNTER, LARDER, MONEY, SHELVES, SUPPLIER, Holder
from world.events import Work
from world.telling import amount, bare, cap, listed, you

if TYPE_CHECKING:
    from world.world import Resident, Tell, World

PUT = {SHELVES: "on", COUNTER: "on", LARDER: "in"}
"""The businesses' holders, each with how a thing is left there: `on the shelves`, `in the
larder`."""


def holder(world: World, key: str) -> Holder:
    """The holder named `key`: a resident by its name, what is left at a place by the place's
    id, or `SHELVES`, `COUNTER`, `LARDER` or `SUPPLIER`."""
    r = world.residents.get(key)
    return r.inventory if r is not None else world.holders[key]


def place_of(world: World, key: str) -> str | None:
    """The place of the holder `key`, which is no resident: a place's own, a business's for
    what it keeps; none for the supplier."""
    if key == SUPPLIER:
        return None
    business = keeping(key)
    return business.place(world.config).id if business is not None else key


def owners(world: World, key: str) -> list[Resident]:
    """Whose the holder `key` is: a resident's own inventory, a business's holder its
    keepers'; what is left at a place is nobody's."""
    r = world.residents.get(key)
    if r is not None:
        return [r]
    business = keeping(key)
    return business.keepers(world) if business is not None else []


def reach(world: World, by: Resident, key: str) -> str | None:
    """Why `by` cannot take from or give to the holder `key`, or None if it can: it reaches
    another resident at its own place, awake or asleep, and a place's or a business's holder
    at that place."""
    other = world.residents.get(key)
    if other is not None:
        return None if world.visible(by, other) else f"{other.name} is not here."
    place = place_of(world, key)
    assert place is not None, "nobody reaches the supplier"
    return None if place == by.place else f"You are not at {world.config.place(place).name}."


def move(world: World, item: str, units: int, source: str | None, target: str | None) -> None:
    """Move `units` of `item` from the holder `source` to the holder `target`, which the source
    must hold: the one way units pass between holders. A `source` of None brings units into
    being (portions cooked); a `target` of None takes them out of it (eaten, cooked with,
    perished)."""
    if source is not None:
        holder(world, source).take(item, units)
    if target is not None:
        holder(world, target).add(item, units)


def things(world: World, what: str, units: int) -> str:
    """`units` of `what`, an item or money, as a sentence names them: `$5`, `2 helpings of
    bread`."""
    return world.config.money(units) if what == MONEY else amount(world.config.item(what), units)


def listing(world: World, held: dict[str, int], money: int = 0) -> list[str]:
    """`money`, if any, and the units of each item of `held`, in the catalogue's order, as a
    sentence names them; `held` may count money under `MONEY`."""
    money += held.get(MONEY, 0)
    told = [world.config.money(money)] if money else []
    return told + [amount(item, held[item.id]) for item in world.config.items if held.get(item.id)]


def held_told(world: World, held: Holder) -> list[str]:
    """What `held` holds, as a sentence names it: its money, then each thing."""
    return listing(world, held.items, held.money)


def _where(world: World, key: str, w: str | None, *, taken: bool) -> str:
    """Where things were taken from (`taken`) or left, as `w` reads it: `from Aisha`, `from
    you`; `from the shelves`, `on the shelves`, `in your larder` to one whose business it is;
    `left at the park`, `at the park`."""
    if key in world.residents:
        return f"from {you(key, w)}"
    if key in PUT:
        whose = "your" if any(owner.name == w for owner in owners(world, key)) else "the"
        return f"{'from' if taken else PUT[key]} {whose} {key}"
    place = world.config.place(key).name
    return f"left at {place}" if taken else f"at {place}"


def record_move(
    world: World,
    tell: Tell,
    *,
    by: Resident,
    what: str,
    units: int,
    source: str | None,
    target: str | None,
    reason: str,
    audience: list[Resident] | tuple[Resident, ...] = (),
    price: int | None = None,
    tax: int = 0,
) -> None:
    """Log that `by` moved `units` of `what`, an item or money, from the holder `source` to the
    holder `target` (None: into nothing), told as `tell` to `audience`, and why (`reason`:
    take, give or eat), with the `price` posted for a unit where it was taken, if one was, and
    the `tax` withheld from money given to one at work."""
    payload = {"what": what, "amount": units, "source": source, "target": target}
    payload |= {"reason": reason, "price": price, "tax": tax}
    world.record("move", tell, actor=by, audience=audience, payload=payload)


@dataclass(frozen=True)
class Moved:
    """What a transfer came to: `told`, as the one who made it reads it; the `amount` that
    changed hands, which a take may find less than asked; the `price` posted for a unit where
    it was taken, if one was; and what the one who took it `ate` of its food at once, the
    helpings of each item."""

    told: str
    amount: int
    price: int | None
    ate: dict[str, int]


def transfer(
    world: World, by: Resident, what: str, units: int, source: str, target: str
) -> Moved | str:
    """`by` takes `units` of `what`, an item or money, from the holder `source` for itself, or
    gives them from what it carries to the holder `target` (see the module docstring): one of
    the two holders is `by`'s own, and the other it must reach. Both bodies are reckoned
    first, so that what either would have eaten by now is eaten; the things or the money change
    hands, the tax withheld from money given to one at work; what went unseen by an owner is
    counted for it; the act is logged and told to everyone there and awake; and a resident
    who received food eats of it at once as far as it could eat. Returns what it came to, or
    the refusal, nothing moved: the other holder out of reach, nothing of the kind there to
    take, or more given than `by` has."""
    taking = target == by.name
    key = source if taking else target
    if refusal := reach(world, by, key):
        return refusal
    other = world.residents.get(key)
    world.reckon(by)
    if other is not None:
        world.reckon(other)
    held = holder(world, source).has(what)
    name = MONEY if what == MONEY else bare(world.config.item(what).name)
    if taking and not held:
        if other is not None:
            return f"{other.name} has no {name}."
        return f"You find no {name} {_where(world, key, by.name, taken=False)}."
    if not taking and held < units:
        return f"You have only {things(world, what, held)}." if held else f"You have no {name}."
    units = min(units, held)
    witnesses = world.addressable(by)
    price = posted(world, source, what) if taking else None
    tax = _hand_over(world, by, what, units, source, target)
    for end, sign in ((source, 1), (target, -1)):
        for owner in owners(world, end):
            if owner is not by and owner not in witnesses:
                gone = owner.missing.setdefault(end, {})
                gone[what] = gone.get(what, 0) + sign * units
    moved = things(world, what, units)

    def tell(w: str | None) -> str:
        actor = cap(you(by.name, w))
        if taking:
            return f"{actor} took {moved} {_where(world, source, w, taken=True)}."
        if other is None:
            return f"{actor} left {moved} {_where(world, target, w, taken=False)}."
        withheld = f", of which {world.config.money(tax)} in tax" if tax and w == target else ""
        return f"{actor} gave {you(target, w)} {moved}{withheld}."

    record_move(
        world,
        tell,
        by=by,
        what=what,
        units=units,
        source=source,
        target=target,
        reason="take" if taking else "give",
        audience=witnesses,
        price=price,
        tax=tax,
    )
    ate: dict[str, int] = {}
    if what != MONEY and taking:
        ate = world.take_in(by)
    elif what != MONEY and other is not None:
        world.take_in(other, tell=True)
    return Moved(tell(by.name), units, price, ate)


def _hand_over(world: World, by: Resident, what: str, units: int, source: str, target: str) -> int:
    """The units of an item, or the money, that `by` takes or gives pass from the holder
    `source` to the holder `target`, the purses recording what the statement tells of money.
    Money that `by` gives to a resident at work is paid to it with the tax withheld
    (`World.earn`). Returns the tax."""
    if what != MONEY:
        move(world, what, units, source, target)
        return 0
    giver, receiver = holder(world, source), holder(world, target)
    if target == by.name:
        giver.spend(units, "lost", "")
        receiver.receive(units, "took", _where(world, source, None, taken=True))
        return 0
    other = world.residents.get(target)
    if other is None:
        giver.spend(units, "left", _where(world, target, None, taken=False))
        receiver.receive(units, "received", by.name)
        return 0
    giver.spend(units, "gave", other.name)
    if isinstance(other.base, Work):
        return world.earn(other, units, f"from {by.name} at work")
    receiver.receive(units, "received", by.name)
    return 0


def notice(world: World, r: Resident) -> None:
    """`r`, awake, is told what went unseen from what is its own and is before it again: from
    what it carries, while it slept; from what its business keeps at the place where it now
    is, while it was away. It is told what and how much, less what was put back unseen, and
    never by whom; each holder's is logged (`missing`)."""
    for key in [key for key in r.missing if key == r.name or place_of(world, key) == r.place]:
        gone = {what: units for what, units in r.missing.pop(key).items() if units > 0}
        if not gone:
            continue
        went = listed(listing(world, gone))
        if key == r.name:
            told, seen = f"While you slept, {went} went from what you carry.", "what it carried"
        else:
            told, seen = f"Since you were last here, {went} went from the {key}.", f"the {key}"
        world.record(
            "missing",
            lambda w, told=told, seen=seen, went=went: (
                told if w == r.name else f"{r.name} found {went} gone from {seen}."
            ),
            actor=r,
            audience=[r],
            payload={"holder": key, "gone": gone},
        )
