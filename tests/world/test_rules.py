"""The rules as one resident is told them: six short sections, its own occupation and workplace
first, then its money (what it is paid for and by whom, the tax, the rent and the treasury), the
town's places, who lives and works where, its body and sleep; and `help`, which tells the detail
by topic: the work of each place of work, money, the body, the day and the places."""

from __future__ import annotations

from tests.support.towns import CARE, RESIDENTS, TRADES, town_config
from world.rules import SECTIONS, TOPICS, Rules

TOWN = town_config(residents=RESIDENTS + TRADES + CARE, tax=0.1)


def test_the_rules_are_six_short_sections_ones_own_work_first():
    rules = Rules(TOWN)
    sections = rules.sections("Mei")
    assert list(sections) == list(SECTIONS)
    text = rules.text("Mei")
    assert text.startswith("## Your work and your town\n\nWork. You are a programmer at ")
    assert [line.split(".")[0] for line in text.split("\n\n")[1:]] == [
        "Work", "Money", "The town", "People", "Body", "Sleep",
    ]  # fmt: skip
    assert len(text) <= 3500  # about 3,000, as the town's (tests/experiments)
    assert sections["work"] == (
        "You are a programmer at the workshop. Clients' tasks come in on its board through the "
        "day: you take one at a time with claim_task, or are given one by the team leader, work "
        "on it there, where the machines are, and hand it in for the client's checks before the "
        "client withdraws it, at the end of the first day after the one it came in. You sit down "
        "to work there with start_work, or by doing your work, and are at work until you stop "
        "with leave_work or go elsewhere."
    )
    assert "the doctor at the clinic treats illness" in sections["body"]
    assert sections["town"].endswith("help tells more of the town, by topic.")
    assert sections["money"] == (
        "You have $120 to begin with. A client pays $50 for each task accepted: all of it to the "
        "one who handed it in. A tenth of every payment for your work is tax for the town's "
        "treasury, which pays the mayor's salary and what the mayor grants. At midnight the "
        "treasury takes your rent, $20 a day, from your purse, never its last $10, a day's "
        "bread; what it cannot take you owe, to be taken later. You pay for everything in cash; "
        "with pass you hand money or things to anyone with you, put leaves something where you "
        "are for anyone, and get takes what is left there."
    )  # no team leader in this town: the whole payment is the programmer's
    untaxed = Rules(town_config(residents=RESIDENTS)).sections("Mei")["money"]
    assert (
        "all of it to the one who handed it in. At midnight the treasury takes your rent, $20 a "
        "day,"
    ) in untaxed  # no tax, and nobody the treasury pays
    assert sections["people"] == (
        "You live in the shared house on Mill Street with Aisha; Tomas, Olga, Jonas, Lucia and "
        "Vera live in the flat by the college gates. Tomas and Aisha are programmers at the "
        "workshop, Jonas is the chef at the café on the square, Olga is the shopkeeper at the "
        "store, Lucia is the doctor at the clinic and Vera is the mayor at the hall. You can "
        "speak to anyone awake where you are, to everyone there or only to the people you name, "
        "and the others notice that you said something but not what; a conversation lasts until "
        "its people leave it or nobody speaks for 10 minutes. Talking, you can still buy, eat and "
        "hand things over; doing your work leaves the talk."
    )
    assert (
        "Walking from one to another takes 10 minutes, 5 between the workshop and the café"
        in (sections["town"])
    )
    assert "Your home" not in sections["town"]  # one's home is told once, among the people
    assert "a dish, or 3 helpings of bread, is about a day's need" in sections["body"]
    assert sections["sleep"].endswith(
        "At 02:00 whoever is still up falls asleep where they are and wakes at home at 07:00."
    )
    moved = {
        "mill-street-house": ["Mei"],
        "college-flat": ["Tomas", "Aisha", "Olga", "Jonas", "Lucia", "Vera"],
    }
    assert rules.sections("Aisha", moved)["people"].startswith(
        "You live in the flat by the college gates with Tomas, Olga, Jonas, Lucia and Vera; Mei "
        "lives in the shared house on Mill Street."
    )


def test_each_occupation_is_told_its_own_work_and_what_it_is_paid_for():
    leader = dict(RESIDENTS[0], occupation="team-leader")
    rules = Rules(town_config(residents=(leader, RESIDENTS[1], *TRADES, *CARE), tax=0.1))
    told = {name: rules.sections(name) for name in ("Mei", "Olga", "Jonas", "Lucia", "Vera")}
    assert told["Mei"]["work"].startswith(
        "You are the team leader at the workshop. You lead its programmers. Clients' tasks come in "
        "on its board through the day: you can give any of them a task with assign,"
    )
    assert (
        "at the end of the first day after the one it came in. Each midnight your statement "
        "tells you the workshop's day. You sit down"
    ) in told["Mei"]["work"]
    assert (
        "A client pays $50 for each task accepted: $40 to the programmer who handed it in and "
        "$10 to you, the whole for one you hand in."
    ) in told["Mei"]["money"]
    assert (
        "A client pays $50 for each task accepted: $40 to the one who handed it in and $10 to "
        "the team leader."
    ) in rules.sections("Tomas")["money"]
    assert told["Olga"]["work"].startswith(
        "You are the shopkeeper at the store. Its counter is open while you are at work there: "
        "you sell its goods, which are yours, at the prices you set, and order more from the "
        "supplier, which you pay for at once"
    )
    assert (
        "The goods on the shelves are yours: what customers pay at the counter goes to you, and "
        "you pay the supplier for what you order."
    ) in told["Olga"]["money"]
    assert (
        "whoever comes buys a dish, or is handed one by you with pass and pays nothing; you have "
        "one yourself with eat. You buy what you cook with at the store with buy "
        "for_the_kitchen, and pay for it."
    ) in told["Jonas"]["work"]
    assert (
        "What diners pay for your dishes is yours, and you pay for what you cook with."
        in told["Jonas"]["money"]
    )
    assert (
        "Its surgery is open while you are at work there: you examine and treat patients"
        in (told["Lucia"]["work"])
    )
    assert "The fees your patients pay are yours. A tenth of" in told["Lucia"]["money"]
    assert told["Vera"]["work"] == (
        "You are the mayor at the hall. There you read the town's report with report, with "
        "announce you tell every resident whatever you want them to know, and with grant you pay "
        "money from the town's treasury to anyone, for a reason the report gives. Your work is "
        "being about the town, so once you have sat down to work it goes with you wherever you "
        "go. You sit down to work there with start_work, or by doing your work, and are at work "
        "until you stop with leave_work."
    )  # the mayor's duty runs anywhere; everyone else's ends on leaving the workplace
    assert told["Vera"]["money"] == (
        "You have $100 to begin with. The town's treasury pays you a salary of $30 a day at "
        "midnight, as far as it holds the money, and owes you the rest. It takes a tenth of every "
        "payment anyone receives for work in tax, and pays out what you grant. At midnight the "
        "treasury takes your rent, $30 a day, from your purse, never its last $10, a day's bread; "
        "what it cannot take you owe, to be taken later. You pay for everything in cash; with "
        "pass you hand money or things to anyone with you, put leaves something where you are "
        "for anyone, and get takes what is left there."
    )


