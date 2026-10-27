"""Purses, the midnight statement and debt, money handed over, skills handed over, and ratings on
and off."""

from __future__ import annotations

import re

import pytest

from tests.world.conftest import awake_at, town_config


async def test_the_midnight_statement_tells_the_days_money_and_debt_bars_buying(make_town):
    town = make_town()
    await awake_at(town)
    await town.call("Mei", "go", place="workshop")
    await town.until("09:00")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    await town.call("Mei", "submit")
    await town.call("Mei", "leave_work")
    await town.call("Aisha", "go", place="workshop")
    await town.until("10:00")
    await town.call("Aisha", "say", text="Could you spare some money?")
    await town.call("Mei", "give_money", to="Aisha", amount=15)
    await town.call("Aisha", "go", place="store")
    await town.until("10:10")
    await town.call("Aisha", "buy", item="coat")  # $30 of her $45
    for name in town.world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    assert town.take("Mei")[-1] == (  # still at the workshop, where no board is posted at night
        "Your statement for Monday 1 January: paid $20 for task 1; gave $15 to Aisha; rent for "
        "your room at the shared house on Mill Street $20. You had nothing to eat today. You are "
        "hungry. You are fresh. You are in good health. Your purse holds $105."
    )
    assert town.take("Aisha")[-1] == (
        "Your statement for Monday 1 January: received $15 from Mei; bought a coat for $30; rent "
        "for your room at the shared house on Mill Street $20. You had nothing to eat today. You "
        "are hungry. You are fresh. You are in good health. You are $5 in debt."
    )
    assert town.world.economy.purses == {"Mei": 105, "Tomas": 150, "Aisha": -5}
    assert "You are $5 in debt." in town.world.ports["Aisha"].situation()
    # In debt one is still paid and still owes rent, and can still be given money, but can buy
    # nothing until the purse covers the price: cash only.
    assert (await town.call("Aisha", "buy", item="groceries")).text == (
        "You do not have $12. You are $5 in debt."
    )
    await town.call("Mei", "go", place="store")
    await town.until("00:10", day=2)
    await town.call("Mei", "say", text="Here, pay me back when you can.", to=["Aisha"])
    assert (await town.call("Mei", "give_money", to="Aisha", amount=20)).text == (
        "You gave Aisha $20. Your purse holds $85."
    )
    assert (await town.call("Aisha", "buy", item="groceries")).text == (
        "You bought groceries for $12. You have groceries (7 helpings) and a coat. Your purse "
        "holds $3."  # she ate two helpings as she bought them
    )
    town.rest()
    await town.until("00:00", day=3)
    assert [p.text for p in town.heard["Aisha"] if p.kind == "settlement"][-1] == (
        "Your statement for Tuesday 2 January: received $20 from Mei; bought groceries for $12; "
        "rent for your room at the shared house on Mill Street $20. You ate today: 3 helpings of "
        "groceries. You are hungry. You are fresh. You are in good health. You are $17 in debt."
    )
    assert town.world.economy.purses == {"Mei": 65, "Tomas": 120, "Aisha": -17}
    gifts = [e for e in town.world.log.entries() if e["kind"] == "gift"]
    assert [(e["actor"], e["payload"]) for e in gifts] == [
        ("Mei", {"to": "Aisha", "amount": 15}),
        ("Mei", {"to": "Aisha", "amount": 20}),
    ]  # a gift or a loan, on their own terms: the world keeps no account of which


async def test_gifts_go_only_to_conversation_partners_and_only_from_what_one_has(make_town):
    town = make_town()
    await awake_at(town)
    await town.call("Aisha", "say", text="Hello.")
    gift = await town.call("Mei", "give_money", to="Tomas", amount=5)
    assert gift.text == "Tomas is not in your conversation."
    assert (await town.call("Mei", "give_money", to="Mei", amount=5)).text == (
        "Mei is not in your conversation."
    )
    too_much = await town.call("Aisha", "give_money", to="Mei", amount=31)
    assert too_much.text == "You do not have $31. Your purse holds $30."
    assert (await town.call("Aisha", "give_money", to="Mei", amount=0)).text == (
        "amount must be a whole number of at least 1."
    )
    town.take("Mei")
    given = await town.call("Aisha", "give_money", to="Mei", amount=10)
    assert given.text == "You gave Mei $10. Your purse holds $20."
    assert town.take("Mei") == ["Aisha gave you $10."]
    assert not town.world.ports["Mei"].interrupt.is_set()
    assert town.world.economy.purses["Mei"] == 130


async def test_a_shared_skill_reaches_its_recipient_as_text(make_town, tmp_path):
    town = make_town()
    await awake_at(town)
    skill = tmp_path / "agents" / "Mei" / "skills" / "bisect.md"
    skill.write_text("Find the breaking commit by halving the range.\n")
    await town.call("Mei", "say", text="I have a method for you.")
    town.take("Aisha")
    unknown = await town.call("Mei", "share_skill", to="Aisha", skill="../../background")
    assert unknown.text == "You have no skill called ../../background."
    shared = await town.call("Mei", "share_skill", to="Aisha", skill="bisect.md")
    assert shared.text == "You passed the skill “bisect” to Aisha."
    assert town.take("Aisha") == [
        "Mei passed the skill “bisect” to you. It reads:\n\nFind the breaking commit by halving "
        "the range.\n"
    ]
    assert not (tmp_path / "agents" / "Aisha" / "skills" / "bisect.md").exists()


async def test_skills_cannot_be_passed_on_when_they_are_not_shareable(make_town, tmp_path):
    town = make_town(town_config(shareable=False))
    await awake_at(town)
    (tmp_path / "agents" / "Mei" / "skills" / "bisect.md").write_text("Halve.\n")
    await town.call("Mei", "say", text="Hello.")
    refused = await town.call("Mei", "share_skill", to="Aisha", skill="bisect")
    assert refused.text == "Skills cannot be passed on here."
    assert "skill" not in town.world.rules.text("Mei").lower().replace("skills folder", "")


