"""The rules as one resident is told them: the money it starts with, its rent and what is for
sale, where people live and meet and which rooms are free, the people it knows already in the
town mode and nowhere else, and the seed of its notes on people."""

from __future__ import annotations

from tests.world.conftest import B_EXCHANGE, RESIDENTS, town_config
from world.rules import TOPICS, Rules

TIES = (
    dict(RESIDENTS[0], ties={"Aisha": "Aisha has the room next to yours and shares the kitchen."}),
    RESIDENTS[1],
    dict(RESIDENTS[2], ties={"Mei": "Mei was in the house before you came."}),
)


def test_the_rules_tell_the_purse_the_rent_the_shops_and_where_people_live_and_meet():
    rules = Rules(town_config(residents=TIES))
    sections = rules.sections("Mei")
    assert sections["money"].startswith(
        "You have $120 to begin with. Your room at the shared house on Mill Street costs $20 a "
        "day; rent, and the daily charge on anything you own that carries one, is taken from "
        "your purse at midnight, when you get a statement of your money. You pay for everything "
        "in cash."
    )
    assert sections["money"].endswith(
        "A purse can go below zero when rent is taken; you are then in debt, and can still be "
        "paid, pay your rent and receive money, but can buy nothing until your purse covers the "
        "price. You can hand money to someone you are talking with, as a gift or a loan, on "
        "terms you agree between you; the town keeps no account of it."
    )
    assert "Your home is the shared house on Mill Street." in sections["places"]
    assert (
        "The homes, with the rent a day for a room and the rooms free: the shared house on Mill "
        "Street $20 (3 rooms, 1 free, little comfort) and the flat by the college gates $30 (6 "
        "rooms, 5 free)."
    ) in sections["places"]
    assert sections["shopping"] == (
        "For sale, paid in cash with buy: at the café on the square, a meal at the café ($10); at "
        "the store, groceries ($12, 9 helpings), a bicycle ($50), a phone ($40, then $2 a day) "
        "and a coat ($30); at the clinic, an examination ($10) and treatment ($25). A meal at the "
        "café: eaten on the spot, the day's food. Groceries: kept in stock and eaten a helping at "
        "a time whenever you could eat, at most 3 helpings a day. With a bicycle your journeys "
        "take half the time. With a phone you can write to anyone else who has one, wherever "
        "they are, with message; they read it when they next look up from what they are doing. "
        "What you wear "
        "and carry, others see: with a coat, in a new coat. What you have, and how much of it is "
        "left, is told with help on money."
    )
    assert sections["health"] == (
        "Through the day you get hungry, and what you eat restores you: a meal, or 3 helpings of "
        "groceries, is about a day's need. You tire with the hours awake, faster at work and on "
        "the road, and sleep restores you, the more the better your home; too tired, you cannot "
        "sit down to work. A day that ends with you starving or exhausted, or lived in a home of "
        "little comfort, wears your health down; a day in which you have eaten and rested mends "
        "it. When your health is gone, you die. You can take stock of how you feel at any time "
        "with how_am_i, and at the clinic an examination tells you exactly how you stand and "
        "treatment restores your health."
    )
    assert "phone" not in Rules(town_config("isolated")).sections("Mei")["shopping"]
    moved = {"mill-street-house": ["Mei"], "college-flat": ["Tomas", "Aisha"]}
    assert "(3 rooms, 2 free, little comfort)" in rules.help("Mei", "places", moved)
    assert "Aisha (the flat by the college gates)" in rules.help("Mei", "people", moved)
    assert "rate" not in Rules(town_config(ratings=False)).sections("Mei")["sleep"]
    assert "rate each person you spoke with" in sections["sleep"]
    people = sections["people"]
    assert "Tomas (the flat by the college gates) and Aisha (the shared house on Mill Street)" in (
        people
    )
    assert (
        "People run into one another at the café on the square, the park, the store and the clinic"
    ) in people
    assert "call on someone at home, or find them at the workshop." in people
    assert "pays $20" in sections["work"] and "the client's own checks" in sections["work"]
    assert "posts it on its board there" in sections["work"]
    assert "You can work on it wherever you are, not only at the workshop." in sections["work"]
    assert rules.help("Mei", "Money") == sections["money"]
    assert rules.help("Mei", "weather") == f"You can ask about: {', '.join(TOPICS)}."
    text = rules.text("Mei")
    assert text.startswith("How the town works.\n\nPlaces. ") and "\n\nSleep. " in text
    assert "\n\nHealth. Through the day you get hungry" in text


def test_ties_are_told_in_the_town_mode_and_seed_the_notes_on_people():
    town = Rules(town_config(residents=TIES))
    assert town.sections("Mei")["people"].endswith(
        "Some of them you know already. Aisha has the room next to yours and shares the "
        "kitchen. You can pass one of your skills to someone you are talking with; they receive "
        "its text."
    )
    assert town.people_notes("Mei") == (
        "# People\n\nAisha has the room next to yours and shares the kitchen.\n"
    )
    assert "know already" not in town.sections("Tomas")["people"]
    assert town.people_notes("Tomas") == "# People\n"
    for config in (
        town_config("isolated", residents=TIES),
        town_config("isolated", exchange=B_EXCHANGE, residents=TIES),
    ):
        alone = Rules(config)
        assert "Aisha" not in alone.sections("Mei")["people"]
        assert alone.people_notes("Mei") == "# People\n"
    paired = Rules(town_config("isolated", exchange=B_EXCHANGE, residents=TIES))
    assert "each with 3 turns to speak" in paired.sections("Mei")["day"]