def test_help_tells_the_detail_by_topic_and_what_one_can_ask_about():
    rules = Rules(TOWN)
    listed = (
        "You can ask about: office, store, restaurant, hospital, hall, money, body, day and places."
    )
    assert rules.help("") == rules.help("weather") == listed
    topics = {topic: rules.help(topic) for topic in TOPICS}
    assert rules.help(" Office ") == topics["office"]
    office = topics["office"]
    for told in (
        "their tasks come in on its board at random through the day, about 0 a day between 08:00 "
        "and 18:00, and whoever is there is told as one comes in",
        "for which the client pays once it is accepted",
        "read_task gives the whole problem without taking it",
        "You can hand in each task at most 2 times a day.",
        "The team leader can give a task to any of the programmers with assign",
        "withdrawn by its client at the end of the first day after the one it came in, held or not",
        "A client pays $50 for each task accepted: all of it to the one who handed it in.",
    ):
        assert told in office, told
    assert "the order comes onto the shelves at 08:00 the next morning" in topics["store"]
    assert "It sells from its shelves, which the shopkeeper sees whenever there" in topics["store"]
    assert (
        "or as the chef hands it over with pass, when nobody pays and the chef bears what it "
        "cost; the chef, at work there, has one with eat and does not buy them."
    ) in topics["restaurant"]
    assert (
        "Nobody is paid for their time. Money comes into the town only from the clients of the "
        "workshop, and leaves it only when the shopkeeper pays the supplier."
    ) in topics["money"]
    assert "With put you leave something where you are, for anyone to take" in topics["money"]
    assert "or when you choose with eat" in topics["body"]
    assert "What customers pay goes to the shopkeeper, the tax withheld." in topics["store"]
    assert (
        "orders more from the supplier outside the town, paying for it at once" in (topics["store"])
    )
    assert (
        "an omelette from 2 units of eggs and 1 unit of vegetables; vegetable soup from 2 units "
        "of vegetables."
    ) in topics["restaurant"]
    assert "An examination, $10 at the start" in topics["hospital"]
    assert (
        "A treatment, $30 at the start, restores 25 of the patient's health" in (topics["hospital"])
    )
    assert "but nobody's purse. With announce the mayor tells every resident" in topics["hall"]
    assert (
        "The patient pays the fee in cash to the doctor, the tax withheld" in (topics["hospital"])
    )
    for told in (
        "A tenth of every payment anyone receives for work, from a client, a customer or a "
        "patient, is withheld at once in tax for the treasury, and you are told how much; money "
        "handed between people is not taxed.",
        "The town's treasury owns the homes: at midnight it takes the rent for your room, and the "
        "daily charge on anything you own that carries one, from your purse, but never its last "
        "$10, a day's bread; what it cannot take you owe, and it is taken at a later midnight.",
        "The treasury pays the mayor a salary of $30 a day, as far as it holds the money, owing "
        "the rest. The mayor may grant money from it to anyone, for a reason the town's report "
        "shows.",
    ):
        assert told in topics["money"], told
    assert "what the treasury holds, took in and paid out, the grants" in topics["hall"]
    assert "With grant the mayor pays money from the treasury to anyone" in topics["hall"]
    assert "At midnight the rent is taken, your health is reckoned" in topics["day"]
    assert "each night costs you 3 of your health and mends nothing" in topics["body"]
    assert "it passes after 5 nights, or when the doctor treats you" in topics["body"]
    assert topics["day"].endswith(
        "When you do nothing, time passes until something happens or 30 minutes have gone by, "
        "and you are told the hour; with wait you let up to 600 minutes pass."
    )
    assert (
        "the shared house on Mill Street $20 (3 rooms, 1 free, little comfort) and the flat by "
        "the college gates $30 (6 rooms, 1 free)"
    ) in topics["places"]
    moved = {"mill-street-house": ["Mei"], "college-flat": ["Tomas", "Aisha", "Olga", "Jonas"]}
    assert "(3 rooms, 2 free, little comfort)" in rules.help("places", moved)
    text = rules.text("Mei")
    assert all(detail not in text for detail in topics.values())
    assert "600 minutes" not in text and "30 minutes" not in text  # the day topic's alone
