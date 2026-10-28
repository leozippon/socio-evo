"""The rules as one resident is told them: the money it starts with, its occupation, wages and
rent, what is for sale, where people live and meet and which rooms are free, and the people it
knows already."""

from __future__ import annotations

from tests.world.conftest import RESIDENTS, town_config
from world.rules import TOPICS, Rules

TIES = (
    dict(RESIDENTS[0], ties={"Aisha": "Aisha has the room next to yours and shares the kitchen."}),
    RESIDENTS[1],
    dict(RESIDENTS[2], ties={"Mei": "Mei was in the house before you came."}),
)


def test_the_rules_tell_the_purse_the_wages_the_rent_the_shops_and_where_people_live_and_meet():
    rules = Rules(town_config(residents=TIES))
    sections = rules.sections("Mei")
    assert sections["money"] == (
        "You have $120 to begin with. The town keeps one fund, which takes in what clients pay "
        "for the work, the rent and what is sold, and pays everyone who works. You are a "
        "programmer at the workshop: you are paid $7 an hour for your time at work there, from "
        "sitting down to work until you stop, and $20 at once for each task of yours accepted. "
        "At midnight your wages for the day are paid into your purse, with the rent for your "
        "room at the shared house on Mill Street, $20 a day, and the daily charge on anything "
        "you own that carries one taken out of them, and you get a statement of your money; "
        "what is in your purse is never touched by rent. When your wages do not cover the rent, "
        "you owe the rest, and it is taken from your next wages; when the fund cannot pay you, "
        "it owes you the rest and pays it with your next wages. You pay for everything in cash "
        "from your purse, and cannot pay more than it holds. With give you can hand money, a "
        "thing you own (with any daily charge on it) or helpings of a stock to anyone awake "
        "where you are, as a gift or on terms you agree between you; the town keeps no account "
        "of it."
    )
    assert (
        "At midnight your wages for the day are paid, with your rent taken out of them"
        in (sections["day"])
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
        "left, inventory tells you."
    )
    assert sections["health"] == (
        "Through the day you get hungry, and what you eat restores you: a meal, or 3 helpings of "
        "groceries, is about a day's need. You tire with the hours awake, faster at work and on "
        "the road, and sleep restores you, the more the better your home; exhausted, you stop "
        "work and cannot work again until you have slept. A day that ends with you starving or "
        "exhausted, or lived in a home of little comfort, wears your health down; a day in which "
        "you have eaten and rested mends it. When your health is gone, you take to your bed at "
        "home, carried there if you are elsewhere, and keep to it until you are treated. You can "
        "take stock of how you feel at any time with how_am_i, and at the clinic an examination "
        "tells you exactly how you stand and treatment restores your health."
    )
    assert sections["day"].endswith(
        "At 02:00 anyone still up falls asleep where it is and wakes at home at 07:00. When you "
        "do nothing, time passes until something happens or 30 minutes have gone by, and you are "
        "told the hour; with wait you let up to 600 minutes pass."
    )
    moved = {"mill-street-house": ["Mei"], "college-flat": ["Tomas", "Aisha"]}
    assert "(3 rooms, 2 free, little comfort)" in rules.help("Mei", "places", moved)
    assert "Aisha (the flat by the college gates)" in rules.help("Mei", "people", moved)
    assert sections["sleep"].endswith(
        "In bed, before you fall asleep, you can look back over your day and see to your files."
    )
    people = sections["people"]
    assert "Tomas (the flat by the college gates) and Aisha (the shared house on Mill Street)" in (
        people
    )
    assert (
        "People run into one another at the café on the square, the park, the store and the clinic"
    ) in people
    assert "call on someone at home, or find them at the workshop." in people
    assert "the client pays the town $50 once it is accepted" in sections["work"]
    assert "the client's own checks" in sections["work"]
    assert "posts it on its board there" in sections["work"]
    assert "You work on it at the workshop, where the machines are." in sections["work"]
    assert "wherever you are" not in sections["work"]
    assert rules.help("Mei", "Money") == sections["money"]
    assert rules.help("Mei", "weather") == f"You can ask about: {', '.join(TOPICS)}."
    text = rules.text("Mei")
    assert text.startswith("How the town works.\n\nPlaces. ") and "\n\nSleep. " in text
    assert "\n\nHealth. Through the day you get hungry" in text


def test_ties_are_told_in_the_rules_to_those_who_have_them():
    town = Rules(town_config(residents=TIES))
    assert town.sections("Mei")["people"].endswith(
        "Some of them you know already. Aisha has the room next to yours and shares the kitchen."
    )
    assert "know already" not in town.sections("Tomas")["people"]
