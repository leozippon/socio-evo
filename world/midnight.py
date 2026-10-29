"""Midnight, the end of a calendar day: every resident settled (its body brought up to the hour,
its health moved by the day, its illness passing or coming, its salary paid if it has one and its
rent and daily charges taken by the treasury, and its statement told), the treasury's day and the
daybook's closed, the clients' withdrawals, what perishes gone wherever it is, and the next day's
arrivals drawn.
"""

from __future__ import annotations

import random
from dataclasses import asdict
from typing import TYPE_CHECKING

from world import office
from world.businesses import KITCHEN
from world.clock import tell_date
from world.config import A_DAYS_FOOD, Item, Place
from world.economy import MOVES, PORTIONS, Inventory, Settled
from world.occupations import TEAM_LEADER
from world.telling import amount, bare, listed

if TYPE_CHECKING:
    from world.world import Resident, World


def midnight(world: World, day: int) -> None:
    """The end of calendar day `day`: its food, its health and illness reckoned, the salary paid
    and the rent and charges taken, the tasks whose time runs out with it
    withdrawn, what perishes gone wherever it is (the portions the kitchen did not sell), and
    the next day's arrivals drawn."""
    _settle(world, day)
    office.withdrawals(world, day)
    for key in [*world.residents, *world.holders]:
        held = world.holder(key).items
        for item in [item for item in held if world.config.item(item).perishes]:
            world.moved(world.move(item, held[item], key, None))
    world.board.schedule = world.board.draw(day + 1)


def _settle(world: World, day: int) -> None:
    """Midnight for every resident, in the configuration's order but with the salaried last,
    once the day's rents are in the treasury: its body is brought up to the hour and its health
    moves by the day (a resident whose health has reached its floor takes to its bed here), its
    illness passes or comes (`_illness`), the day's food is reckoned, its salary is paid and its
    rent, daily charges and arrears are taken from its purse above what it spares
    (`Treasury.settle`), and the statement is told, the team leader's with the Office's day
    (`office.day_told`); then the daybook's day and the treasury's are closed."""
    date = tell_date(day, world.config.start_date)
    hours: dict[str, int] = {}
    residents = sorted(world.residents.values(), key=lambda r: r.occupation.salary > 0)
    for r in residents:
        world.reckon(r)
        living, inventory = r.living, r.inventory
        home = world.config.place(r.home)
        assert home.rent is not None and home.comfort is not None
        before = world.body.bands(living)
        was_ill = living.ill
        night = world.body.night(living, home.comfort)
        if living.health <= 0 and not living.bedridden:
            world.take_to_bed(r, day)
        illness = _illness(world, r, day, was_ill, home.comfort)
        world.note_bands(r, before, tell=False)
        stock = []
        for item in world.config.items:
            if item.dish or not item.ready or not living.eaten.get(item.id):
                continue
            assert item.nourishment
            left = inventory.units(item.id)
            if not left:
                stock.append(f"You have used up your {bare(item.name)}.")
            elif left * item.nourishment < A_DAYS_FOOD:  # less than a day's food
                stock.append(f"You have {amount(item, left)} left.")
        unsold = world.held_told(world.holders[PORTIONS].items)
        if KITCHEN.keeps(r.occupation.id) and unsold:
            stock.append(f"What the kitchen did not sell is gone: {listed(unsold)}.")
        charged = [i for i in world.config.items if i.fee_per_day and inventory.units(i.id)]
        settled = world.treasury.settle(
            r.name,
            purse=inventory.money,
            spares=world.config.treasury.spares,
            salary=r.occupation.salary,
            rent=home.rent,
            charges=sum(item.fee_per_day for item in charged),
        )
        inventory.money += settled.salary_paid - settled.rent_paid
        nourishment = world.nourishment(r)
        eaten = [_eaten(world, item, units) for item, units in living.eaten.items()]
        food = (
            f"You ate today: {listed(eaten)}." if nourishment else "You had nothing to eat today."
        )
        items = _moves_told(world, inventory) + _settled_told(world, settled, home, charged)
        office_day = [office.day_told(world, r, day)] if r.occupation.id == TEAM_LEADER else []
        statement = " ".join(
            [f"Your statement for {date}: {'; '.join(items)}.", food, *stock]
            + ([illness] if illness else [])
            + [world.body.condition(living), world.purse(r), *office_day]
        )
        world.record(
            "settlement",
            lambda w, r=r, statement=statement: (
                statement if w == r.name else f"{r.name} was told the midnight statement."
            ),
            actor=r,
            place=None,
            audience=[r],
            payload={
                "hours": round(r.worked / 3600, 2),
                **asdict(settled),
                "money": inventory.money,
                "nourishment": nourishment,
                "satiety": round(living.satiety, 1),
                "energy": round(living.energy, 1),
                "health": round(living.health, 1),
                "night": night,
                "ill": living.ill,
            },
        )
        hours[r.name] = r.worked
        living.eaten, inventory.moves, r.worked = {}, [], 0
    world.daybook.close_day(day, hours, world.treasury)
    world.treasury.close_day()


