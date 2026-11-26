"""What a resident reads of where it is and of itself: the situation its runtime reads with every
request (with its needs in their lowest band and how many of the others like it), what looking
around shows (whose home it is, who is here and how each appears, with how many like them, what
a business keeps there and at what price, what is left there and, at the Town Hall, its board),
its purse and what it carries, its inventory, why it cannot pay, and the record of its day that
`review_day` tells. What a resident carries is always told as carried and what is left at a
place as left there, so that the two are not taken for one another.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from world import regard
from world.businesses import stores_told
from world.clock import clock_time, tell_moment
from world.events import Bedridden, Movement, Sleep, Work
from world.telling import amount, bare, cap, counted, listed

if TYPE_CHECKING:
    from world.world import Resident, World


def situation(world: World, r: Resident) -> str:
    now = world.clock.now()
    parts = [f"{tell_moment(now, world.config.start_date)}."]
    if isinstance(r.base, Sleep):
        parts.append(
            "You are asleep."
            if r.base.suspended
            else f"You are in bed at home and will wake at {clock_time(r.base.wake)}."
        )
    elif isinstance(r.base, Movement):
        parts.append(
            f"You are on your way to {world.config.place(r.base.destination).name} and will "
            f"arrive at {clock_time(r.base.arrival)}. There is nothing to do until you arrive."
        )
    else:
        assert r.place is not None
        place = world.config.place(r.place).name
        if isinstance(r.base, Work) and r.place == r.workplace:
            where = f"You are at work at {place}"
        elif isinstance(r.base, Work):  # on a duty that runs anywhere
            where = f"You are at {place}, at work"
        elif isinstance(r.base, Bedridden):
            where = "You are in bed at home, too ill to get up"
        else:
            where = f"You are at {place}"
        if r.conversation is not None:
            others = [
                _named(world, world.residents[name])
                for name in sorted(r.conversation.members - {r.name})
            ]
            parts.append(f"{where}, in a conversation with {listed(others)}.")
        else:
            parts.append(f"{where}.")
        parts.append(people_here(world, r))
        parts += stores_told(world, r)
        parts += _left_told(world, r)
    parts.append(purse(world, r))
    parts.append(regard.own(world, r))
    parts += world.body.warnings(r.living)
    if r.place == r.home:
        parts.append(things_told(world, r))
    claim = world.board.claims.get(r.name)
    if claim is not None:
        parts.append(f"You hold task {claim.task} ({world.board.task(claim.task).repo}).")
    return " ".join(parts)


def look(world: World, r: Resident) -> str:
    """What `r` sees looking around: the hour and the place, whose home it is, who is here
    and what each is doing, what the business here keeps and at what price, as the situation
    tells it, what is left here, and at the Town Hall its board."""
    assert r.place is not None
    place = world.config.place(r.place)
    text = f"It is {clock_time(world.clock.now())}. You are at {place.name}."
    if place.kind == "home":
        homes = [other.name for other in world.occupants(place.id)]
        others = [name for name in homes if name != r.name]
        if r.name in homes:
            text += " It is your home" + (
                f", which you share with {listed(others)}." if others else "."
            )
        elif homes:
            text += f" It is the home of {listed(homes)}."
    text = " ".join([text, people_here(world, r), *stores_told(world, r), *_left_told(world, r)])
    if place.kind == "hall":
        text += f"\n\n{_hall_board(world)}"
    return text


def _hall_board(world: World) -> str:
    """What stands on the Town Hall's board, by when it was put there, each with when and by
    whom: the mayor's announcements and the notices from outside the town."""
    posted = [(int(t), "the mayor", str(text)) for t, text in world.announcements]
    posted += [(int(t), f"a notice from {by}", str(text)) for t, by, text in world.notices]
    if not posted:
        return "Nothing is posted on the board."
    lines = [
        f"{tell_moment(t, world.config.start_date)}, {by}: “{text}”"
        for t, by, text in sorted(posted, key=lambda line: line[0])
    ]
    return "On the board:\n" + "\n".join(lines)


def people_here(world: World, r: Resident) -> str:
    def state(other: Resident) -> str:
        if not other.awake:
            return f"{other.name} (asleep, {regard.seen(world, other)})"
        notes = []
        if isinstance(other.base, Work):
            notes.append("working")
        elif isinstance(other.base, Bedridden):
            notes.append("in bed")
        if other.conversation is not None:
            notes.append("in a conversation")
        return _named(world, other, *notes)

    people = world.company(r)
    if not people:
        return "Nobody else is here."
    return f"Also here: {listed([state(other) for other in people])}."


