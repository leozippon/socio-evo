"""The standing rules of the town, as one resident is told them, and `help` by topic.

The rules are derived from the configuration and from who lives where, which the world passes
in as it stands: a move changes the homes, the free rooms and one's own rent, and nothing else
in them changes during a run. They are part of the system prompt. They describe
what can be done and what follows from it, in plain words, and nothing else: not the length of
the run, not the machinery, not how anyone ought to behave. Their sections (`TOPICS`) tell a
resident its own occupation and workplace first and the others' in a sentence; `help` tells the
same paragraphs on one topic, and on the work of each workplace (`DETAILS`) the detail the
rules leave out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import partial

from world import economy
from world.clock import parse_hour
from world.config import A_DAYS_FOOD, DayHours, Good, TownConfig
from world.telling import cap, counted, duration, listed

TOPICS = ("places", "day", "work", "money", "shopping", "health", "people", "sleep")
DETAILS = ("office", "store", "restaurant")
"""The topics `help` tells beyond the rules: how the work at each workplace goes."""
MAX_WAIT_MINUTES = 600
"""The longest a resident can ask to wait, in minutes: the bound of `wait`, told in the rules."""
_HEADINGS = {
    "places": "Places",
    "day": "The day",
    "work": "Work",
    "money": "Money",
    "shopping": "Shopping",
    "health": "Health",
    "people": "People",
    "sleep": "Sleep",
}
OWN_WORK = {
    "programmer": (
        "Clients' tasks are posted on its board: you claim one at a time, work on it there, "
        "where the machines are, and hand it in for the client's checks."
    ),
    "team-leader": (
        "You lead its programmers. Clients' tasks are posted on its board: like them, you can "
        "claim one at a time, work on it there, where the machines are, and hand it in for the "
        "client's checks."
    ),
    "chef": (
        "You cook dishes in its kitchen from what the kitchen holds, set the menu's prices and "
        "serve whoever comes while you are at work there. You buy what you cook with at {store}: "
        "start work there, and what you buy goes to the kitchen, paid by the fund."
    ),
    "shopkeeper": (
        "It is open while you are at work there: you sell its goods at the prices you set, and "
        "order more from the supplier, which the fund pays and which arrives the next morning."
    ),
    "doctor": "",
    "mayor": "",
}
"""What each occupation's work is, told to the resident who has it after its workplace."""
SERVICE = {
    "programmer": "for each task of yours accepted",
    "team-leader": "for each task of the programmers' accepted",
    "chef": "for each dish served",
    "shopkeeper": "for each sale",
    "doctor": "for each patient examined or treated",
    "mayor": "for each service",
}
"""What each occupation's sum per service is paid for, as the money rules tell it."""
Homes = Mapping[str, Sequence[str]]
"""Who lives where: the names of the residents of each home, by the home's id."""


def bare(name: str) -> str:
    """A good's name without its article: `a phone` is `phone`."""
    for article in ("a ", "an ", "the "):
        if name.startswith(article):
            return name[len(article) :]
    return name


def amount(good: Good, units: int) -> str:
    """`units` of `good` as a sentence names them: `a phone`, `2 phones`, `3 helpings of bread`,
    `4 units of rice`."""
    if good.kind == "durable":
        return good.name if units == 1 else counted(units, bare(good.name))
    return f"{counted(units, 'helping' if good.ready else 'unit')} of {bare(good.name)}"


def fraction(factor: float) -> str:
    """`half`, `a quarter of`, `70% of`: the share of the time a journey takes."""
    if factor == 0.5:
        return "half"
    if factor == 0.25:
        return "a quarter of"
    return f"{round(factor * 100)}% of"


def comfort_word(comfort: float) -> str | None:
    """How a home's comfort is told beside its rent: `little comfort` below an ordinary home's,
    `comfortable` above it, nothing for an ordinary home."""
    if comfort < 1:
        return "little comfort"
    if comfort > 1:
        return "comfortable"
    return None


def longest_sleep(day: DayHours) -> str:
    """How long one sleep lasts at most, told: `12 hours`."""
    return duration(parse_hour(day.sleep_at_most))