def _illness(world: World, r: Resident, day: int, was_ill: int, comfort: float) -> str | None:
    """`r`'s illness at the midnight that ends calendar day `day`, its night reckoned: one
    ill before it (`was_ill`) whose nights are over is well again; one well, with health
    left, falls ill by the chance of its health and its home (of `comfort`), drawn from the
    run's seed, the day and its name. Logged, told by the statement: what it tells, if
    anything."""
    living = r.living
    if was_ill:
        if living.ill:
            return None
        world.record(
            "recovered",
            lambda w: "Your illness has passed." if w == r.name else f"{r.name} is well again.",
            actor=r,
            place=None,
            payload={
                "illness": True,
                "bedridden": False,
                "treated": False,
                "health": round(living.health, 1),
            },
        )
        return "Your illness has passed."
    if living.bedridden:
        return None
    chance = world.body.illness_chance(living, comfort)
    if random.Random(f"{world.config.seed}:illness:{day}:{r.name}").random() >= chance:
        return None
    world.body.fall_ill(living)
    world.record(
        "illness",
        lambda w: "You have fallen ill." if w == r.name else f"{r.name} fell ill.",
        actor=r,
        place=None,
        payload={
            "chance": round(chance, 4),
            "nights": living.ill,
            "health": round(living.health, 1),
        },
    )
    return "You have fallen ill."


def _eaten(world: World, item: str, units: int) -> str:
    """`units` of the ready food or the dish `item`, as the statement tells what was eaten."""
    return amount(world.config.item(item), units)


def _moves_told(world: World, inventory: Inventory) -> list[str]:
    """The statement's items on the movements of `inventory`'s money since the last midnight,
    in their order: what it earned summed by what for, with the tax withheld from it; any other
    movement told once with how many times it was made."""
    money = world.config.money
    earned: dict[str, list[int]] = {}  # what for: [earned, tax]
    times: dict[tuple[str, int, str], int] = {}
    for kind, paid, about in inventory.moves:
        if kind in ("earned", "tax"):
            sums = earned.setdefault(str(about), [0, 0])
            sums[kind == "tax"] += int(paid)
            continue
        key = (str(kind), int(paid), str(about))
        times[key] = times.get(key, 0) + 1
    told = [
        MOVES["earned"].format(money=money(gross), about=about)
        + (f", {MOVES['tax'].format(money=money(tax))}" if tax else "")
        for about, (gross, tax) in earned.items()
    ]
    return told + [
        MOVES[kind].format(money=money(paid), about=about) + (f", {n} times" if n > 1 else "")
        for (kind, paid, about), n in times.items()
    ]


def _settled_told(world: World, settled: Settled, home: Place, charged: list[Item]) -> list[str]:
    """The statement's items on what midnight `settled`: the salary and what the treasury owed,
    and what came of them; the rent for the room at `home`, the daily charges on the items
    `charged` and the rent owed, and what the purse paid of them."""
    money, spares = world.config.money, world.config.treasury.spares
    items = []
    if settled.salary or settled.owed_before:
        due = f"your salary {money(settled.salary)}" + (
            f" and {money(settled.owed_before)} the treasury owed you"
            if settled.owed_before
            else ""
        )
        if not settled.owed:
            items.append(f"{due}, paid into your purse")
        elif settled.salary_paid:
            items.append(
                f"{due}, of which the treasury paid {money(settled.salary_paid)} into your purse "
                f"and owes you the other {money(settled.owed)}"
            )
        else:
            items.append(f"{due}, which the treasury could not pay and owes you")
    owing = [f"rent for your room at {home.name} {money(settled.rent)}"]
    owing += [f"the daily charge on {item.name} {money(item.fee_per_day)}" for item in charged]
    if settled.arrears_before:
        owing.append(f"{money(settled.arrears_before)} of rent you owed")
    later = "taken from your purse at a later midnight"
    kept = f"the {money(spares)} it keeps for your bread"
    if not settled.arrears:
        owing.append(f"your purse paid {'all of it' if len(owing) > 1 else 'it'}")
    elif settled.rent_paid:
        owing.append(
            f"your purse paid {money(settled.rent_paid)} of it, all it held above {kept}; you "
            f"owe the other {money(settled.arrears)}, {later}"
        )
    else:
        owing.append(
            f"your purse paid none of it, holding no more than {kept}; you owe "
            f"{money(settled.arrears)}, {later}"
        )
    return items + owing
