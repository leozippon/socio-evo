"""The standing rules of the town, as one resident is told them, and `help` by topic.

The rules are derived from the configuration once and never change during a run; they are part
of the system prompt and the seed of the resident's notes on the town, and the ties they tell in
the town mode seed its notes on people. They describe what can be done and what follows from it,
in plain words, and nothing else: not the length of the run, not the machinery, not how anyone
ought to behave. `help` tells the same paragraphs with what has changed since: who lives where
and which rooms are free, as the world passes it in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from world.clock import parse_hour
from world.config import DayHours, Good, TownConfig
from world.telling import cap, counted, listed

TOPICS = ("places", "day", "work", "money", "shopping", "health", "people", "sleep")
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
Homes = Mapping[str, Sequence[str]]
"""Who lives where: the names of the residents of each home, by the home's id."""


def worth(days: int) -> str:
    """`a day's worth`, `3 days' worth`."""
    return "a day's worth" if days == 1 else f"{days} days' worth"


def bare(name: str) -> str:
    """A good's name without its article: `a phone` is `phone`."""
    for article in ("a ", "an ", "the "):
        if name.startswith(article):
            return name[len(article) :]
    return name


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
    """The rule on how long one sleep may last, without its full stop; `sleep` refuses with it."""
    hours, minutes = divmod(parse_hour(day.sleep_at_most) // 60, 60)
    span = listed([counted(n, unit) for n, unit in ((hours, "hour"), (minutes, "minute")) if n])
    return f"Nobody sleeps longer than {span} at a stretch"


class Rules:
    def __init__(self, config: TownConfig) -> None:
        self.config = config

    def text(self, name: str) -> str:
        """The whole of the rules told to `name`."""
        sections = self.sections(name)
        body = "\n\n".join(f"{_HEADINGS[topic]}. {sections[topic]}" for topic in TOPICS)
        return f"How the town works.\n\n{body}"

    def help(self, name: str, topic: str, homes: Homes | None = None) -> str:
        """The rules on `topic`, with `homes` as they stand now, or the list of topics."""
        sections = self.sections(name, homes)
        key = topic.strip().lower()
        if key in sections:
            return sections[key]
        return f"You can ask about: {', '.join(TOPICS)}."

    def homes(self, name: str) -> dict[str, list[str]]:
        """Who lives where as `name` knows it at the start: in the isolated mode, only itself."""
        c = self.config
        return {
            place.id: [
                r.name
                for r in c.residents
                if r.home == place.id and (c.social.mode == "town" or r.name == name)
            ]
            for place in c.places
            if place.kind == "home"
        }

    def ties(self, name: str) -> list[str]:
        """What `name` is told of the people it knows already: its ties, in the town mode."""
        if self.config.social.mode != "town":
            return []
        me = next(resident for resident in self.config.residents if resident.name == name)
        return list(me.ties.values())

    def people_notes(self, name: str) -> str:
        """The first contents of `name`'s notes on people: the heading, and under it the people
        it knows already, as the rules tell them."""
        return "# People\n" + "".join(f"\n{tie}\n" for tie in self.ties(name))

    def sections(self, name: str, homes: Homes | None = None) -> dict[str, str]:
        """The rules by topic, told to `name`, with `homes` as they stand (at the start if not
        given)."""
        c = self.config
        me = next(resident for resident in c.residents if resident.name == name)
        homes = homes if homes is not None else self.homes(name)
        home_of = {who: place for place, people in homes.items() for who in people}
        my_home = c.place(home_of[name])
        workplace = c.workplace
        social = c.social
        exchange = social.exchange
        contact = social.mode == "town" or exchange is not None
        for_sale = c.for_sale()

        def money(amount: int) -> str:
            return f"-{c.currency}{-amount}" if amount < 0 else f"{c.currency}{amount}"

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
            f"{cap(workplace.name)} is open at all hours. At midnight rent is taken from every "
            "purse, your health is reckoned from the day and the board for the new day is "
            "posted. You go to bed at home at whatever hour you choose, giving the hour you "
            "want to wake and "
            f"writing up your day. At {c.day.forced_sleep} anyone still up falls asleep and "
            f"wakes at home at {c.day.forced_wake}, with no journal entry for that day."
        )
        if exchange is not None:
            day += (
                f" Every evening at {exchange.at} you are paired by lot with another worker of "
                "the town, and woken for it if you are asleep; you both walk to "
                f"{c.place(exchange.place).name} and talk about your work, each with "
                f"{counted(exchange.messages, 'turn')} to speak."
            )

        expiry = {
            0: "at the first midnight after you claimed it",
            1: "at the second midnight after you claimed it",
        }.get(
            c.work.claim_expiry_days,
            f"when {c.work.claim_expiry_days + 1} midnights have passed since you claimed it",
        )
        work = (
            f"{cap(workplace.name)} takes in programming work from clients elsewhere and posts "
            "it on its board: each task is a code repository with a problem to fix, and pays "
            f"{money(c.work.payment)}. Claim a task and you get a workspace with its repository, "
            "where you can run commands and read and write files; there is no internet. When "
            "your fix is ready, hand it in with submit: the client's own checks, which you do "
            "not see, run on it in a clean copy of the repository, and if they pass you are paid "
            f"at once. You can hand in each task at most {c.work.acceptance_runs} times a day. "
            f"You hold at most one task at a time. You keep it when you leave {workplace.name}, "
            f"and your changes are kept overnight, but a claim runs out unpaid {expiry}. You "
            "cannot claim again a task you have been paid for."
        )
        work += (
            " Everyone works from the same board; a task someone holds is shown as held, and "
            "nobody else can claim it; a task someone has been paid for leaves the board for "
            "the day."
            if social.mode == "town"
            else " The board is yours alone."
        )

        assert my_home.rent is not None
        fees = any(good.fee_per_day for good in for_sale)
        money_rules = (
            f"You have {money(me.purse)} to begin with. Your room at {my_home.name} costs "
            f"{money(my_home.rent)} a day; rent"
            + (", and the daily charge on anything you own that carries one," if fees else "")
            + " is taken from your purse at midnight, when you get a statement of your money. "
            "You pay for everything in cash. A purse can go below zero when rent is taken; you "
            "are then in "
            "debt, and can still be paid, pay your rent and receive money, but can buy nothing "
            "until your purse covers the price."
        )
        if contact:
            money_rules += (
                " You can hand money to someone you are talking with, as a gift or a loan, on "
                "terms you agree between you; the town keeps no account of it."
            )

        shopping = self._shopping(for_sale, money)
        health = self._health(for_sale)

        conversation = (
            f"A conversation lasts until its people leave it or nobody speaks for "
            f"{social.silence_minutes} minutes."
        )
        if social.mode == "town":
            others = listed(
                [
                    f"{r.name} ({c.place(home_of[r.name]).name})"
                    for r in c.residents
                    if r.name != name and r.name in home_of  # the dead live nowhere
                ]
            )
            meeting = listed([place.name for place in c.places if place.kind in ("social", "shop")])
            people = f"The others who live in the town, with their homes: {others}. "
            if meeting:
                people += f"People run into one another at {meeting}; you can also "
            else:
                people += "You can "
            people += (
                f"call on someone at home, or find them at {workplace.name} while they work. "
                "You can speak to anyone awake at the same place as you: to everyone there at "
                "once, or only to the people you name, and then the others notice that you said "
                f"something but not what. {conversation}"
            )
            if me.ties:
                people += " Some of them you know already. " + " ".join(me.ties.values())
        elif exchange is not None:
            people = (
                "During the day you live and work on your own and meet nobody. At the evening "
                f"meeting you talk with the person you are paired with. {conversation}"
            )
        else:
            people = "You live and work on your own here and meet nobody."
        if contact and social.skills_shareable:
            people += (
                " You can pass one of your skills to someone you are talking with; they "
                "receive its text."
            )

        sleep = (
            "Go to bed at home at any hour with sleep, giving the hour you want to wake and "
            "your journal entry for the day, which is kept in your journal folder; if you go to "
            "bed more than once in a day, each entry is added to that day's journal. "
            f"{longest_sleep(c.day)}."
        )
        sleep += (
            " In bed, before you fall asleep, you read the ratings others gave you the night "
            "before, without their names; you can look back over your day; you can rate each "
            "person you spoke with that day from 1 to 5, with a reason, which they read "
            "the next night without your name; and you can see to your files."
            if contact and social.ratings
            else " In bed, before you fall asleep, you can look back over your day and see to "
            "your files."
        )
        return {
            "places": places,
            "day": day,
            "work": work,
            "money": money_rules,
            "shopping": shopping,
            "health": health,
            "people": people,
            "sleep": sleep,
        }

    def _health(self, for_sale: list[Good]) -> str:
        """How the body works, in a few lines: what wears it and what restores it, and where
        it can be looked at."""
        c = self.config
        clinic = [
            c.place(place_id).name
            for good in for_sale
            if good.effect in ("examination", "treatment")
            for place_id in good.sold_at
        ]
        text = (
            "Through the day you get hungry, and what you eat restores you: a meal, or a day's "
            "worth of a stock, is about a day's need. You tire with the hours awake, faster at "
            "work and on the road, and sleep restores you, the more the better your home; too "
            f"tired, you cannot sit down to work at {c.workplace.name}. A day that ends with "
            "you starving or exhausted, or lived in a home of little comfort, wears your health "
            "down; a day in which you have eaten and rested mends it. When your health is gone, "
            "you die. You can take stock of how you feel at any time with how_am_i"
        )
        if clinic:
            text += (
                f", and at {listed(sorted(set(clinic)))} an examination tells you exactly how "
                "you stand and treatment restores your health"
            )
        return text + "."

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

    def _shopping(self, for_sale: list[Good], money) -> str:
        """What is for sale where, and what each good does, from the catalogue."""
        c = self.config
        counters = []
        for place in c.places:
            sold = [good for good in for_sale if place.id in good.sold_at]
            if sold:
                counters.append(
                    f"at {place.name}, {listed([self._priced(g, money) for g in sold])}"
                )
        text = f"For sale, paid in cash with buy: {'; '.join(counters)}."
        food = [good for good in for_sale if good.effect == "food"]
        on_the_spot = [good.name for good in food if good.kind == "immediate"]
        stocked = [good.name for good in food if good.kind == "consumable"]
        if on_the_spot:
            text += f" {cap(listed(on_the_spot, 'or'))}: eaten on the spot, the day's food."
        if stocked:
            text += (
                f" {cap(listed(stocked, 'or'))}: kept in stock, and eaten from whenever you "
                "could eat, a day's worth a day."
            )
        for good in for_sale:
            if good.effect == "travel":
                assert good.factor is not None
                text += f" With {good.name} your journeys take {fraction(good.factor)} the time."
        writing = [good.name for good in for_sale if good.effect == "messaging"]
        if writing:
            text += (
                f" With {listed(writing, 'or')} you can write to anyone else who has one, "
                "wherever they are, with message; they read it when they next look up from what "
                "they are doing."
            )
        seen = [
            f"with {good.name}, {good.phrase}" for good in for_sale if good.effect == "appearance"
        ]
        if seen:
            text += f" What you wear and carry, others see: {'; '.join(seen)}."
        text += " What you have, and how much of it is left, is told with help on money."
        return text

    @staticmethod
    def _priced(good: Good, money) -> str:
        """`groceries ($36, 3 days' worth)`, `a phone ($80, then $3 a day)`."""
        detail = ""
        if good.kind == "consumable":
            assert good.uses is not None and good.per_day is not None
            detail = (
                f", {worth(good.days)}"
                if good.uses % good.per_day == 0
                else f", {good.uses} uses, {good.per_day} a day"
            )
        if good.fee_per_day:
            detail += f", then {money(good.fee_per_day)} a day"
        return f"{good.name} ({money(good.price)}{detail})"
