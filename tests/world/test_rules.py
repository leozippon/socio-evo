"""The rules as one resident is told them: the money it starts with and the day's cost, where
people live and meet, the people it knows already in the town mode and nowhere else, and the seed
of its notes on people."""

from __future__ import annotations

from tests.world.conftest import B_EXCHANGE, RESIDENTS, town_config
from world.rules import TOPICS, Rules

TIES = (
    dict(RESIDENTS[0], ties={"Aisha": "Aisha has the room next to yours and shares the kitchen."}),
    RESIDENTS[1],
    dict(RESIDENTS[2], ties={"Mei": "Mei was in the house before you came."}),
)


def test_the_rules_tell_the_purse_the_living_cost_and_where_people_live_and_meet():
    rules = Rules(town_config(residents=TIES))
    sections = rules.sections("Mei")
    assert sections["money"].startswith(
        "You have $120 to begin with. Living here costs $30 a day, rent and board, taken from "
        "your purse at midnight"
    )
    assert "Your home is the shared house on Mill Street." in sections["places"]
    people = sections["people"]
    assert "Tomas (the flat by the college gates) and Aisha (the shared house on Mill Street)" in (
        people
    )
    assert "People run into one another at the café on the square and the park" in people
    assert "call on someone at home, or find them at the workshop while they work" in people
    assert "pays $20" in sections["work"] and "the client's own checks" in sections["work"]
    assert rules.help("Mei", "Money") == sections["money"]
    assert rules.help("Mei", "weather") == f"You can ask about: {', '.join(TOPICS)}."
    text = rules.text("Mei")
    assert text.startswith("How the town works.\n\nPlaces. ") and "\n\nSleep. " in text


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
