"""The standing rules of the town, as one resident is told them, and `help` by topic.

The rules are derived from the configuration and from who lives where, which the world passes
in as it stands: a move changes the homes, the free rooms and one's own rent, and nothing else
in them changes during a run. They are part of the system prompt, what the resident knows of
its own work and its town, told in the second person as the town speaks to it. They describe
what can be done and what follows from it, in plain words, and nothing else: not the length of
the run, not the machinery, not how anyone ought to behave. Their six sections (`SECTIONS`) are
short: the resident's own occupation and workplace, its money, the town's places, the others
(who lives and works where, and how speech goes), its body and sleep. `help` tells the detail by
topic (`TOPICS`): the work of each place of work, money, the body, the day and the places.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from world.businesses import BUSINESSES
from world.config import A_DAYS_FOOD, Occupation, TownConfig
from world.occupations import MAYOR, OCCUPATIONS, TEAM_LEADER
from world.telling import (
    amount,
    bare,
    cap,
    comfort_word,
    counted,
    fraction,
    listed,
    longest_sleep,
    share,
)

SECTIONS = ("work", "money", "town", "people", "body", "sleep")
"""The sections of the standing rules, in their order: one's own work first."""
HEADING = "## Your work and your town"
"""What the rules are headed with where the resident reads them."""
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
Homes = Mapping[str, Sequence[str]]
"""Who lives where: the names of the residents of each home, by the home's id."""


