"""A resident's living: its body reckoned and fed, its sleep and waking, the forced sleep, taking
to its bed and treatment.

The body (`world.body`) is reckoned lazily and exactly: `reckon` brings a resident up to the moment
at the rates of what it has been doing since it was last reckoned (`activity`), counting its time on
duty (`on_duty`), and is called every hour on the hour, before every change of
activity (sitting down to work, setting off, arriving, going to bed, falling asleep, waking) and at
the checkpoint, so that a checkpoint carries the body as of its moment. A resident awake and able
to eat eats the ready food in its inventory, a helping at a time, as it is reckoned; a dish is eaten
as it is served. A resident the reckoning finds at work in the lowest band of energy stops work, as
`leave_work` stops it, keeping its task, and is told that it cannot work until it has slept; before
an action in its workspace the body is reckoned too, so that the exhausted are refused it
(`world.tools`). A need that crosses into another band is logged, and told to the resident when it
is awake at a place (the wake-up, the statement and a purchase's result tell it otherwise).

A resident goes to bed at home, to wake at the hour it gives or when its longest sleep ends, and
falls asleep once its runtime has nothing more to do; at the forced sleep whoever is still up falls
asleep where it is, to wake at home at the forced waking hour, and nobody wakes between it and the
checkpoint. A resident whose health has reached its floor at midnight takes to its bed: it leaves
what it was in, is carried home if it was elsewhere, and is Bedridden, where it can do little but
speak to whoever comes and eat what it is given, until treatment (`treat`) lets it up; those where
it was and at its home are told, and a checkpoint keeps it so.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from world.body import Activity
from world.clock import DAY, clock_time, tell_moment
from world.config import Band
from world.events import EXHAUSTED, Bedridden, Idle, Movement, Sleep, Work
from world.telling import amount, cap, longest_sleep, you

if TYPE_CHECKING:
    from world.world import Resident, Tell, World


def reckon(world: World, r: Resident) -> None:
    """Bring `r`'s body up to the moment at the rates of what it has been doing since it was
    last reckoned, counting its time on duty, let it eat from its stock if
    it is awake and could eat, and note each need that crossed into another band, telling `r`
    if it is awake at a place; if `r` is at work and exhausted, its work stops."""
    now = world.clock.now()
    before = world.body.bands(r.living)
    home = world.config.place(r.home)
    assert home.comfort is not None
    world.body.elapse(r.living, now - r.reckoned, activity(world, r), home.comfort)
    if on_duty(r):
        r.worked += now - r.reckoned
    r.reckoned = now
    _feed(world, r)
    note_bands(world, r, before, tell=r.awake and r.place is not None)
    if isinstance(r.base, Work) and world.body.lowest("energy", r.living.energy):
        _exhausted(world, r)


def _exhausted(world: World, r: Resident) -> None:
    """`r`, found exhausted at work, stops work as `leave_work` stops it and is told that it
    cannot work until it has slept, and which task it still holds."""
    r.base = Idle()
    told = world.stopped_told(r, EXHAUSTED)
    world.record(
        "leave_work",
        lambda w: told if w == r.name else f"{r.name} stopped work, exhausted.",
        actor=r,
        audience=[r],
    )


def on_duty(r: Resident) -> bool:
    """Whether `r`'s hours at work are running: at work, which one enters only at one's own
    workplace and, unless one's duty runs anywhere (`Occupation.duty`), leaves by leaving it;
    or on one's way at work, the duty running."""
    return isinstance(r.base, Work) or (isinstance(r.base, Movement) and r.base.working)


def activity(world: World, r: Resident) -> Activity:
    """What `r`'s body is doing now, for the rates of the hours."""
    if isinstance(r.base, Work):
        return "work"
    if isinstance(r.base, Movement):
        return "walk"
    if r.suspended:
        return "sleep"
    return "awake"


def _feed(world: World, r: Resident) -> None:
    """Awake and able to eat, `r` eats the ready food in its inventory, a helping at a time,
    until it could eat no more."""
    if not r.awake:
        return
    for item in world.config.items:
        while item.ready and world.body.hungry(r.living) and r.inventory.units(item.id):
            eat(world, r, item.id, 1)


def note_bands(world: World, r: Resident, before: dict[str, Band], *, tell: bool) -> None:
    """Log each need of `r` whose band is no longer `before`'s, in the band's words, and
    tell `r` so if `tell` (a result, the wake-up or the statement tells it otherwise)."""
    for name, band in world.body.bands(r.living).items():
        if band is before[name]:
            continue
        world.record(
            "condition",
            lambda w, band=band: (
                f"You are {band.name}." if w == r.name else f"{r.name} is {band.name}."
            ),
            actor=r,
            audience=[r] if tell else [],
            payload={
                "need": name,
                "band": band.name,
                "value": round(getattr(r.living, name), 1),
                "lowest": band is world.body.need(name).lowest,
            },
        )