class Rules:
    def __init__(self, config: TownConfig) -> None:
        self.config = config

    def text(self, name: str, homes: Homes | None = None) -> str:
        """The whole of the rules told to `name`, with `homes` as they stand (at the start if not
        given)."""
        sections = self.sections(name, homes)
        body = "\n\n".join(f"{_HEADINGS[topic]}. {sections[topic]}" for topic in TOPICS)
        return f"How the town works.\n\n{body}"

    def help(self, name: str, topic: str, homes: Homes | None = None) -> str:
        """The rules on `topic`, with `homes` as they stand now, the detail of a workplace's
        work, or the list of topics."""
        key = topic.strip().lower()
        if key in DETAILS:
            return self.details()[key]
        sections = self.sections(name, homes)
        if key in sections:
            return sections[key]
        return f"You can ask about: {', '.join((*TOPICS, *DETAILS))}."

    def homes(self) -> dict[str, list[str]]:
        """Who lives where at the start."""
        c = self.config
        return {
            place.id: [r.name for r in c.residents if r.home == place.id]
            for place in c.places
            if place.kind == "home"
        }

    def sections(self, name: str, homes: Homes | None = None) -> dict[str, str]:
        """The rules by topic, told to `name`, with `homes` as they stand (at the start if not
        given)."""
        c = self.config
        me = next(resident for resident in c.residents if resident.name == name)
        homes = homes if homes is not None else self.homes()
        home_of = {who: place for place, people in homes.items() for who in people}
        my_home = c.place(home_of[name])
        occupation = c.occupation(me.occupation)
        workplace = c.place(occupation.workplace)
        office = c.workplace("office")
        social = c.social

        money = partial(economy.money, c.currency)
        names = listed([f"{place.name} ({place.id})" for place in c.places])
        routes = self._routes()
        rooms = []
        for place in c.places:
            if place.kind == "home":
                assert place.rooms is not None and place.rent is not None
                assert place.comfort is not None
                free = place.rooms - len(homes.get(place.id, ()))
                comfort = comfort_word(place.comfort)
                rooms.append(
                    f"{place.name} {money(place.rent)} ({counted(place.rooms, 'room')}, "
                    f"{free or 'none'} free{f', {comfort}' if comfort else ''})"
                )
        places = (
            f"The town has these places, each with the short name you use to go there: {names}. "
            f"Walking from one place to another takes {c.travel_minutes} minutes"
            + (f", except {routes}" if routes else "")
            + ". On the way you notice nothing of where you are going, and nobody can speak "
            f"to you. The homes, with the rent a day for a room and the rooms free: "
            f"{listed(rooms)}. Your home is {my_home.name}. At a home with a free room you can "
            "move in with move_in: you give up your old room, and the new rent is taken from "
            "the next midnight."
        )

        day = (
            "No place keeps hours: a place of work is open while someone is at work there. At "
            f"{c.day.board_posted} the day's board is posted at {office.name}; what is left of "
            "the day before's stays up until then. At midnight your wages for the day are paid, "
            "with your rent taken out of them, and your health is reckoned from the day. "
            "You go to bed at home at whatever hour you choose, giving the hour you want to "
            f"wake. At {c.day.forced_sleep} anyone still up falls asleep where it is and wakes "
            f"at home at {c.day.forced_wake}. When you do nothing, time passes until something "
            f"happens or {counted(c.clock.idle_minutes, 'minute')} have gone by, and you are "
            f"told the hour; with wait you let up to {counted(MAX_WAIT_MINUTES, 'minute')} pass."
        )

        own = OWN_WORK[occupation.id].format(store=c.workplace("store").name)
        work = " ".join(
            part
            for part in (
                f"You are {occupation.title} at {workplace.name}.",
                own,
                "You sit down to work there with start_work, or by doing your work, and are at "
                "work until you stop with leave_work, go elsewhere or go to sleep.",
                self._others(name),
                "With help you can ask how the work goes at the office, the store or the "
                "restaurant.",
            )
            if part
        )

        assert my_home.rent is not None
        fees = any(good.fee_per_day for good in c.supplier)
        sums = [f"{money(occupation.per_service)} at once {SERVICE[occupation.id]}"]
        if occupation.id == "team-leader":
            programmer = c.occupation("programmer")
            sums.append(f"{money(programmer.per_service)} for each task of your own accepted")
        paid = (
            f"you are paid {money(occupation.wage_per_hour)} an hour for your time at work "
            "there, from sitting down to work until you stop"
            + (f", and {listed(sums)}" if occupation.per_service else "")
        )
        money_rules = (
            f"You have {money(me.purse)} to begin with. The town keeps one fund, which takes in "
            "what clients pay for the work, the rent and what is sold, and pays everyone who "
            f"works. You are {occupation.title} at {workplace.name}: {paid}. At "
            "midnight your wages for the day are paid into your purse, with the rent for your "
            f"room at {my_home.name}, {money(my_home.rent)} a day"
            + (", and the daily charge on anything you own that carries one" if fees else "")
            + " taken out of them, and you get a statement of your money; what is in your purse "
            "is never touched by rent. When your wages do not cover the rent, you owe the rest, "
            "and it is taken from your next wages; when the fund cannot pay you, it owes you the "
            "rest and pays it with your next wages. You pay for everything in cash from your "
            "purse, and cannot pay more than it holds. With give you can hand money, a thing you "
            "own (with any daily charge on it) or food you keep to anyone awake where you "
            "are, as a gift or on terms you agree between you; the town keeps no account of it."
        )

        others = listed(
            [f"{r.name} ({c.place(home_of[r.name]).name})" for r in c.residents if r.name != name]
        )
        meeting = listed(
            [place.name for place in c.places if place.kind in ("social", "store", "restaurant")]
        )
        people = (
            f"The others who live in the town, with their homes: {others}. People run into one "
            f"another at {meeting}; you can also call on someone at home, or find them where "
            "they work. You can speak to anyone awake at the same place as you: to everyone "
            "there at once, or only to the people you name, and then the others notice that you "
            "said something but not what. A conversation lasts until its people leave it or "
            f"nobody speaks for {social.silence_minutes} minutes."
        )
        if me.ties:
            people += " Some of them you know already. " + " ".join(me.ties.values())

        sleep = (
            "Go to bed at home at any hour with sleep, giving the hour you want to wake and, if "
            "you write one, the day's entry in your own journal, which is kept in your journal "
            "folder; an entry given at a later bedtime the same day, or again from bed, is added "
            f"to that day's. You cannot sleep longer than {longest_sleep(c.day)} at a stretch: "
            "by then you wake, whatever hour you gave. In bed, before you fall asleep, you can "
            "look back over your day and see to your files."
        )
        return {
            "places": places,
            "day": day,
            "work": work,
            "money": money_rules,
            "shopping": self._shopping(),
            "health": self._health(),
            "people": people,
            "sleep": sleep,
        }

    def _others(self, name: str) -> str:
        """The others' occupations and workplaces, in a sentence."""
        c = self.config
        told = []
        for occupation in c.occupations:
            them = [r.name for r in c.residents if r.occupation == occupation.id and r.name != name]
            if not them:
                continue
            where = c.place(occupation.workplace).name
            if len(them) == 1:
                told.append(f"{them[0]} is {occupation.title} at {where}")
            else:
                told.append(f"{listed(them)} are {bare(occupation.title)}s at {where}")
        return f"In the town, {listed(told)}." if told else ""

    def details(self) -> dict[str, str]:
        """How the work goes at the office, the store and the restaurant, for `help`."""
        c = self.config
        money = partial(economy.money, c.currency)
        office, store = c.workplace("office"), c.workplace("store")
        restaurant = c.workplace("restaurant")
        # A claim runs out at the midnight that ends the day this many days after the day it
        # was made.
        days = c.work.claim_expiry_days
        nth = {0: "first", 1: "second"}.get(days)
        expiry = (
            f"at the {nth} midnight after you claimed it"
            if nth
            else f"when {days + 1} midnights have passed since you claimed it"
        )
        office_work = (
            f"{cap(office.name)} takes in programming work from clients elsewhere and posts "
            "it on its board there: each task is a code repository with a problem to fix, for "
            f"which the client pays the town {money(c.work.payment)} once it is accepted. The "
            "board shows the first line of each problem; there read_task gives you the whole of "
            "one without claiming it. Claim a task at the board and you get a workspace with its "
            "repository, where you can run commands and read and write files; there is no "
            f"internet. You work on it at {office.name}, where the machines are. When your fix "
            "is ready, hand it in with submit: the client's own checks, which you do not see, run "
            "on it in a clean copy of the repository, and if they pass the task is accepted and "
            "you are paid for it at once. You can hand in each task at most "
            f"{c.work.acceptance_runs} times a day. You hold at most one task at a time. You "
            "keep it wherever you go, and your "
            f"changes are kept overnight, but a claim runs out unpaid {expiry}. You cannot claim "
            "again a task you have been paid for. The programmers work from the same board; a "
            "task someone holds is shown as held, stays on the board from day to day while it "
            "is held, and nobody else can claim it; a task someone has been paid for leaves the "
            "board for the day."
        )
        shopkeeper = c.occupation("shopkeeper")
        store_work = (
            f"{cap(store.name)} sells while its shopkeeper is at work there; otherwise its door "
            "is shut. It sells from its stock, at the prices the shopkeeper sets, and what is "
            "sold out is gone until the shopkeeper orders more from the supplier outside the "
            f"town: the fund pays the supplier at once, and the goods arrive at {c.day.delivery} "
            "the next morning. An order the fund cannot pay for is refused. Each sale pays the "
            f"shopkeeper {money(shopkeeper.per_service)}. The chef, at work at {store.name}, "
            "buys for the kitchen, and the fund pays."
        )
        chef = c.occupation("chef")
        recipes = "; ".join(
            f"{dish.name} from "
            + listed([amount(c.good(good), units) for good, units in dish.ingredients.items()])
            for dish in c.dishes
        )
        restaurant_work = (
            f"The kitchen of {restaurant.name} serves while its chef is at work there, and is "
            f"closed otherwise. The chef buys what it cooks with at {store.name}, the fund "
            "paying, and cooks dishes from what the kitchen holds, a portion of each from its "
            f"ingredients: {recipes}. A dish is a day's food, eaten there as it is bought, at "
            "the price on the menu, which the chef sets; the chef does not buy its own dishes. "
            "What is not sold by midnight is gone. Each dish served pays the chef "
            f"{money(chef.per_service)}."
        )
        return {"office": office_work, "store": store_work, "restaurant": restaurant_work}

    def _health(self) -> str:
        """How the body works, in a few lines: what wears it and what restores it."""
        helpings: dict[int, list[str]] = {}
        for good in self.config.supplier:
            if good.ready:
                assert good.nourishment
                helpings.setdefault(round(A_DAYS_FOOD / good.nourishment), []).append(
                    bare(good.name)
                )
        food = [
            f"{counted(n, 'helping')} of {listed(foods, 'or')}" for n, foods in helpings.items()
        ]
        return (
            "Through the day you get hungry, and what you eat restores you: a dish"
            + (f", or {listed(food, 'or')}," if food else "")
            + " is about a day's need. You tire with the hours awake, faster at work and on the "
            "road, and sleep restores you, the more the better your home; exhausted, you stop "
            "work and cannot work again until you have slept. A day that ends with "
            "you starving or exhausted, or lived in a home of little comfort, wears your health "
            "down; a day in which you have eaten and rested mends it. When your health is gone, "
            "you take to your bed at home, carried there if you are elsewhere, and keep to it "
            "until you are treated. You can take stock of how you feel at any time with "
            "how_am_i."
        )

    def _routes(self) -> str:
        """The routes that differ from the usual walk, grouped by their minutes: `10 minutes
        among A, B and C` where every pair among those places has that route, else each pair."""
        c = self.config
        by_minutes: dict[int, list[tuple[str, str]]] = {}
        for route in c.routes:
            by_minutes.setdefault(route.minutes, []).append(route.between)
        parts = []
        for minutes, pairs in sorted(by_minutes.items()):
            joined = {place for pair in pairs for place in pair}
            places = [place.name for place in c.places if place.id in joined]
            if len(places) > 2 and len(pairs) == len(places) * (len(places) - 1) // 2:
                parts.append(f"{minutes} minutes among {listed(places)}")
            else:
                parts += [
                    f"{minutes} minutes between {c.place(a).name} and {c.place(b).name}"
                    for a, b in pairs
                ]
        return listed(parts)

    def _shopping(self) -> str:
        """Where things are sold, and what each good does, from the catalogue."""
        c = self.config
        money = partial(economy.money, c.currency)
        store, restaurant = c.workplace("store"), c.workplace("restaurant")
        ready = [bare(good.name) for good in c.supplier if good.ready]
        raw = [bare(good.name) for good in c.supplier if good.effect == "food" and not good.ready]
        kept = [good.name for good in c.supplier if good.kind == "durable"]
        sold = [
            *([f"ready food ({listed(ready)}), which you keep and eat a helping at a time "
               "whenever you could eat"] if ready else []),
            *([f"what the kitchen cooks with ({listed(raw)}), not eaten as it is"] if raw else []),
            *([listed(kept)] if kept else []),
        ]  # fmt: skip
        text = (
            f"Goods are sold at {store.name} while its shopkeeper is at work there: "
            f"{'; '.join(sold)}. Dishes are served at {restaurant.name} while its chef is at "
            "work there, each a day's food, eaten there and then. You pay in cash with buy; "
            "what is for sale, and at what price, you see when you are there."
        )
        for good in c.supplier:
            if good.effect == "travel":
                assert good.factor is not None
                text += f" With {good.name} your journeys take {fraction(good.factor)} the time."
        for good in c.supplier:
            if good.effect == "messaging":
                charge = (
                    f" ({money(good.fee_per_day)} a day while you own it)"
                    if good.fee_per_day
                    else ""
                )
                text += (
                    f" With {good.name}{charge} you can write to anyone else who has one, "
                    "wherever they are, with message; they read it when they next look up from "
                    "what they are doing."
                )
        seen = [
            f"with {good.name}, {good.phrase}" for good in c.supplier if good.effect == "appearance"
        ]
        if seen:
            text += f" What you wear and carry, others see: {'; '.join(seen)}."
        text += " What you have, and how much of it is left, inventory tells you."
        return text