class Rules:
    def __init__(self, config: TownConfig) -> None:
        self.config = config

    def text(self, name: str, homes: Homes | None = None) -> str:
        """The whole of the rules told to `name`, with `homes` as they stand (at the start if not
        given)."""
        sections = self.sections(name, homes)
        body = "\n\n".join(f"{_HEADINGS[s]}. {sections[s]}" for s in SECTIONS)
        return f"{HEADING}\n\n{body}"

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
        c, money = self.config, self.config.money
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
            + "; on the way nobody can speak to you. help tells more of the town, by topic."
        )

        office, store = c.workplace("office").name, c.workplace("store").name
        own = OCCUPATIONS[occupation.id].told.format(
            office=office, store=store, withdrawn=self._withdrawn()
        )
        until = "you stop with leave_work" + (
            "" if occupation.duty == "anywhere" else " or go elsewhere"
        )
        work = (
            f"You are {occupation.title} at {workplace.name}. {own} You sit down to work there "
            f"with start_work, or by doing your work, and are at work until {until}."
        )

        assert my_home.rent is not None
        money_rules = (
            f"{self._economy(occupation)} You have {money(me.purse)} to begin with. Your rent, "
            f"{money(my_home.rent)} a day, is taken from your purse at midnight, never its last "
            f"{money(c.treasury.spares)}, a day's bread; what cannot be taken you owe, to be taken "
            "later."
        )

        food = self._a_days_food()
        body = (
            f"You get hungry through the day, and a dish{food} is about a day's need; you tire "
            "with the hours awake, faster at work and on the road, and sleep restores you. Ending "
            "a day starving or exhausted, a home of little comfort and illness wear your health "
            f"down; eating and rest mend it, and the doctor at {c.workplace('hospital').name} "
            "treats illness. When your health is gone you keep to your bed at home until the "
            "doctor treats you there."
        )

        people = (
            f"{self._who_lives(name, home_of)} {self._who_works(name)} You can speak to anyone "
            "awake where you are, to everyone there or only to the people you name, and the "
            "others notice that you said something but not what; a conversation lasts until its "
            f"people leave it or nobody speaks for {c.social.silence_minutes} minutes. Talking, "
            "you can still buy, eat and hand things over; doing your work leaves the talk."
        )

        day = c.day
        sleep = (
            "You go to bed at home with sleep, at any hour, giving the hour you want to wake and, "
            "if you write one, the day's entry for your journal; an entry given again the same "
            f"day is added to it. One sleep lasts at most {longest_sleep(day)}. In bed, before "
            "you fall asleep, you can look back over your day and see to your files. At "
            f"{day.forced_sleep} whoever is still up falls asleep where they are and wakes at home "
            f"at {day.forced_wake}."
        )
        return {
            "work": work,
            "money": money_rules,
            "town": town,
            "people": people,
            "body": body,
            "sleep": sleep,
        }

    def _staffed(self, occupation: str | None = None) -> list[Occupation]:
        """The occupations some resident has, or only `occupation` if some resident has it."""
        had = {resident.occupation for resident in self.config.residents}
        return [o for o in self.config.occupations if o.id in had and occupation in (None, o.id)]

    def _shares(self) -> tuple[int, int]:
        """A client's payment for a task and the team leader's share of it, none when the town
        has no team leader."""
        work = self.config.work
        return work.payment, work.team_share if self._staffed(TEAM_LEADER) else 0

    def _split(self) -> str:
        """`A client pays $150 for each task accepted: $120 to the one who handed it in and $30
        to the team leader`, or all of it to the one who handed it in when the town has no team
        leader."""
        money = self.config.money
        payment, team = self._shares()
        shared = (
            f"{money(payment - team)} to the one who handed it in and {money(team)} to the team "
            "leader"
            if team
            else "all of it to the one who handed it in"
        )
        return f"A client pays {money(payment)} for each task accepted: {shared}"

    def _economy(self, occupation: Occupation) -> str:
        """How the town's money goes, in two sentences told to `occupation` first among the money
        rules: who is paid by whom, nobody for their time (`a client pays for each task
        accepted, a fifth to the team leader and the rest to whoever handed it in; the chef, the
        shopkeeper and the doctor are paid by their customers and the mayor from the town's
        treasury`); and the tax withheld into the treasury, with what else the treasury takes
        and pays, which to the mayor is what it is there for and where he sees it."""
        c, money = self.config, self.config.money
        staffed = self._staffed()
        paid = []
        if any(OCCUPATIONS[o.id].workplace == "office" for o in staffed):
            shared = (
                f"{share(c.work.leader_share)} to the team leader and the rest to whoever "
                "handed it in"
                if self._shares()[1]
                else "all of it to whoever handed it in"
            )
            paid.append(f"a client pays for each task accepted, {shared}")
        keepers = [o.title for o in staffed if any(b.keeps(o.id) for b in BUSINESSES.values())]
        salaried = [o.title for o in staffed if o.salary]
        by = ((keepers, "by their customers"), (salaried, "from the town's treasury"))
        groups = [(titles, how) for titles, how in by if titles]
        if groups:  # the verb told once: `X are paid by their customers and Y from the treasury`
            (first, how), *rest = groups
            verb = "is" if len(first) == 1 else "are"
            told = [f"{listed(first)} {verb} paid {how}", *(f"{listed(t)} {h}" for t, h in rest)]
            paid.append(listed(told))
        if occupation.id == MAYOR:
            salary = (
                f"your salary of {money(occupation.salary)} a day at midnight, as far as it holds "
                "the money, and "
                if occupation.salary
                else ""
            )
            pays = (
                f" and is there to pay {salary}whatever you grant residents at "
                f"{c.place(occupation.workplace).name}; your report shows what it holds and takes "
                "in"
            )
        else:
            paying = [f"{title}'s salary" for title in salaried]
            paying += ["what the mayor grants"] if self._staffed(MAYOR) else []
            pays = f" and pays {listed(paying)}" if paying else ""
        named = "the treasury" if salaried else "the town's treasury"  # named once in full
        treasury = (
            f"{cap(share(c.tax))} of what clients and customers pay is withheld in tax into "
            f"{named}, which also takes the rents{pays}."
            if c.tax
            else f"{cap(named)} takes the rents{pays}."
        )
        return f"Nobody is paid for their time{': ' if paid else ''}{'; '.join(paid)}. {treasury}"

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
        for item in self.config.items:
            if item.ready and not item.dish:
                assert item.nourishment
                helpings.setdefault(round(A_DAYS_FOOD / item.nourishment), []).append(
                    bare(item.name)
                )
        food = [
            f"{counted(n, 'helping')} of {listed(foods, 'or')}" for n, foods in helpings.items()
        ]
        return f", or {listed(food, 'or')}," if food else ""

    def topics(self, homes: Homes | None = None) -> dict[str, str]:
        """What `help` tells on each topic, with `homes` as they stand (at the start if not
        given)."""
        c, money = self.config, self.config.money
        office, store = c.workplace("office"), c.workplace("store")
        restaurant, hospital, hall = (c.workplace(k) for k in ("restaurant", "hospital", "hall"))
        work, day = c.work, c.day
        own = (
            " (the whole to the team leader for a task of the leader's own)"
            if self._shares()[1]
            else ""
        )
        office_work = (
            f"{cap(office.name)} takes in programming work from clients elsewhere: their tasks "
            f"come in on its board at random through the day, about {work.tasks_a_day:g} a day "
            f"between {work.arrive_from} and {work.arrive_until}, and whoever is there is told "
            "as one comes in. Each task is a code repository with a problem to fix, for which "
            "the client pays once it is accepted. The board "
            "shows each open task's first line, who holds it and when the client withdraws it; "
            "read_task gives the whole problem without taking it. Claim a task and you get a "
            "workspace with its repository, where you can run commands and read and write "
            "files; there is no internet. You work on it there, where the machines are. When "
            "your fix is ready, hand it in with submit: the client's own checks, which you do "
            "not see, run on it in a clean copy of the repository, and if they pass the task is "
            "accepted and the client pays at once. You can hand in each task at most "
            f"{counted(work.acceptance_runs, 'time')} a day. You hold one task at a time and "
            "keep it wherever you go, your changes kept overnight; you can give it up with "
            "abandon_task, and its changes are gone. The team leader can give a task to any of "
            "the programmers with assign, or move it from one to another, whose changes to it "
            "are then gone. A task not accepted in time is withdrawn by its client at the end of "
            f"{self._withdrawn()}, held or not, and its workspace with it. "
            + f"{self._split()}{own}."
        )

        store_work = (
            f"{cap(store.name)} is its shopkeeper's, and sells while the shopkeeper is at work "
            "there; otherwise its door is shut. It sells from its shelves, which the shopkeeper "
            f"sees whenever there, at the prices the shopkeeper sets: {self._goods()} What is "
            "sold out is gone until the shopkeeper orders more from the supplier outside the "
            "town, paying for it at once; the order comes onto the shelves at "
            f"{day.delivery} the next morning. The chef buys for the kitchen with buy "
            "for_the_kitchen, and pays like anyone else."
        )

        recipes = "; ".join(
            f"{dish.name} from "
            + listed([amount(c.item(item), units) for item, units in dish.ingredients.items()])
            for dish in c.dishes
        )
        restaurant_work = (
            f"The kitchen of {restaurant.name} is its chef's, and serves while the chef is at "
            "work there; it is closed otherwise. The chef buys what the kitchen cooks with at "
            f"{store.name} with buy for_the_kitchen, paying for it, and cooks dishes from what "
            f"the kitchen holds, a portion of each from its ingredients: {recipes}. A dish is a "
            "day's food, eaten there as it is bought, at the price on the menu, which the chef "
            "sets; or as the chef hands it over with pass, when nobody pays and the chef bears "
            "what it cost; the chef, at work there, has one with eat and does not buy them. What "
            "is left at midnight is gone."
        )

        fees = c.hospital
        hospital_work = (
            f"The surgery at {hospital.name} is open while its doctor is at work there. An "
            f"examination, {money(fees.examination)} at the start, tells the doctor and the "
            "patient how hungry, tired and well the patient is, in numbers out of 100, whether "
            "the patient is ill, and why the patient's health moved the night before. A "
            f"treatment, {money(fees.treatment)} at the start, restores {fees.restores:g} of the "
            "patient's health, ends an illness and gets one too ill to get up out of bed; the "
            "doctor goes to such a patient's bedside. The patient pays the fee, which the doctor "
            "sets."
        )

        hall_work = (
            f"At {hall.name} the mayor reads the town's report with report: what the treasury "
            "holds now, what it took in and paid out so far today and yesterday, the grants, what "
            "it owes and who owes rent; the tasks open at "
            f"{office.name} and those accepted, and by whom; the stock, prices and sales of "
            f"{store.name}; the menu and the dishes served at {restaurant.name}; the patients of "
            f"{hospital.name}; and each resident's occupation, time at work and health as others "
            "see it, but nobody's purse. With announce the mayor tells every resident something, "
            f"at once or on waking, and it stays on the board at {hall.name}, which anyone there "
            "can read with look_around. With grant the mayor pays money from the treasury to "
            "anyone, for a reason, which the report shows."
        )

        fees_charged = any(item.fee_per_day for item in c.items)

        withheld = (
            " The tax is withheld from each payment as it comes in, rounded down, and you are told "
            "how much; money handed between people is not taxed."
            if c.tax
            else ""
        )
        charges = (
            "; with the rent it takes the daily charge on anything you own that carries one"
            if fees_charged
            else ""
        )
        salary = "".join(
            f" It pays {o.title} a salary of {money(o.salary)} a day, as far as it holds the "
            "money, owing the rest."
            for o in self._staffed()
            if o.salary
        )
        money_detail = (
            f"Money comes into the town only from the clients of {office.name}, and leaves it "
            f"only when the shopkeeper pays the supplier. {cap(store.name)}, the kitchen of "
            f"{restaurant.name} and the surgery at {hospital.name} are their keepers', who pay "
            f"for what the business buys.{withheld} The town's treasury owns the homes{charges}."
            f"{salary} Your statement at midnight tells you each movement of your money that day "
            "and what your purse holds. You pay for everything in cash from your purse, and "
            "cannot pay more than it holds. With pass you can hand money, a thing you own (with "
            "any daily charge on it) or food you keep to anyone awake where you are, as a gift or "
            "on terms you agree between you; the town keeps no account of it. With put you leave "
            "something where you are, for anyone to take, and with get you take what is left "
            "there; what a shop or a kitchen keeps is bought, not taken. What you have, and how "
            "much of it is left, inventory tells you."
        )

        illness = c.needs.health.illness
        body = (
            "Through the day you get hungry, and what you eat restores you: a dish"
            f"{self._a_days_food()} is about a day's need. Food you keep you eat a helping at a "
            "time as you get hungry, or when you choose with eat. You tire with the hours awake, "
            "faster "
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
            f"the day before arrives at {day.delivery}. At midnight the rent is taken, your "
            "health is reckoned from the day, and what the kitchen did not sell is gone. When "
            "you do nothing, time passes until something happens or "
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
        """What the Store sells, and what each item does, from the catalogue."""
        c, money = self.config, self.config.money
        ready = [bare(item.name) for item in c.supplied if item.ready]
        raw = [bare(item.name) for item in c.supplied if item.effect == "food" and not item.ready]
        kept = [item.name for item in c.supplied if item.kind == "durable"]
        sold = [
            *([f"ready food ({listed(ready)}), which you keep and eat a helping at a time "
               "whenever you could eat"] if ready else []),
            *([f"what the kitchen cooks with ({listed(raw)}), not eaten as it is"] if raw else []),
            *([listed(kept)] if kept else []),
        ]  # fmt: skip
        text = f"{'; '.join(sold)}."
        for item in c.supplied:
            if item.effect == "travel":
                assert item.factor is not None
                text += f" With {item.name} your journeys take {fraction(item.factor)} the time."
        for item in c.supplied:
            if item.effect == "messaging":
                charge = (
                    f" ({money(item.fee_per_day)} a day while you own it)"
                    if item.fee_per_day
                    else ""
                )
                text += (
                    f" With {item.name}{charge} you can write to anyone else who has one, "
                    "wherever they are, with message; they read it when they next look up from "
                    "what they are doing."
                )
        seen = [
            f"with {item.name}, {item.phrase}" for item in c.supplied if item.effect == "appearance"
        ]
        if seen:
            text += f" What you wear and carry, others see: {'; '.join(seen)}."
        return text