def nourishment(world: World, r: Resident) -> int:
    """What `r` has eaten since the last midnight, as nourishment: the one measure of
    whether it has eaten today."""
    return sum(_food(world, item) * units for item, units in r.living.eaten.items())


def _food(world: World, item: str) -> int:
    """What a helping of the ready food `item`, or a portion of the dish `item`, gives."""
    nourishment = world.config.item(item).nourishment
    assert nourishment
    return nourishment


def eat(world: World, r: Resident, item: str, units: int = 1) -> None:
    """`r` eats `units` of the ready food or the dish `item` it holds: they go out of its
    inventory into nothing, today's record grows and its satiety rises. Logged; told to
    nobody, since a result or the statement tells it."""
    world.moved(world.move(item, units, r.name, None, by=r))
    r.living.eaten[item] = r.living.eaten.get(item, 0) + units
    world.body.eat(r.living, _food(world, item) * units)
    eaten = amount(world.config.item(item), units)
    world.record_move(
        "eat",
        lambda w: f"{cap(you(r.name, w))} ate {eaten}.",
        by=r,
        item=item,
        units=units,
        source=r.name,
    )


def take_in(world: World, r: Resident, *, tell: bool = False) -> None:
    """`r` has just been handed something: the ready food it could eat is eaten at once, and
    each need that crossed into another band is noted, told to it if `tell` (a result tells
    one who took it itself)."""
    before = world.body.bands(r.living)
    _feed(world, r)
    note_bands(world, r, before, tell=tell)


def take_to_bed(world: World, r: Resident, day: int) -> None:
    """`r`'s health has reached its floor at the midnight that ends calendar day `day`: it
    takes to its bed at home, carried there if it was elsewhere, and keeps to it until
    treated. It leaves its conversation and its work and keeps its task; one in bed or
    asleep already is bedridden on waking. It is told, and so are those where it was and
    those at its home."""
    r.living.bedridden = True
    origin = r.place
    witnesses = world.addressable(r)
    world.break_off(r)
    carried = False
    if not isinstance(r.base, Sleep):
        if r.timer is not None:  # on the road: the arrival never comes
            r.timer.cancel()
            r.timer = None
        carried = origin != r.home
        r.place, r.base = r.home, Bedridden()
        witnesses += [other for other in world.addressable(r) if other not in witnesses]
    how = "were carried home to bed" if carried else "took to your bed"
    told = f"You are too ill to go on: you {how}, and keep to it until you are treated."
    seen = (
        f"{r.name} was carried home to bed, too ill to go on."
        if carried
        else f"{r.name} took to bed, too ill to go on."
    )
    claim = world.board.claims.get(r.name)
    world.record(
        "bedridden",
        lambda w: told if w == r.name else seen,
        actor=r,
        place=r.home,
        audience=[r, *witnesses],
        payload={
            "day": day,
            "home": r.home,
            "from": origin,
            "carried": carried,
            "task": claim.task if claim else None,
        },
    )


def treat(world: World, r: Resident, restores: float) -> None:
    """Treatment restores `restores` of `r`'s health, ends its illness and, if `r` was
    bedridden, lets it up, Idle at its home; either is logged as `recovered`, told to it
    and, out of bed, to those there. The doctor's treatment, at the Hospital or at a
    patient's bedside, calls this."""
    reckon(world, r)
    ill, bedridden = bool(r.living.ill), r.living.bedridden
    world.body.treat(r.living, restores)
    r.living.bedridden = False
    if isinstance(r.base, Bedridden):
        r.base = Idle()
    if not (ill or bedridden):
        return
    world.record(
        "recovered",
        lambda w: (
            (
                "You are well enough to leave your bed."
                if w == r.name
                else f"{r.name} is well enough to get up."
            )
            if bedridden
            else ("Your illness is over." if w == r.name else f"{r.name} is well again.")
        ),
        actor=r,
        audience=[r, *world.addressable(r)] if bedridden else [r],
        payload={
            "illness": ill,
            "bedridden": bedridden,
            "treated": True,
            "health": round(r.living.health, 1),
        },
    )


def go_to_bed(world: World, r: Resident, hour: int, journal: str | None, day: int) -> str:
    """`r` goes to bed, to wake at `hour` (seconds after midnight) or when its longest sleep
    ends, with the day's entry in its journal if it wrote one, and returns what `sleep`
    answers. Going to bed from elsewhere, it is told in bed what it may still do; from bed,
    the answer alone tells the hour it will wake, so that with nothing more to read it falls
    asleep at its next wait."""
    in_bed = isinstance(r.base, Sleep)
    wake, longest = _wake_time(world, hour)
    put_to_sleep(world, r, wake, longest=longest)
    until = f"You are in bed and will wake at {clock_time(wake)}"
    if longest:
        until += f", since you cannot sleep longer than {longest_sleep(world.config.day)}"
    kept = "; your journal entry for today is kept" if journal else ""
    parts = [f"{until}{kept}."]
    if not in_bed:
        parts.append(
            "Before you fall asleep you can look back over your day and see to your files; "
            "you fall asleep once you have nothing more to do."
        )
    told = " ".join(parts)
    wrote = " and wrote in the journal" if journal else ""
    world.record(
        "sleep",
        lambda w: told if w == r.name else f"{r.name} went to bed{wrote}.",
        actor=r,
        audience=[] if in_bed else [r],
        payload={"journal": journal, "day": day, "wake": wake},
    )
    return told if in_bed else "You went to bed."


