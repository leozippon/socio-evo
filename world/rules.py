"""The standing rules of the town, as one resident is told them, and `help` by topic.

The rules are derived from the configuration once and never change during a run; they are part
of the system prompt and the seed of the resident's notes on the town, and the ties they tell in
the town mode seed its notes on people. They describe what can be done and what follows from it,
in plain words, and nothing else: not the length of the run, not the machinery, not how anyone
ought to behave.
"""

from __future__ import annotations

from world.clock import parse_hour
from world.config import DayHours, TownConfig
from world.telling import cap, counted, listed

TOPICS = ("places", "day", "work", "money", "people", "sleep")
_HEADINGS = {
    "places": "Places",
    "day": "The day",
    "work": "Work",
    "money": "Money",
    "people": "People",
    "sleep": "Sleep",
}


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

    def help(self, name: str, topic: str) -> str:
        """The rules on `topic`, or the list of topics."""
        sections = self.sections(name)
        key = topic.strip().lower()
        if key in sections:
            return sections[key]
        return f"You can ask about: {', '.join(TOPICS)}."

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

    def sections(self, name: str) -> dict[str, str]:
        c = self.config
        me = next(resident for resident in c.residents if resident.name == name)
        workplace = c.workplace
        social = c.social
        exchange = social.exchange
        contact = social.mode == "town" or exchange is not None

        def money(amount: int) -> str:
            return f"-{c.currency}{-amount}" if amount < 0 else f"{c.currency}{amount}"

        names = listed([f"{place.name} ({place.id})" for place in c.places])
        routes = listed(
            [
                f"between {c.place(a).name} and {c.place(b).name}, {route.minutes}"
                for route in c.routes
                for a, b in [route.between]
            ]
        )
        places = (
            f"The town has these places, each with the short name you use to go there: {names}. "
            f"Your home is {c.place(me.home).name}. Walking from one place to another takes "
            f"{c.travel_minutes} minutes"
            + (f", except {routes} minutes" if routes else "")
            + ". On the way you notice nothing of where you are going, and nobody can speak "
            "to you."
        )

        day = (
            f"{cap(workplace.name)} is open at all hours. At midnight the day's living cost is "
            "taken from every purse and the board for the new day is posted. You go to bed at "
            "home at whatever hour you choose, giving the hour you want to wake and writing up "
            f"your day. At {c.day.forced_sleep} anyone still up falls asleep and wakes at home "
            f"at {c.day.forced_wake}, with no journal entry for that day."
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
            "nobody else can claim it."
            if social.mode == "town"
            else " The board is yours alone."
        )

        money_rules = (
            f"You have {money(me.purse)} to begin with. Living here costs "
            f"{money(c.work.living_cost)} a day, rent and board, taken from your purse at "
            "midnight, when you get a statement of your money. A purse can go below zero; you "
            "are then in debt."
        )
        if contact:
            money_rules += " You can hand money to someone you are talking with."

        conversation = (
            f"A conversation lasts until its people leave it or nobody speaks for "
            f"{social.silence_minutes} minutes."
        )
        if social.mode == "town":
            others = listed(
                [f"{r.name} ({c.place(r.home).name})" for r in c.residents if r.name != name]
            )
            meeting = listed([place.name for place in c.places if place.kind == "social"])
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
            "person you spent time with that day from 1 to 5, with a reason, which they read "
            "the next night without your name; and you can see to your files."
            if contact
            else " In bed, before you fall asleep, you can look back over your day and see to "
            "your files."
        )
        return {
            "places": places,
            "day": day,
            "work": work,
            "money": money_rules,
            "people": people,
            "sleep": sleep,
        }
