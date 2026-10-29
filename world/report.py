"""The town's report, as the mayor reads it at the Town Hall, and the fund's day within it: the
fund and its tax account, the days the daybook has closed and today so far, the residents as the
town sees them, and the announcements standing on the Hall's board.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from world.businesses import BUSINESSES, offered
from world.clock import tell_date, tell_moment
from world.economy import PAID, TAKEN, TAX, TAX_WAGE
from world.telling import cap, duration, listed

if TYPE_CHECKING:
    from world.world import World


def report(world: World) -> str:
    """The town's report, as the mayor reads it at the Town Hall: what the fund and its tax
    account hold and their day before (`fund_report`); the last seven days the daybook has
    closed, a line each (the fund's balance and how it moved, the tasks accepted, the sales,
    the dishes served, the patients); today so far (the Office's open tasks and who holds
    them, the Store's shelves and the menu, what was accepted, sold, served and seen today);
    each resident's occupation, time at work the day before and health as others see it,
    whether it is ill and whether it is in bed; and the announcements standing. No purse is
    in it."""
    c, book = world.config, world.daybook
    parts = [f"The town's report, {tell_moment(world.clock.now(), c.start_date)}."]
    parts.append(f"The fund. {fund_report(world)}")
    week = [f"{tell_date(d['day'], c.start_date)}: {_day_told(world, d)}" for d in book.days]
    parts.append(
        "The last days, as each closed at midnight:\n" + "\n".join(week)
        if week
        else "No day has closed yet."
    )

    held = {claim.task: name for name, claim in world.board.claims.items()}
    open_tasks = [
        f"task {n} ({world.board.task(n).repo}), "
        + (f"held by {held[n]}" if n in held else "held by nobody")
        for n in sorted(world.board.open)
    ]
    today = [
        f"{cap(c.workplace('office').name)}. Open on the board: "
        f"{'; '.join(open_tasks) or 'nothing'}.",
        *[
            f"{cap(b.place(c).name)}. {cap(b.listing + offered(world, b))}"
            for b in BUSINESSES.values()
        ],
        f"So far today: {_day_told(world, book.today, closed=False)}",
    ]
    parts.append("Today.\n" + "\n".join(today))

    yesterday = book.yesterday
    people = []
    for r in world.residents.values():
        worked = duration(yesterday["hours"].get(r.name, 0))
        line = f"{r.name}, {r.occupation.title}: {worked or 'no time'} at work yesterday"
        if r.living.bedridden:
            line += ", in bed, too ill to get up"
        elif (looks := world.body.seen(r.living)) is not None:
            line += f", {looks}"
        if r.living.ill:
            line += ", ill"
        people.append(line + ".")
    parts.append("The residents. " + " ".join(people))
    parts.append(f"{cap(c.workplace('hall').name)}. {hall_board(world)}")
    return "\n\n".join(parts)


def _day_told(world: World, day: dict[str, Any], *, closed: bool = True) -> str:
    """A day of the daybook in a line of the report: for a `closed` day, the fund's balance
    at its midnight and how the day moved it; the tasks accepted, by whom; what the Store
    sold; the dishes served; the patients the doctor saw."""
    money = world.config.money
    told = []
    if closed:
        net = day["net"]
        moved = f"up {money(net)}" if net > 0 else f"down {money(-net)}" if net < 0 else "even"
        told.append(f"the fund held {money(day['fund'])} at midnight, {moved} on the day")
    accepted = [f"task {task} by {name}" for name, task in day["accepted"]]
    seen: dict[str, list[str]] = {}
    for name, service in day["patients"]:
        seen.setdefault(name, []).append(service)
    patients = [f"{name} ({listed(services)})" for name, services in seen.items()]
    told += [
        f"accepted {listed(accepted) or 'nothing'}",
        f"sold {listed(world.held_told(day['sales'])) or 'nothing'}",
        f"served {listed(world.held_told(day['dishes'])) or 'nothing'}",
        f"{listed(patients) or 'nobody'} seen at {world.config.workplace('hospital').name}",
    ]
    return "; ".join(told) + "."


def fund_report(world: World) -> str:
    """The fund's day, as the town tells it: what the fund holds, what it took in and paid
    out by kind on the day the last midnight closed, the same of its tax account, what it
    owes in wages and who owes it rent."""
    fund, money = world.fund, world.config.money
    day = fund.yesterday
    took = [f"{money(day[kind])} {words}" for kind, words in TAKEN.items() if kind in day]
    paid = [f"{money(day[kind])} {words}" for kind, words in PAID.items() if kind in day]
    parts = [
        f"The fund holds {money(fund.balance)}, before tonight's wages and taxes.",
        f"Yesterday it took in {listed(took) or 'nothing'} and paid out "
        f"{listed(paid) or 'nothing'}.",
        f"Its tax account holds {money(fund.taxes)}; yesterday it took in "
        f"{money(day.get(TAX, 0))} in taxes and paid out {money(day.get(TAX_WAGE, 0))} in "
        "wages.",
    ]
    if fund.owed:
        owed = listed([f"{name} {money(amount)}" for name, amount in fund.owed.items()])
        parts.append(f"It owes in wages it could not pay: {owed}.")
    if fund.arrears:
        owing = listed([f"{name} {money(amount)}" for name, amount in fund.arrears.items()])
        parts.append(f"Owing rent the wages did not cover: {owing}.")
    return " ".join(parts)


def hall_board(world: World) -> str:
    """The announcements standing on the Town Hall's board, each with when it was made."""
    if not world.announcements:
        return "Nothing is posted on the board."
    lines = [
        f"{tell_moment(int(t), world.config.start_date)}: “{text}”"
        for t, text in world.announcements
    ]
    return "On the board, the mayor's announcements:\n" + "\n".join(lines)