def _wake_time(world: World, hour: int) -> tuple[int, bool]:
    """When a resident who goes to bed now, asking to wake at `hour` (seconds after
    midnight), wakes, and whether its body wakes it before that hour: at the next time the
    clock shows that hour, an hour at or before the present one meaning tomorrow, or when
    the longest sleep ends, if that is sooner. Everyone must be asleep from the forced sleep
    to the checkpoint, so a waking in between becomes the checkpoint's."""
    now = world.clock.now()
    wake = now - now % DAY + hour
    if wake <= now:
        wake += DAY
    longest = wake - now > world.sleep_at_most
    wake = min(wake, now + world.sleep_at_most)
    night = world.lived_day() * DAY
    if night + world.forced_sleep <= wake < night + world.checkpoint_hour:
        wake = night + world.checkpoint_hour
    return wake, longest


def put_to_sleep(
    world: World, r: Resident, wake: int, suspended: bool = False, longest: bool = False
) -> None:
    """`r` sleeps until `wake`, which replaces any hour it was to wake at before; `longest`
    whether that is when its longest sleep ends, before the hour it gave."""
    reckon(world, r)
    if r.timer is not None:
        r.timer.cancel()
    r.base = Sleep(wake, suspended, longest)
    r.timer = world.at(wake, partial(_wake_up, world, r))


def fall_asleep(world: World, r: Resident) -> None:
    """`r`, in bed, has nothing more to do: it falls asleep until its wake-up."""
    _fall_asleep(world, r, None)
    world.record(
        "fell_asleep",
        lambda w: f"{cap(you(r.name, w))} fell asleep.",
        actor=r,
        payload={"forced": False},
    )


def _fall_asleep(world: World, r: Resident, told: str | None) -> None:
    if told is not None:  # told before the resident is suspended, so that it hears it
        world.record(
            "fell_asleep",
            lambda w: told if w == r.name else f"{r.name} fell asleep.",
            actor=r,
            audience=[r],
            payload={"forced": True},
        )
    assert isinstance(r.base, Sleep)
    reckon(world, r)
    r.base.suspended = True
    r.wait_minutes = None
    r.port.disarm_tick()
    world.rest_changed()


def _wake_up(world: World, r: Resident, tell: Tell | None = None) -> None:
    """`r` wakes at home, at its hour, when its longest sleep ends or, told `tell`, woken
    by the town, eats from its stock if it could, and is told what shape it is in."""
    reckon(world, r)
    longest = isinstance(r.base, Sleep) and r.base.longest
    r.timer = None
    r.base, r.place = (Bedridden() if r.living.bedridden else Idle()), r.home
    before = world.body.bands(r.living)
    _feed(world, r)
    note_bands(world, r, before, tell=False)
    r.port.release()
    moment = tell_moment(world.clock.now(), world.config.start_date)
    could = " could sleep no longer and" if longest else ""
    woke = tell or (lambda w: f"{cap(you(r.name, w))}{could} woke up at home. It is {moment}.")
    shape = world.body.condition(r.living)
    world.record(
        "wake",
        lambda w: f"{woke(w)} {shape}" if w == r.name else woke(w),
        actor=r,
        audience=[r],
    )
    world.rest_changed()


def force_sleep(world: World, day: int) -> None:
    """The night's end of calendar day `day`: whoever is up falls asleep where it is, to wake
    at home at the forced waking hour; one in bed falls asleep there."""
    wake = day * DAY + world.forced_wake
    hour = clock_time(world.clock.now())
    for r in world.residents.values():
        if isinstance(r.base, Sleep):
            if not r.base.suspended:
                _fall_asleep(world, r, f"It is {hour}: you fell asleep.")
            continue
        if isinstance(r.base, Bedridden):  # in bed already
            world.break_off(r)
            put_to_sleep(world, r, wake)
            _fall_asleep(world, r, f"It is {hour}: you fell asleep.")
            continue
        world.break_off(r)
        if r.timer is not None:
            r.timer.cancel()
        again = " again" if _went_to_bed(world, r) else ""
        world.record(
            "forced_sleep",
            lambda w, r=r, again=again: (
                f"It is {hour}: {you(r.name, w)} fell asleep without going to bed{again}, and "
                f"will wake at home at {clock_time(wake)}."
            ),
            actor=r,
            audience=[r],
            payload={"wake": wake},
        )
        r.place = r.home
        put_to_sleep(world, r, wake)
        _fall_asleep(world, r, None)


def _went_to_bed(world: World, r: Resident) -> bool:
    """Whether `r` has gone to bed in the day being lived."""
    return any(kind == "sleep" for _, kind, _, _ in r.day)