async def test_ratings_go_to_those_one_spoke_with_and_arrive_anonymously_the_next_night(make_town):
    town = make_town()
    await awake_at(town)
    await town.call("Tomas", "go", place="mill-street-house")
    await town.until("07:10")
    await town.call("Tomas", "say", text="Morning, Mei.", to=["Mei"])  # Aisha hears only that
    await town.call("Mei", "say", text="Morning, both of you.")  # Aisha is drawn in
    await town.call("Tomas", "go", place="college-flat")
    await town.until("20:00")
    for name in town.world.residents:
        await town.call(name, "sleep", until="07:00", journal=f"{name}'s first day.")
    in_bed = town.take("Mei")[-1]
    assert "Nobody rated you last night." in in_bed
    assert "rate the people you spoke with today (Aisha and Tomas)" in in_bed
    assert "rate the people you spoke with today (Mei)" in town.take("Aisha")[-1]
    refused = await town.call("Tomas", "rate", resident="Aisha", score=3, reason="Quiet.")
    assert refused.text == "You did not speak with Aisha today."  # though they shared a room

    assert (
        await town.call("Tomas", "rate", resident="Mei", score=4, reason="Kind words.")
    ).text == "You rated Mei 4 of 5."
    again = await town.call("Tomas", "rate", resident="Mei", score=1, reason="Changed my mind.")
    assert again.text == "You have already rated Mei tonight."
    assert (await town.call("Aisha", "rate", resident="Mei", score=6, reason="x")).text == (
        "score must be a whole number from 1 to 5."
    )
    assert (await town.call("Aisha", "rate", resident="Mei", score=2, reason=" ")).text == (
        "Give a reason with your rating."
    )
    await town.call("Aisha", "rate", resident="Mei", score=2, reason="Too loud.")
    await town.call("Mei", "rate", resident="Tomas", score=5, reason="Came by.")
    town.rest()

    await town.until("21:00", day=2)
    await town.call("Mei", "sleep", until="07:00", journal="Second day.")
    told = [p.text for p in town.heard["Mei"] if p.kind == "sleep"][-1]
    assert (
        "Last night others rated you, without their names: 2 of 5, saying “Too loud.”; 4 of 5, "
        "saying “Kind words.”." in told
    )
    ratings = told.split("Last night")[1].split("Before you")[0]
    assert "Tomas" not in ratings and "Aisha" not in ratings
    assert "rate the people" not in told  # waking in the same house is no conversation
    read = [e for e in town.world.log.entries() if e["kind"] == "sleep"][-1]
    assert read["payload"]["ratings_read"] == [[2, "Too loud."], [4, "Kind words."]]


async def test_nobody_can_be_rated_without_having_been_met(make_town):
    town = make_town()
    await awake_at(town)
    await town.until("20:00")
    await town.call("Tomas", "sleep", until="07:00", journal="Alone.")
    refused = await town.call("Tomas", "rate", resident="Mei", score=3, reason="Never saw her.")
    assert refused.text == "You did not speak with Mei today."
    assert (await town.call("Tomas", "rate", resident="Tomas", score=5, reason="Me.")).text == (
        "You did not speak with Tomas today."
    )


async def test_with_ratings_off_nothing_a_resident_reads_mentions_them(make_town):
    town = make_town(town_config(ratings=False))
    await awake_at(town)
    world = town.world
    assert "rate" not in [spec.name for spec in world.tool_specs]
    texts = [world.rules.text("Mei"), world.rules.people_notes("Mei")]
    texts += [spec.description for spec in world.tool_specs]
    await town.call("Tomas", "go", place="mill-street-house")
    await town.until("07:10")
    await town.call("Tomas", "say", text="Morning, Mei.", to=["Mei"])
    texts.append(world.ports["Mei"].situation())
    await town.call("Tomas", "go", place="college-flat")
    await town.until("20:00")
    await town.call("Mei", "sleep", until="07:00", journal="A day.")
    in_bed = town.take("Mei")[-1]
    assert in_bed == (
        "You are in bed and will wake at 07:00; your journal entry for today is kept. Before you "
        "fall asleep you can look back over your day and see to your files; you fall asleep once "
        "you have nothing more to do."
    )
    refused = await town.call("Mei", "go", place="park")  # what one may still do in bed
    texts += [in_bed, world.ports["Mei"].situation(), refused.text]
    assert [text for text in texts if re.search(r"\brat(e|es|ed|ing|ings)\b", text)] == []
    with pytest.raises(KeyError):  # not declared, so as unknown as any other name
        await town.call("Mei", "rate", resident="Tomas", score=4, reason="x")
    slept = [e for e in world.log.entries() if e["kind"] == "sleep"][-1]
    assert slept["payload"]["ratings_read"] == []


async def test_an_isolated_resident_meets_nobody_and_hears_of_no_ratings(make_town):
    town = make_town(town_config("isolated"))
    await awake_at(town)
    mei = town.world.residents["Mei"]
    assert town.world.company(mei) == []  # Aisha shares the house, in another town
    assert (
        await town.call("Mei", "say", text="Hello?")
    ).text == "There is nobody here to hear you."
    await town.until("20:00")
    await town.call("Mei", "sleep", until="07:00", journal="Quiet.")
    in_bed = town.take("Mei")[-1]
    assert "rated" not in in_bed and "rate" not in in_bed
    refused = await town.call("Mei", "rate", resident="Aisha", score=3, reason="x")
    assert refused.text == "You did not speak with Aisha today."
