"""The standing rules of the town, as one resident is told them, and `help` by topic.

The rules are derived from the configuration once and never change during a run; they are part
of the system prompt and the seed of the resident's notes on the town. They describe what can
be done and what follows from it, in plain words, and nothing else: not the length of the run,
not the machinery, not how anyone ought to behave.
"""

from __future__ import annotations

from world.config import TownConfig
from world.telling import cap, listed

TOPICS = ("places", "day", "work", "money", "people", "sleep")
_HEADINGS = {
    "places": "Places",
    "day": "The day",
    "work": "Work",
    "money": "Money",
    "people": "People",
    "sleep": "Sleep",
}


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
            f"The town has these places, each with the name to use when you go there: {names}. "
            f"Your home is {c.place(me.home).name}. Walking from one place to another takes "
            f"{c.travel_minutes} minutes"
            + (f", except {routes} minutes" if routes else "")
            + ". On the way you notice nothing of where you are going, and nobody can speak "
            "to you."
        )

        day = (
            f"Nobody gets up before {c.day.wake_earliest}. {cap(workplace.name)} opens at "
            f"{workplace.opens}, when the day's board is posted, and closes at "
            f"{workplace.closes}; whoever is still working then stops and steps outside. At "
            "midnight the day's living cost is taken from every purse. You end your day by "
            f"going to bed at home. At {c.day.forced_sleep} anyone still up falls asleep and "
            f"wakes at home at {c.day.wake_earliest}, with no journal entry for that day."
        )
        if exchange is not None:
            day += (
                f" Every evening at {exchange.at} you are paired by lot with another worker of "
                f"the town; you both walk to {c.place(exchange.place).name} and talk about "
                f"your work, {exchange.messages} messages each."
            )

        expiry = {
            0: "of the day you claimed it",
            1: "of the day after you claimed it",
        }.get(c.work.claim_expiry_days, f"{c.work.claim_expiry_days} days after you claimed it")
        work = (
            f"Work comes from the board at {workplace.name}. Each task is a code repository "
            f"with a problem to fix, and pays {money(c.work.payment)}. Claim a task to get a "
            "workspace with its repository, where you can run commands and read and write "
            "files; the workspace has no internet. When your change is ready, submit it: it "
            "is checked in a clean copy of the repository by checks you cannot see, and if it "
            "passes you are paid at once. You can submit each task at most "
            f"{c.work.acceptance_runs} times a day. You hold at most one task at a time. You "
            f"keep it when you leave {workplace.name}, and your changes are kept overnight, "
            f"but a claim runs out unpaid at the closing {expiry}. You cannot claim again a "
            "task you have been paid for."
        )
        work += (
            " Everyone works from the same board; a task someone holds is shown as held, and "
            "nobody else can claim it."
            if social.mode == "town"
            else " The board is yours alone."
        )

        money_rules = (
            f"You started with {money(me.purse)}. Living costs {money(c.work.living_cost)} a "
            "day, taken at midnight, when you get a statement of your money. A purse can go "
            "below zero; you are then in debt."
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
            people = (
                "You can speak to anyone awake at the same place as you: to everyone there at "
                "once, or only to the people you name, and then the others notice that you "
                f"said something but not what. {conversation} The others who live in the town, "
                f"with their homes: {others}."
            )
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
            f"Go to bed at home from {c.day.earliest_sleep} on, with sleep, giving the hour you "
            f"want to wake, no earlier than {c.day.wake_earliest}, and your journal entry for "
            "the day, which is kept in your journal folder."
        )
        sleep += (
            " In bed, before you fall asleep, you read the ratings others gave you the night "
            "before, without their names; you can look over the town's record of your day; "
            "you can rate each person you spent time with that day from 1 to 5, with a "
            "reason, which they read the next night without your name; and you can see to "
            "your files."
            if contact
            else " In bed, before you fall asleep, you can look over the town's record of your "
            "day and see to your files."
        )
        return {
            "places": places,
            "day": day,
            "work": work,
            "money": money_rules,
            "people": people,
            "sleep": sleep,
        }
