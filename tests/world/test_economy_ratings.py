"""Purses, the midnight statement and debt, gifts, skills handed over, and ratings."""

from __future__ import annotations

from tests.world.conftest import awake_at, town_config


async def test_the_midnight_statement_tells_the_days_money_and_debt(make_town):
    town = make_town()
    await awake_at(town)
    await town.call("Mei", "go", place="workshop")
    await town.until("09:00")
    await town.call("Mei", "start_work")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    await town.call("Mei", "submit")
    await town.call("Mei", "leave_work")
    await town.call("Aisha", "go", place="workshop")
    await town.until("10:00")
    await town.call("Aisha", "say", text="Could you spare some money?")
    await town.call("Mei", "give_money", to="Aisha", amount=15)
    for name in town.world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    assert town.take("Mei")[-2:] == [
        "Your statement for Monday 1 January: paid $20 for task 1; gave $15 to Aisha; living "
        "cost $30. Your purse holds $95.",
        "It is 00:00: the day's board is posted at the workshop.",  # she is still there
    ]
    assert town.take("Aisha")[-2] == (
        "Your statement for Monday 1 January: received $15 from Mei; living cost $30. Your "
        "purse holds $15."
    )
    town.rest()
    await town.until("00:00", day=3)
    assert [p.text for p in town.heard["Aisha"] if p.kind == "settlement"][-1] == (
        "Your statement for Tuesday 2 January: living cost $30. You are $15 in debt."
    )
    assert town.world.economy.purses == {"Mei": 65, "Tomas": 120, "Aisha": -15}
    assert "You are $15 in debt." in town.world.ports["Aisha"].situation()


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


async def test_ratings_go_to_those_one_was_with_and_arrive_anonymously_the_next_night(make_town):
    town = make_town()
    await awake_at(town)
    await town.call("Tomas", "go", place="mill-street-house")
    await town.until("07:10")
    await town.call("Tomas", "go", place="college-flat")
    await town.until("20:00")
    for name in town.world.residents:
        await town.call(name, "sleep", until="07:00", journal=f"{name}'s first day.")
    in_bed = town.take("Mei")[-1]
    assert "Nobody rated you last night." in in_bed
    assert "rate the people you spent time with today (Aisha and Tomas)" in in_bed

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
    assert "spent time with today (Aisha)" in told  # they woke in the same house
    read = [e for e in town.world.log.entries() if e["kind"] == "sleep"][-1]
    assert read["payload"]["ratings_read"] == [[2, "Too loud."], [4, "Kind words."]]


async def test_nobody_can_be_rated_without_having_been_met(make_town):
    town = make_town()
    await awake_at(town)
    await town.until("20:00")
    await town.call("Tomas", "sleep", until="07:00", journal="Alone.")
    refused = await town.call("Tomas", "rate", resident="Mei", score=3, reason="Never saw her.")
    assert refused.text == "You did not spend time with Mei today."
    assert (await town.call("Tomas", "rate", resident="Tomas", score=5, reason="Me.")).text == (
        "You did not spend time with Tomas today."
    )


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
    assert refused.text == "You did not spend time with Aisha today."
