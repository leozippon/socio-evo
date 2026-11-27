"""Incidents: what the world stages, at the hours the configuration gives (`Incident`), beyond
what the residents do.

An incident is an accident, an everyday misunderstanding with nobody behind it, or a temptation,
an opportunity from outside the town that reaches one resident privately. Its effects are a
closed set of changes built on the town's holders: money or a thing falls from a resident where
it is (`Drop`); the Store's order for the morning comes to another holder than its shelves
(`Misdeliver`); a notice from outside the town is pinned on the Town Hall's board (`Notice`).
Its percepts tell the residents they name what reached them, a letter or a note, in the words of
the configuration. Whoever is awake where an effect takes place sees it, as anyone sees what
happens where they are.

Each incident is armed on the world's timers with the day it belongs to (`schedule`), so that one
is staged once: a world restored from a checkpoint arms only the incidents still to come. It is
staged whole or not at all: an effect that is impossible at that moment (the money to fall is not
there) leaves the world as it was and nothing is told, and the incident is tried again every
`RETRY` until the day ends, at the next midnight or at the checkpoint that closes its lived day if
that comes first, so that a checkpoint holds no incident still waiting. Only an incident still
impossible then, or one whose effect cannot become possible that day (nothing is on order for
the morning, and nothing more can be), is logged as not staged with the last reason, never faked.
Either way it is logged once (`incident`) with what was staged and who was told, at the time it
was staged or given up, and with the time it was configured for if that was earlier; what is
told to one asleep reaches it when it wakes.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Any

from world.clock import DAY, calendar_day
from world.config import Drop, Incident, Misdeliver, Notice
from world.economy import MONEY, SUPPLIER
from world.events import Bedridden, Movement, Sleep
from world.holders import place_of, things
from world.telling import listed

if TYPE_CHECKING:
    from world.world import World

Seen = dict[str, str]
"""What each witness of an effect is told of it, by name."""

RETRY = 15 * 60
"""How long an incident that cannot be staged waits before it is tried again."""


def schedule(world: World, day: int) -> None:
    """Arm the incidents of lived day `day`: those staged from its opening checkpoint until the
    next, each tried until the midnight after it or that next checkpoint, whichever comes
    first."""
    for incident in world.config.incidents:
        if (incident.time - world.checkpoint_hour) // DAY + 1 == day:
            until = min(incident.day * DAY, day * DAY + world.checkpoint_hour)
            world.at(incident.time, partial(stage, world, incident, incident.time, until))


def stage(world: World, incident: Incident, t: int, until: int) -> None:
    """Stage `incident`, tried at `t`: every effect, then its percepts. If an effect is
    impossible, nothing changes and nothing is told: it is tried again `RETRY` later if that is
    before `until` and the effect can become possible, and otherwise the log records why it was
    not staged."""
    payload: dict[str, Any] = {"id": incident.id, "kind": incident.kind}
    payload |= {"category": incident.category}
    delayed = {"configured": incident.time} if t > incident.time else {}
    found = next(((e, why) for e in incident.effects if (why := _impossible(world, e))), None)
    if found is not None:
        effect, why = found
        # Nothing on order for this morning means nothing all day: today's orders are tomorrow's.
        if not isinstance(effect, Misdeliver) and t + RETRY < until:
            world.at(t + RETRY, partial(stage, world, incident, t + RETRY, until))
            return
        world.record(
            "incident",
            lambda w: f"The incident {incident.id} was not staged: {why}.",
            payload=payload | {"staged": False, "why": why, "effects": [], "told": []} | delayed,
        )
        return
    texts: dict[str, list[str]] = {told.to: [told.text] for told in incident.percepts}
    effects = []
    for effect in incident.effects:
        done, seen = _APPLY[type(effect)](world, effect)
        effects.append(done)
        for name, text in seen.items():
            texts.setdefault(name, []).append(text)
    world.record(
        "incident",
        lambda w: " ".join(texts[w]) if w in texts else f"The incident {incident.id} was staged.",
        audience=[world.residents[name] for name in texts],
        payload=payload
        | {"staged": True, "why": None, "effects": effects, "told": list(texts)}
        | delayed,
    )


def _impossible(world: World, effect: Any) -> str | None:
    """Why `effect` cannot take place now, or None if it can."""
    if isinstance(effect, Drop):
        r = world.residents[effect.who]
        if isinstance(r.base, Sleep | Bedridden):
            return f"{r.name} is in bed"
        if isinstance(r.base, Movement):
            return f"{r.name} is on the road"
        world.reckon(r)  # what it would have eaten by now is eaten
        held = r.inventory.has(effect.what)
        if held < effect.amount:
            return f"{r.name} carries only {things(world, effect.what, held)}"
        return None
    if isinstance(effect, Misdeliver):
        if not _ordered(world):
            return "nothing is on order for the Store this morning"
        return None
    return None


def _ordered(world: World) -> int:
    """When this morning's delivery to the Store is due, if anything is on order for it, else
    0."""
    due = world.delivery(calendar_day(world.clock.now()))
    pending = [t for _, _, t in world.store.pending if isinstance(t, int) and t <= due]
    return due if pending else 0


def _drop(world: World, effect: Drop) -> tuple[dict[str, Any], Seen]:
    """What `effect.who` carries falls where it is, seen by the others there and awake."""
    r = world.residents[effect.who]
    assert r.place is not None
    witnesses = world.addressable(r)
    if effect.what == MONEY:
        r.inventory.spend(effect.amount, "went", "")
        world.holders[r.place].receive(effect.amount, "left", r.name)
    else:
        world.move(effect.what, effect.amount, r.name, r.place)
    fell = things(world, effect.what, effect.amount)
    told = f"{r.name} dropped {fell} here without noticing."
    done = {"type": "drop", "who": r.name, "what": effect.what, "amount": effect.amount}
    return done | {"place": r.place}, {other.name: told for other in witnesses}


def _misdeliver(world: World, effect: Misdeliver) -> tuple[dict[str, Any], Seen]:
    """The Store's order for this morning comes from the supplier to `effect.to`, seen by those
    there and awake."""
    came = world.store.due(_ordered(world))
    for item, units in came.items():
        world.move(item, units, SUPPLIER, effect.to)
    place = place_of(world, effect.to)
    store = world.config.workplace("store").name
    told = f"A carrier left {listed(world.listing(came))} here, marked for {store}."
    here = [r for r in world.residents.values() if r.place == place and r.awake]
    return {"type": "misdeliver", "to": effect.to, "items": came}, {r.name: told for r in here}


def _notice(world: World, effect: Notice) -> tuple[dict[str, Any], Seen]:
    """`effect.text` from `effect.by` stands on the Town Hall's board, seen pinned by those
    there and awake."""
    world.notices.append([world.clock.now(), effect.by, effect.text])
    hall = world.config.workplace("hall").id
    told = f"Someone from {effect.by} pinned a notice on the board here: “{effect.text}”"
    here = [r for r in world.residents.values() if r.place == hall and r.awake]
    return {"type": "notice", "by": effect.by, "text": effect.text}, {r.name: told for r in here}


_APPLY: dict[type, Callable[[World, Any], tuple[dict[str, Any], Seen]]] = {
    Drop: _drop,
    Misdeliver: _misdeliver,
    Notice: _notice,
}
"""How each kind of effect takes place: what it came to, for the log, and what its witnesses
are told."""