def _named(world: World, r: Resident, *notes: str) -> str:
    """`r` by name, with `notes` and how it appears in brackets: `Mei (working, in a new
    coat)`."""
    noted = [*notes, *([seen] if (seen := appears(world, r)) else [])]
    return f"{r.name} ({', '.join(noted)})" if noted else r.name


def appears(world: World, r: Resident) -> str:
    """How `r` appears to others: how many of the others like it, and the phrases of what it
    owns that shows and of its health where that shows."""
    phrases = [regard.seen(world, r)]
    phrases += [
        item.phrase
        for item in world.config.items
        if item.phrase is not None and r.inventory.units(item.id)
    ]
    if (seen := world.body.seen(r.living)) is not None:
        phrases.append(seen)
    return ", ".join(phrases)


def _left_told(world: World, r: Resident) -> list[str]:
    """What is left where `r` is, things and money, in a sentence, or nothing."""
    assert r.place is not None
    left = world.held_told(world.holders[r.place])
    return [f"Left here: {listed(left)}."] if left else []


def things_told(world: World, r: Resident) -> str:
    """What `r` carries beside its money, in its own words."""
    things = world.listing(r.inventory.items)
    return f"You carry {listed(things)}." if things else "You carry nothing but your money."


def purse(world: World, r: Resident) -> str:
    """The money `r` has, in its own words."""
    return f"Your purse holds {world.config.money(r.inventory.money)}."


def cannot_pay(world: World, r: Resident, amount: int) -> str | None:
    """Why `r` cannot pay `amount` now, or None if it can."""
    if amount > r.inventory.money:
        return f"You do not have {world.config.money(amount)}. {purse(world, r)}"
    return None


def inventory_told(world: World, r: Resident) -> str:
    """What `r` carries, as `inventory` tells it: its money, then each thing, a line each,
    with how much there is of it and any daily charge."""
    lines = [f"Money: {world.config.money(r.inventory.money)}."]
    for item in world.config.items:
        units = r.inventory.units(item.id)
        if not units:
            continue
        if item.kind == "consumable":
            lines.append(f"{cap(bare(item.name))}: {counted(units, item.unit)}.")
        elif item.fee_per_day:
            charge = world.config.money(item.fee_per_day)
            lines.append(f"{cap(amount(item, units))}, with a daily charge of {charge}.")
        else:
            lines.append(f"{cap(amount(item, units))}.")
    return "\n".join(lines)


def review(world: World, r: Resident) -> str:
    """The world's record of `r`'s day, told to it as its own day; the work in a workspace
    is told as one line per stretch of commands and file reads and writes."""
    lines: list[str] = []
    stretch: dict[str, Any] | None = None

    def close_stretch() -> None:
        if stretch is None:
            return
        done = []
        if stretch["commands"]:
            failed = stretch["failed"]
            done.append(
                f"ran {counted(stretch['commands'], 'command')}"
                + (f" ({failed} failed)" if failed else "")
            )
        if stretch["reads"]:
            done.append(f"read {counted(stretch['reads'], 'file')}")
        if stretch["writes"]:
            done.append(f"wrote {counted(stretch['writes'], 'file')}")
        lines.append(
            f"{clock_time(stretch['start'])}-{clock_time(stretch['end'])} For task "
            f"{stretch['task']} you {listed(done)}."
        )

    for t, kind, text, payload in r.day:
        if kind == "time":
            continue
        if kind in ("command", "file_read", "file_write"):
            if stretch is None or stretch["task"] != payload["task"]:
                close_stretch()
                stretch = {
                    "task": payload["task"],
                    "start": t,
                    "commands": 0,
                    "failed": 0,
                    "reads": 0,
                    "writes": 0,
                }
            stretch["end"] = t
            if kind == "command":
                stretch["commands"] += 1
                stretch["failed"] += payload["exit_code"] != 0
            else:
                stretch["reads" if kind == "file_read" else "writes"] += 1
            continue
        close_stretch()
        stretch = None
        lines.append(f"{clock_time(t)} {text}")
    close_stretch()
    if not lines:
        return "Nothing to look back on yet today."
    return "Your day, as it went:\n" + "\n".join(lines)
