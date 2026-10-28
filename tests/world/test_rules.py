"""The rules as one resident is told them: six short sections, its own occupation and workplace,
its money, its body, who lives and works where, and sleep; and `help`, which tells the detail by
topic: the work of each place of work, money, the body, the day and the places."""

from __future__ import annotations

from tests.world.conftest import CARE, RESIDENTS, TRADES, town_config
from world.rules import SECTIONS, TOPICS, Rules

TOWN = town_config(residents=RESIDENTS + TRADES + CARE)


def test_the_rules_are_six_short_sections_ones_own_work_first():
    rules = Rules(TOWN)
    sections = rules.sections("Mei")
    assert list(sections) == list(SECTIONS)
    text = rules.text("Mei")
    assert text.startswith("How the town works.\n\nThe town. The places, with the short name ")
    assert [line.split(".")[0] for line in text.split("\n\n")[1:]] == [
        "The town", "Work", "Money", "Body", "People", "Sleep",
    ]  # fmt: skip
    assert len(text) < 3000
    assert sections["work"] == (
        "You are a programmer at the workshop. Clients' tasks come in on its board through the "
        "day: you take one at a time with claim_task, or are given one by the team leader, work "
        "on it there, where the machines are, and hand it in for the client's checks before the "
        "client withdraws it, at the end of the first day after the one it came in. You sit down "
        "to work there with start_work, or by doing your work, and are at work until you stop "
        "with leave_work, go elsewhere or go to sleep."
    )
    assert "the doctor at the clinic treats illness" in sections["body"]
    assert sections["town"].endswith("help tells more of the town, by topic.")
    assert sections["money"] == (
        "You have $120 to begin with. The town's fund pays you $7 an hour for your time at work "
        "at the workshop, and $20 at once for each task of yours accepted. At midnight your "
        "wages are paid into your purse, with the rent for your room, $20 a day, taken out of "
        "them. You pay for everything in cash from your purse, and with give you can hand money "
        "or things to anyone with you."
    )
    assert sections["people"] == (
        "You live in the shared house on Mill Street with Aisha; Tomas, Olga, Jonas, Lucia and "
        "Vera live in the flat by the college gates. Tomas and Aisha are programmers at the "
        "workshop, Jonas is the chef at the café on the square, Olga is the shopkeeper at the "
        "store, Lucia is the doctor at the clinic and Vera is the mayor at the hall. You can "
        "speak to anyone awake where you are, to everyone there or only to the people you name, "
        "and the others notice that you said something but not what; a conversation lasts until "
        "its people leave it or nobody speaks for 10 minutes."
    )
    assert (
        "Walking from one to another takes 10 minutes, 5 between the workshop and the café"
        in (sections["town"])
    )
    assert "Your home is the shared house on Mill Street." in sections["town"]
    assert "a dish, or 3 helpings of bread, is about a day's need" in sections["body"]
    assert sections["sleep"].endswith(
        "At 02:00 anyone still up falls asleep where it is and wakes at home at 07:00."
    )
    moved = {
        "mill-street-house": ["Mei"],
        "college-flat": ["Tomas", "Aisha", "Olga", "Jonas", "Lucia", "Vera"],
    }
    assert rules.sections("Aisha", moved)["people"].startswith(
        "You live in the flat by the college gates with Tomas, Olga, Jonas, Lucia and Vera; Mei "
        "lives in the shared house on Mill Street."
    )


def test_each_occupation_is_told_its_own_work_and_sum():
    leader = dict(RESIDENTS[0], occupation="team-leader")
    rules = Rules(town_config(residents=(leader, *TRADES, *CARE)))
    told = {name: rules.sections(name) for name in ("Mei", "Olga", "Jonas", "Lucia", "Vera")}
    assert told["Mei"]["work"].startswith(
        "You are the team leader at the workshop. You lead its programmers. Clients' tasks come in "
        "on its board through the day: you can give any of them a task with assign,"
    )
    assert (
        "$10 at once for each task of the programmers' accepted and $20 for each task of your "
        "own accepted."
    ) in told["Mei"]["money"]
    assert told["Olga"]["work"].startswith(
        "You are the shopkeeper at the store. It is open while you are at work there: you sell "
        "its goods at the prices you set,"
    )
    assert "and $2 at once for each sale." in told["Olga"]["money"]
    assert (
        "You buy what you cook with at the store with buy for_the_kitchen, and the fund pays."
        in (told["Jonas"]["work"])
    )
    assert (
        "Its surgery is open while you are at work there: you examine and treat patients"
        in (told["Lucia"]["work"])
    )
    assert "and $4 at once for each patient examined or treated." in told["Lucia"]["money"]
    assert told["Vera"]["work"].startswith(
        "You are the mayor at the hall. There you read the town's report with report, and with "
        "announce you tell every resident whatever you want them to know."
    )
    assert (
        told["Vera"]["money"].endswith(
            "at the hall. At midnight your wages are paid into your purse, with the rent for your "
            "room, $30 a day, taken out of them. You pay for everything in cash from your purse, "
            "and with give you can hand money or things to anyone with you."
        )
        and "at once" not in told["Vera"]["money"]
    )  # the mayor has no sum


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
        "the client pays the town $50 once it is accepted",
        "read_task gives the whole problem without taking it",
        "You can hand in each task at most 2 times a day.",
        "The team leader can give a task to any of the programmers with assign",
        "withdrawn by its client at the end of the first day after the one it came in, held or not",
        "pays the one who handed it in $20 and the team leader $10.",
    ):
        assert told in office, told
    assert "the goods arrive at 08:00 the next morning" in topics["store"]
    assert "Each sale pays the shopkeeper $2." in topics["store"]
    assert (
        "an omelette from 2 units of eggs and 1 unit of vegetables; vegetable soup from 2 units "
        "of vegetables."
    ) in topics["restaurant"]
    assert "An examination, $10 at the start" in topics["hospital"]
    assert (
        "A treatment, $30 at the start, restores 25 of the patient's health" in (topics["hospital"])
    )
    assert "but nobody's purse. With announce the mayor tells every resident" in topics["hall"]
    assert "when the fund cannot pay you, it owes you the rest" in topics["money"]
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
