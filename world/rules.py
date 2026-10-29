"""The standing rules of the town, as one resident is told them, and `help` by topic.

The rules are derived from the configuration and from who lives where, which the world passes
in as it stands: a move changes the homes, the free rooms and one's own rent, and nothing else
in them changes during a run. They are part of the system prompt. They describe
what can be done and what follows from it, in plain words, and nothing else: not the length of
the run, not the machinery, not how anyone ought to behave. Their six sections (`SECTIONS`) are
short: the town's places, the resident's own occupation and workplace, its money, its body, the
others (who lives and works where, and how speech goes) and sleep. `help` tells the detail by
topic (`TOPICS`): the work of each place of work, money, the body, the day and the places.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import partial

from world import economy
from world.clock import parse_hour
from world.config import A_DAYS_FOOD, DayHours, Good, TownConfig
from world.telling import cap, counted, duration, listed

SECTIONS = ("town", "work", "money", "body", "people", "sleep")
"""The sections of the standing rules, in their order."""
TOPICS = ("office", "store", "restaurant", "hospital", "hall", "money", "body", "day", "places")
"""What `help` tells more of."""
MAX_WAIT_MINUTES = 600
"""The longest a resident can ask to wait, in minutes: the bound of `wait`, told by `help`."""
_HEADINGS = {
    "town": "The town",
    "work": "Work",
    "money": "Money",
    "body": "Body",
    "people": "People",
    "sleep": "Sleep",
}
OWN_WORK = {
    "programmer": (
        "Clients' tasks come in on its board through the day: you take one at a time with "
        "claim_task, or are given one by the team leader, work on it there, where the machines "
        "are, and hand it in for the client's checks before the client withdraws it, at the end "
        "of {withdrawn}."
    ),
    "team-leader": (
        "You lead its programmers. Clients' tasks come in on its board through the day: you can "
        "give any of them a task with assign, and, like them, take one at a time yourself, work "
        "on it there, where the machines are, and hand it in for the client's checks before the "
        "client withdraws it, at the end of {withdrawn}."
    ),
    "chef": (
        "You cook dishes in its kitchen from what the kitchen holds, set the menu's prices and "
        "serve whoever comes while you are at work there. You buy what you cook with at {store} "
        "with buy for_the_kitchen, and the fund pays."
    ),
    "shopkeeper": (
        "It is open while you are at work there: you sell its goods at the prices you set, and "
        "order more from the supplier, which the fund pays and which arrives the next morning."
    ),
    "doctor": (
        "Its surgery is open while you are at work there: you examine and treat patients, at "
        "fees you set, and you go to the bedside of anyone too ill to get up."
    ),
    "mayor": (
        "There you read the town's report with report, and with announce you tell every "
        "resident whatever you want them to know."
    ),
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
        self._money = partial(economy.money, config.currency)

    def text(self, name: str, homes: Homes | None = None) -> str:
        """The whole of the rules told to `name`, with `homes` as they stand (at the start if not
        given)."""
        sections = self.sections(name, homes)
        body = "\n\n".join(f"{_HEADINGS[s]}. {sections[s]}" for s in SECTIONS)
        return f"How the town works.\n\n{body}"

    def help(self, topic: str, homes: Homes | None = None) -> str:
        """More on `topic`, with `homes` as they stand now, or what one can ask about."""
        key = topic.strip().lower()
        if key in TOPICS:
            return self.topics(homes)[key]
        return f"You can ask about: {listed(list(TOPICS))}."

    def homes(self) -> dict[str, list[str]]:
        """Who lives where at the start."""
        c = self.config
        return {
            place.id: [r.name for r in c.residents if r.home == place.id]
            for place in c.places
            if place.kind == "home"
        }

    def sections(self, name: str, homes: Homes | None = None) -> dict[str, str]:
        """The rules by section, told to `name`, with `homes` as they stand (at the start if not
        given)."""
        c, money = self.config, self._money
        me = next(resident for resident in c.residents if resident.name == name)
        homes = homes if homes is not None else self.homes()
        home_of = {who: place for place, people in homes.items() for who in people}
        my_home = c.place(home_of[name])
        occupation = c.occupation(me.occupation)
        workplace = c.place(occupation.workplace)

        names = listed([f"{place.name} ({place.id})" for place in c.places])
        routes = self._routes()
        town = (
            f"The places, with the short name you go there by: {names}. Walking from one to "
            f"another takes {c.travel_minutes} minutes"
            + (f", {routes}" if routes else "")
            + "; on the way nobody can speak to you. Your home is "
            f"{my_home.name}. help tells more of the town, by topic."
        )

        store, withdrawn = c.workplace("store").name, self._withdrawn()
        own = OWN_WORK[occupation.id].format(store=store, withdrawn=withdrawn)
        work = (
            f"You are {occupation.title} at {workplace.name}. {own} You sit down to work there "
            "with start_work, or by doing your work, and are at work until you stop with "
            "leave_work or go elsewhere."
        )

        assert my_home.rent is not None
        sums = [f"{money(occupation.per_service)} at once {SERVICE[occupation.id]}"]
        if occupation.id == "team-leader":
            programmer = c.occupation("programmer")
            sums.append(f"{money(programmer.per_service)} for each task of your own accepted")
        money_rules = (
            f"You have {money(me.purse)} to begin with. The town's fund pays you "
            f"{money(occupation.wage_per_hour)} an hour for your time at work at {workplace.name}"
            + (f", and {listed(sums)}" if occupation.per_service else "")
            + ". At midnight your wages are paid into your purse, with the rent for your room, "
            f"{money(my_home.rent)} a day, taken out of them. You pay for everything in cash from "
            "your purse, and with give you can hand money or things to anyone with you."
        )

        food = self._a_days_food()
        body = (
            f"You get hungry through the day, and a dish{food} is about a day's need; you tire "
            "with the hours awake, faster at work and on the road, and sleep restores you. Ending "
            "a day starving or exhausted, a home of little comfort and illness wear your health "
            f"down; eating and rest mend it, and the doctor at {c.workplace('hospital').name} "
            "treats illness. When your health is gone you keep to your bed at home until the "
            "doctor treats you there. how_am_i tells you how you are."
        )

        people = (
            f"{self._who_lives(name, home_of)} {self._who_works(name)} You can speak to anyone "
            "awake where you are, to everyone there or only to the people you name, and the "
            "others notice that you said something but not what; a conversation lasts until its "
            f"people leave it or nobody speaks for {c.social.silence_minutes} minutes."
        )

        day = c.day
        sleep = (
            "Go to bed at home at any hour with sleep, giving the hour you want to wake and, if "
            "you write one, the day's entry in your journal; an entry given again the same day "
            f"is added to it. You cannot sleep longer than {longest_sleep(day)} at a stretch. In "
            "bed, before you fall asleep, you can look back over your day and see to your files. "
            f"At {day.forced_sleep} anyone still up falls asleep where it is and wakes at home at "
            f"{day.forced_wake}."
        )
        return {
            "town": town,
            "work": work,
            "money": money_rules,
            "body": body,
            "people": people,
            "sleep": sleep,
        }

    def _who_lives(self, name: str, home_of: Mapping[str, str]) -> str:
        """Who lives where, in a sentence told to `name`."""
        c = self.config
        mine = home_of[name]
        housemates = [r.name for r in c.residents if r.name != name and home_of[r.name] == mine]
        told = f"You live in {c.place(mine).name}" + (
            f" with {listed(housemates)}" if housemates else ""
        )
        others = []
        for place in c.places:
            living = [r.name for r in c.residents if home_of[r.name] == place.id]
            if place.id == mine or not living:
                continue
            verb = ("lives " if len(living) == 1 else "live ") if not others else ""
            others.append(f"{listed(living)} {verb}in {place.name}")
        return f"{told}; {listed(others)}." if others else f"{told}."

    def _who_works(self, name: str) -> str:
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
        return f"{cap(listed(told))}." if told else ""

    def _withdrawn(self) -> str:
        """`the third day after the one it came in`: at whose end a client withdraws a task."""
        after = self.config.work.expiry_days
        nth = {1: "first", 2: "second", 3: "third"}.get(after, f"{after}th")
        return f"the {nth} day after the one it came in" if after else "the day it came in"

    def _a_days_food(self) -> str:
        """`, or 3 helpings of bread or fruit,`: the helpings of ready food that make a day's
        need, or nothing if none is sold."""
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
        return f", or {listed(food, 'or')}," if food else ""

    def topics(self, homes: Homes | None = None) -> dict[str, str]:
        """What `help` tells on each topic, with `homes` as they stand (at the start if not
        given)."""
        c, money = self.config, self._money
        office, store = c.workplace("office"), c.workplace("store")
        restaurant, hospital, hall = (c.workplace(k) for k in ("restaurant", "hospital", "hall"))
        work, day = c.work, c.day
        programmer, leader = c.occupation("programmer"), c.occupation("team-leader")
        office_work = (
            f"{cap(office.name)} takes in programming work from clients elsewhere: their tasks "
            f"come in on its board at random through the day, about {work.tasks_a_day:g} a day "
            f"between {work.arrive_from} and {work.arrive_until}, and whoever is there is told "
            "as one comes in. Each task is a code repository with a problem to fix, for which "
            f"the client pays the town {money(work.payment)} once it is accepted. The board "
            "shows each open task's first line, who holds it and when the client withdraws it; "
            "read_task gives the whole problem without taking it. Claim a task and you get a "
            "workspace with its repository, where you can run commands and read and write "
            "files; there is no internet. You work on it there, where the machines are. When "
            "your fix is ready, hand it in with submit: the client's own checks, which you do "
            "not see, run on it in a clean copy of the repository, and if they pass the task is "
            "accepted and you are paid for it at once. You can hand in each task at most "
            f"{counted(work.acceptance_runs, 'time')} a day. You hold one task at a time and "
            "keep it wherever you go, your changes kept overnight; you can give it up with "
            "abandon_task, and its changes are gone. The team leader can give a task to any of "
            "the programmers with assign, or move it from one to another, whose changes to it "
            "are then gone. A task not accepted in time is withdrawn by its client at the end of "
            f"{self._withdrawn()}, held or not, and its workspace with it. Each task accepted "
            f"pays the one who handed it in {money(programmer.per_service)} and the team leader "
            f"{money(leader.per_service)}."
        )

        shopkeeper = c.occupation("shopkeeper")
        store_work = (
            f"{cap(store.name)} sells while its shopkeeper is at work there; otherwise its door "
            f"is shut. It sells from its stock, at the prices the shopkeeper sets: {self._goods()} "
            "What is sold out is gone until the shopkeeper orders more from the supplier outside "
            f"the town: the fund pays the supplier at once, and the goods arrive at {day.delivery} "
            "the next morning; an order the fund cannot pay for is refused. Each sale pays the "
            f"shopkeeper {money(shopkeeper.per_service)}. The chef buys for the kitchen with buy "
            "for_the_kitchen, and the fund pays."
        )

        chef = c.occupation("chef")
        recipes = "; ".join(
            f"{dish.name} from "
            + listed([amount(c.good(good), units) for good, units in dish.ingredients.items()])
            for dish in c.dishes
        )
        restaurant_work = (
            f"The kitchen of {restaurant.name} serves while its chef is at work there, and is "
            f"closed otherwise. The chef buys what it cooks with at {store.name} with buy "
            "for_the_kitchen, the fund paying, and cooks dishes from what the kitchen holds, a "
            f"portion of each from its ingredients: {recipes}. A dish is a day's food, eaten "
            "there as it is bought, at the price on the menu, which the chef sets; the chef does "
            "not buy its own dishes. What is not sold by midnight is gone. Each dish served pays "
            f"the chef {money(chef.per_service)}."
        )

        doctor, fees = c.occupation("doctor"), c.hospital
        hospital_work = (
            f"The surgery at {hospital.name} is open while its doctor is at work there. An "
            f"examination, {money(fees.examination)} at the start, tells the doctor and the "
            "patient how hungry, tired and well the patient is, in numbers out of 100, whether "
            "it is ill, and why its health moved the night before. A treatment, "
            f"{money(fees.treatment)} at the start, restores {fees.restores:g} of the patient's "
            "health, ends an "
            "illness and gets one too ill to get up out of bed; the doctor goes to such a "
            "patient's bedside. The patient pays the fee in cash, and the doctor sets the fees. "
            f"Each patient examined or treated pays the doctor {money(doctor.per_service)}."
        )

        hall_work = (
            f"At {hall.name} the mayor reads the town's report with report: what the fund "
            "holds, took in and paid out, what it owes and who owes rent; the tasks open at "
            f"{office.name} and those accepted, and by whom; the stock, prices and sales of "
            f"{store.name}; the menu and the dishes served at {restaurant.name}; the patients of "
            f"{hospital.name}; and each resident's occupation, time at work and health as others "
            "see it, but nobody's purse. With announce the mayor tells every resident something, "
            f"at once or on waking, and it stays on the board at {hall.name}, which anyone there "
            "can read with look_around."
        )

        fees_charged = any(good.fee_per_day for good in c.supplier)
        money_detail = (
            "The town keeps one fund, which takes in what clients pay for the work, the rent, "
            "what is sold and the fees, and pays everyone who works: a wage for each hour at "
            "work at one's own place of work, from sitting down to work until one stops, and a "
            "sum at once for each service. At midnight your wages for the day are paid into your "
            "purse with the rent for your room"
            + (
                ", and the daily charge on anything you own that carries one,"
                if fees_charged
                else ""
            )
            + " taken out of them, and you get a statement of your money; what is in your purse "
            "is never touched by rent. When your wages do not cover the rent, you owe the rest, "
            "and it is taken from your next wages; when the fund cannot pay you, it owes you the "
            "rest and pays it with your next wages. You pay for everything in cash from your "
            "purse, and cannot pay more than it holds. With give you can hand money, a thing you "
            "own (with any daily charge on it) or food you keep to anyone awake where you are, "
            "as a gift or on terms you agree between you; the town keeps no account of it. What "
            "you have, and how much of it is left, inventory tells you."
        )

        illness = c.needs.health.illness
        body = (
            "Through the day you get hungry, and what you eat restores you: a dish"
            f"{self._a_days_food()} is about a day's need. You tire with the hours awake, faster "
            "at work and on the road, and sleep restores you, the more the better your home; "
            "exhausted, you stop work and cannot work again until you have slept. A day that "
            "ends with you starving or exhausted, or lived in a home of little comfort, wears "
            "your health down; a day in which you have eaten and rested mends it. Illness comes "
            "by chance at midnight, the more often the lower your health and the poorer your "
            f"home: while you are ill, each night costs you {illness.per_night:g} of your health "
            "and mends nothing, and sleep restores half as much; it passes after "
            f"{counted(illness.nights, 'night')}, or when the doctor treats you. When your health "
            "is gone, you take to your bed at home, carried there if you are elsewhere, and keep "
            "to it until the doctor treats you there. You can take stock of how you feel at any "
            "time with how_am_i."
        )

        day_detail = (
            "No place keeps hours: a place of work is open while someone is at work there, and "
            f"every place can be visited at any hour. Clients' tasks come in at {office.name} "
            f"between {work.arrive_from} and {work.arrive_until}, and what {store.name} ordered "
            f"the day before arrives at {day.delivery}. At midnight your wages for the day are "
            "paid, your health is reckoned from the day, and what the kitchen did not sell is "
            "gone. When you do nothing, time passes until something happens or "
            f"{counted(c.clock.idle_minutes, 'minute')} have gone by, and you are told the hour; "
            f"with wait you let up to {counted(MAX_WAIT_MINUTES, 'minute')} pass."
        )

        homes = homes if homes is not None else self.homes()
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
        meeting = listed(
            [place.name for place in c.places if place.kind in ("social", "store", "restaurant")]
        )
        places = (
            f"The homes, with the rent a day for a room and the rooms free: {listed(rooms)}. At a "
            "home with a free room you can move in with move_in: you give up your old room, and "
            f"the new rent is taken from the next midnight. People run into one another at "
            f"{meeting}; you can also call on someone at home, or find them where they work."
        )
        return {
            "office": office_work,
            "store": store_work,
            "restaurant": restaurant_work,
            "hospital": hospital_work,
            "hall": hall_work,
            "money": money_detail,
            "body": body,
            "day": day_detail,
            "places": places,
        }

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
                parts.append(f"{minutes} among {listed(places)}")
            else:
                parts += [
                    f"{minutes} between {c.place(a).name} and {c.place(b).name}" for a, b in pairs
                ]
        return listed(parts)

    def _goods(self) -> str:
        """What the Store sells, and what each good does, from the catalogue."""
        c, money = self.config, self._money
        ready = [bare(good.name) for good in c.supplier if good.ready]
        raw = [bare(good.name) for good in c.supplier if good.effect == "food" and not good.ready]
        kept = [good.name for good in c.supplier if good.kind == "durable"]
        sold = [
            *([f"ready food ({listed(ready)}), which you keep and eat a helping at a time "
               "whenever you could eat"] if ready else []),
            *([f"what the kitchen cooks with ({listed(raw)}), not eaten as it is"] if raw else []),
            *([listed(kept)] if kept else []),
        ]  # fmt: skip
        text = f"{'; '.join(sold)}."
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
        return text
