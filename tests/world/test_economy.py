"""Purses, the midnight statement and debt, money and things given, and files handed over."""

from __future__ import annotations

from tests.world.conftest import awake_at


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
    await town.call("Mei", "give", to="Aisha", what="money", amount=15)
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
    assert (await town.call("Mei", "give", to="Aisha", what="money", amount=20)).text == (
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


async def test_money_goes_to_anyone_awake_here_and_only_from_what_one_has(make_town):
    town = make_town()
    await awake_at(town)
    gift = await town.call("Mei", "give", to="Tomas", what="money", amount=5)
    assert gift.text == "Tomas is not here."
    assert (await town.call("Mei", "give", to="Mei", what="money", amount=5)).text == (
        "You cannot give to yourself."
    )
    too_much = await town.call("Aisha", "give", to="Mei", what="money", amount=31)
    assert too_much.text == "You do not have $31. Your purse holds $30."
    assert (await town.call("Aisha", "give", to="Mei", what="money", amount=0)).text == (
        "amount must be a whole number of at least 1."
    )
    town.take("Mei")
    given = await town.call("Aisha", "give", to="Mei", what="money", amount=10)  # no word said
    assert given.text == "You gave Mei $10. Your purse holds $20."
    assert town.take("Mei") == ["Aisha gave you $10."]
    assert not town.world.ports["Mei"].interrupt.is_set()
    assert town.world.economy.purses["Mei"] == 130
    await town.until("21:00")
    await town.call("Mei", "sleep", until="07:00")
    asleep = await town.call("Aisha", "give", to="Mei", what="money", amount=1)
    assert asleep.text == "Mei is asleep."


async def test_a_thing_goes_with_its_daily_charge_and_a_stock_feeds_whom_it_is_given(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei, aisha = world.residents["Mei"], world.residents["Aisha"]
    mei.living.things.update({"groceries": 6, "phone": 1})
    assert (await town.call("Aisha", "give", to="Mei", what="phone", amount=1)).text == (
        "You have no phone."
    )
    assert (await town.call("Mei", "give", to="Aisha", what="phone", amount=2)).text == (
        "You have one phone to give."
    )
    assert (await town.call("Mei", "give", to="Aisha", what="groceries", amount=7)).text == (
        "You have only 6 helpings of groceries."
    )
    given = await town.call("Mei", "give", to="Aisha", what="phone", amount=1)
    assert given.text == "You gave Aisha a phone. You have groceries (6 helpings)."
    assert "phone" not in mei.living.things and aisha.living.things["phone"] == 1
    town.take("Aisha")
    aisha.living.satiety = 30  # hungry: she eats what she is given
    given = await town.call("Mei", "give", to="Aisha", what="groceries", amount=2)
    assert given.text == "You gave Aisha 2 helpings of groceries. You have groceries (4 helpings)."
    assert "groceries" not in aisha.living.things and aisha.living.eaten == {"groceries": 2}
    assert town.take("Aisha") == ["Mei gave you 2 helpings of groceries.", "You are well fed."]
    gifts = [e["payload"] for e in world.log.entries() if e["kind"] == "gift"]
    assert gifts == [
        {"to": "Aisha", "item": "phone", "name": "a phone", "quantity": 1},
        {"to": "Aisha", "item": "groceries", "name": "groceries", "quantity": 2},
    ]
    town.rest()
    await town.until("00:00", day=2)  # the phone's daily charge is now Aisha's
    fees = {
        e["actor"]: e["payload"]["fees"] for e in world.log.entries() if e["kind"] == "settlement"
    }
    assert fees == {"Mei": 0, "Tomas": 0, "Aisha": 2}


async def test_a_copy_of_any_file_but_the_journal_reaches_its_recipient_as_text(
    make_town, tmp_path
):
    town = make_town()
    await awake_at(town)
    mei = tmp_path / "agents" / "Mei"
    (mei / "skills" / "bisect.md").write_text("Find the breaking commit by halving the range.\n")
    (mei / "memory" / "letter.md").write_text("Dear Aisha,\n")
    (mei / "memory" / "journal").mkdir()
    (mei / "memory" / "journal" / "2001-01-01.md").write_text("A day.\n")
    (mei / "session.jsonl").write_text("{}\n")
    await town.call("Mei", "say", text="I have a method for you.")
    town.take("Aisha")
    for path in ("../../Aisha/memory/x.md", "session.jsonl", "/etc/passwd", "memory/none.md"):
        refused = await town.call("Mei", "share_file", to=["Aisha"], path=path)
        assert refused.text == f"You have no file {path}."
    journal = await town.call(
        "Mei", "share_file", to=["Aisha"], path="memory/journal/2001-01-01.md"
    )
    assert journal.text == "You can pass on any of your files but your journal."
    shared = await town.call("Mei", "share_file", to=["Aisha"], path="skills/bisect.md")
    assert shared.text == "You passed Aisha a copy of skills/bisect.md."
    assert town.take("Aisha") == [
        "Mei passed you a copy of skills/bisect.md. It reads:\n\nFind the breaking commit by "
        "halving the range.\n"
    ]
    assert not (tmp_path / "agents" / "Aisha" / "skills" / "bisect.md").exists()
    letter = await town.call("Mei", "share_file", to=["Aisha"], path="memory/letter.md")
    assert letter.text == "You passed Aisha a copy of memory/letter.md."
    shares = [e["payload"] for e in town.world.log.entries() if e["kind"] == "skill_shared"]
    assert [(p["file"], p["text"]) for p in shares] == [
        ("skills/bisect.md", "Find the breaking commit by halving the range.\n"),
        ("memory/letter.md", "Dear Aisha,\n"),
    ]


async def test_a_file_is_passed_to_each_one_named_who_is_in_the_conversation(make_town, tmp_path):
    town = make_town()
    await awake_at(town)
    (tmp_path / "agents" / "Mei" / "memory" / "letter.md").write_text("Dear all,\n")
    for name in ("Mei", "Tomas", "Aisha"):
        await town.call(name, "go", place="cafe")
    await town.until("07:30")
    await town.call("Mei", "say", text="A letter for you.", to=["Aisha"])  # Tomas stays out
    path = "memory/letter.md"
    refusals = {
        "Aisha": "to must be a list of names.",  # a name, not a list of them
        (): "Name the people you pass it to.",
        ("Mei",): "You cannot pass a file to yourself.",
        ("Jonas",): "Jonas is not in your conversation.",
        ("Aisha", "Tomas"): "Tomas is not in your conversation.",
    }
    for to, refusal in refusals.items():
        to = to if isinstance(to, str) else list(to)
        assert (await town.call("Mei", "share_file", to=to, path=path)).text == refusal
    assert "skill_shared" not in town.kinds()

    await town.call("Mei", "say", text="And for you.", to=["Tomas"])
    for name in ("Tomas", "Aisha"):
        town.take(name)
    passed = await town.call("Mei", "share_file", to=["Aisha", "Tomas", "Aisha"], path=path)
    assert passed.text == "You passed Aisha and Tomas a copy of memory/letter.md."
    for name in ("Tomas", "Aisha"):
        assert town.take(name) == [f"Mei passed you a copy of {path}. It reads:\n\nDear all,\n"]
    shares = [
        (e["actor"], e["payload"]["to"])
        for e in town.world.log.entries()
        if e["kind"] == "skill_shared"
    ]
    assert shares == [("Mei", "Aisha"), ("Mei", "Tomas")]  # a copy to each, logged one by one
