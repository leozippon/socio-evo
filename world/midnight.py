"""Midnight, the end of a calendar day: every resident settled (its body brought up to the hour,
its health moved by the day, its illness passing or coming, its wages paid with its tax, rent and
daily charges taken out of them, and its statement told), the fund's day and the daybook's closed,
the clients' withdrawals, what perishes gone wherever it is, and the next day's arrivals drawn.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict
from typing import TYPE_CHECKING

from world import office
from world.businesses import KITCHEN
from world.clock import tell_date
from world.config import A_DAYS_FOOD, Item, Place
from world.economy import MOVES, PORTIONS, Inventory, Settled
from world.occupations import TEAM_LEADER
from world.telling import amount, bare, duration, listed

if TYPE_CHECKING:
    from world.world import Resident, World


def midnight(world: World, day: int) -> None:
    """The end of calendar day `day`: its food, its health and illness reckoned, its wages
    paid with the rent and charges taken out of them, the tasks whose time runs out with it
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
    """Midnight for every resident, in the configuration's order but with those paid from
    the tax account last, once the day's taxes are in it: its body is brought up to the hour
    and its health moves by the day (a resident whose health has reached its floor takes to
    its bed here), its illness passes or comes (`_illness`), the day's food is reckoned, its
    wages for its time at work are paid with its tax, rent and daily charges taken out of
    them (`Fund.settle`: the tax is `town.tax` of the day's wages and the sums paid it that
    day, to the nearest whole, and what the wages leave of it is paid from the purse, or
    owed; when the fund runs short, those settled first are paid first), and the statement
    is told, the team leader's with the Office's day (`office.day_told`); then the fund's day
    and the daybook's are closed."""
    date, money = tell_date(day, world.config.start_date), world.config.money
    hours: dict[str, int] = {}
    residents = sorted(world.residents.values(), key=lambda r: r.occupation.paid_from == "taxes")
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
        wages = r.worked * r.occupation.wage_per_hour // 3600
        sums = sum(int(paid) for kind, paid, _ in inventory.moves if kind == "service")
        settled = world.fund.settle(
            r.name,
            wages=wages,
            tax=math.floor(world.config.tax * (wages + sums) + 0.5),
            purse=inventory.money,
            rent=home.rent,
            charges=sum(item.fee_per_day for item in charged),
            from_taxes=r.occupation.paid_from == "taxes",
        )
        held = inventory.money
        inventory.money += settled.paid - settled.tax_from_purse
        world.record(
            "wage",
            lambda w, r=r, held=held, paid=settled.paid, taxed=settled.tax_from_purse: (
                f"At midnight your purse held {money(held)}"
                + (
                    f", and {money(paid)} of your wages went into it."
                    if paid
                    else f", and {money(taxed)} of it went in tax."
                    if taxed
                    else "; none of your wages went into it."
                )
                if w == r.name
                else f"{r.name} was paid {money(paid) if paid else 'nothing'} at midnight."
            ),
            actor=r,
            place=None,
            payload={
                "hours": round(r.worked / 3600, 2),
                **asdict(settled),
                "money": inventory.money,
            },
        )
        nourishment = world.nourishment(r)
        eaten = [_eaten(world, item, units) for item, units in living.eaten.items()]
        food = (
            f"You ate today: {listed(eaten)}." if nourishment else "You had nothing to eat today."
        )
        moves = _moves_told(world, inventory)
        items = moves + _wages_told(world, r, settled, home, charged)
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
    world.daybook.close_day(day, hours, world.fund)
    world.fund.close_day()


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
    in their order, the same movement told once with how many times it was made."""
    times: dict[tuple[str, int, str], int] = {}
    for kind, paid, about in inventory.moves:
        key = (str(kind), int(paid), str(about))
        times[key] = times.get(key, 0) + 1
    return [
        MOVES[kind].format(money=world.config.money(paid), about=about)
        + (f", {n} times" if n > 1 else "")
        for (kind, paid, about), n in times.items()
    ]


def _wages_told(
    world, r: Resident, settled: Settled, home: Place, charged: list[Item]
) -> list[str]:
    """The statement's items on `r`'s wages as `settled` at midnight: its time at work and
    what it earned, what its payer (the fund, or the tax account) owed it, the tax, the rent
    for its room at `home`, the daily charges on the items `charged` and the rent it owed,
    and what came of them."""
    worked = duration(r.worked)
    money = world.config.money
    payer = "the tax account" if r.occupation.paid_from == "taxes" else "the fund"
    items = [f"{worked} at work, {money(settled.wages)} in wages" if worked else "no time at work"]
    if settled.owed_before:
        items.append(f"{money(settled.owed_before)} {payer} owed you")
    tax, from_purse = settled.tax, settled.tax_from_purse
    if tax:
        items.append(
            f"tax on the day's earnings {money(tax)}"
            + (", paid from your purse" if from_purse == tax else "")
            + (f", {money(from_purse)} of it from your purse" if 0 < from_purse < tax else "")
        )
    items.append(f"rent for your room at {home.name} {money(settled.rent)}")
    items += [f"the daily charge on {item.name} {money(item.fee_per_day)}" for item in charged]
    if settled.arrears_before:
        items.append(f"{money(settled.arrears_before)} of rent you owed")
    left, paid, owed, arrears = settled.remainder, settled.paid, settled.owed, settled.arrears
    if owed and arrears:  # the tax account short even of what the rent took
        items.append(
            f"{payer} could not pay {money(owed)} of your wages and owes it to you, and what "
            f"it paid fell {money(arrears)} short of that; you owe it, and it is taken from "
            "your next wages"
        )
    elif left < 0:
        items.append(
            f"your wages fell {money(-left)} short of that; you owe it, and it is taken from "
            "your next wages"
        )
    elif not left:
        items.append("nothing left of your wages")
    elif paid == left:
        items.append(f"{money(left)} left of your wages, paid into your purse")
    elif paid:
        items.append(
            f"{money(left)} left of your wages, of which {money(paid)} paid into your purse; "
            f"{payer} could not pay the other {money(owed)} and owes it to you"
        )
    else:
        items.append(f"{money(left)} left of your wages, which {payer} could not pay and owes you")
    return items
