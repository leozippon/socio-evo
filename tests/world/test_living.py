"""What a resident keeps and the homes: ready food eaten from the inventory as one gets hungry,
a durable kept and billed, a bicycle that shortens the walk, messages between phone owners
wherever they are, what one wears seen by others, and moving into a home with a free room. Buying
is in test_shops; what the body makes of food, sleep and work is in test_body."""

from __future__ import annotations

from tests.support.towns import at, awake_at, town_config
from world.config import TownConfig


async def test_ready_food_is_eaten_a_helping_at_a_time_and_the_statement_tells_what_is_left(
    make_town,
):
    town = make_town()
    await awake_at(town)
    world = town.world
    tomas = world.residents["Tomas"]
    tomas.inventory.items["bread"] = 9
    assert (await town.call("Tomas", "inventory")).text == "Money: $180.\nBread: 9 helpings."
    for name in world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    statements = {name: town.take(name)[-1] for name in world.residents}
    assert statements["Tomas"] == (  # helpings, eaten as he could eat
        "Your statement for Monday 1 January: no time at work; rent for your room at the flat "
        "by the college gates $30; your wages fell $30 short of that; you owe it, and it is "
        "taken from your next wages. You ate today: 2 helpings of bread. You are well fed. You "
        "are fresh. You are in good health. Your purse holds $180."
    )
    owed = "your wages fell $20 short of that; you owe it, and it is taken from your next wages"
    assert statements["Aisha"] == (
        "Your statement for Monday 1 January: no time at work; rent for your room at the shared "
        f"house on Mill Street $20; {owed}. You had nothing to eat today. You are hungry. You "
        "are fresh. You are in good health. Your purse holds $30."
    )
    # The day's record starts afresh; the bread went down by the two helpings Tomas ate when
    # he could eat, at 12:00 and 21:00. Aisha, full when the town began, is hungry but not yet
    # starving at the first midnight.
    assert world.nourishment(tomas) == 0 and tomas.inventory.items == {"bread": 7}
    settled = [e for e in world.log.entries() if e["kind"] == "settlement"]
    assert [e["payload"]["nourishment"] for e in settled] == [0, 68, 0]
    assert settled[2]["payload"]["night"] == {"poor_home": -2, "recovery": 5}

    # The statement tells what is left once it is less than a day's food, and when it is gone.
    town.rest()
    await town.until("00:01", day=5)
    statements = [p.text for p in town.heard["Tomas"] if p.kind == "settlement"]
    notes = [
        note
        for text in statements
        for note in ("helpings of bread left", "used up your bread")
        if note in text
    ]
    assert notes == ["helpings of bread left", "used up your bread"]
    assert tomas.inventory.items == {}


async def test_a_durable_is_kept_and_its_charge_is_billed_each_midnight_while_owned(make_town):
    town = make_town()
    await awake_at(town)
    town.world.residents["Mei"].inventory.items["phone"] = 1
    town.take("Mei")
    await town.until("00:00", day=2)
    assert town.take("Mei")[-1] == (
        "Your statement for Monday 1 January: no time at work; rent for your room at the shared "
        "house on Mill Street $20; the daily charge on a phone $2; your wages fell $22 short of "
        "that; you owe it, and it is taken from your next wages. You had nothing to eat today. "
        "You are hungry. You are fresh. You are in good health. Your purse holds $120."
    )
    paid = [e for e in town.world.log.entries() if e["kind"] == "wage"]
    assert {k: paid[0]["payload"][k] for k in ("rent", "charges", "arrears", "money")} == {
        "rent": 20, "charges": 2, "arrears": 22, "money": 120,
    }  # fmt: skip
    assert (await town.call("Mei", "inventory")).text == (
        "Money: $120.\nA phone, with a daily charge of $2."
    )


async def test_a_bicycle_halves_the_walk(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei = world.residents["Mei"]
    await town.call("Mei", "go", place="store")
    assert mei.base.arrival == at("07:10")  # ten minutes on foot
    await town.until("07:10")
    mei.inventory.items["bicycle"] = 1
    assert (await town.call("Mei", "go", place="workshop")).text == (
        "You set off for the workshop and will arrive at 07:15."
    )
    assert world.travel_minutes(mei, "workshop", "cafe") == 3  # five minutes, halved and rounded up
    assert world.travel_minutes(world.residents["Aisha"], "workshop", "cafe") == 5


async def test_a_message_reaches_a_phone_owner_wherever_it_is_and_waits_while_it_sleeps(
    make_town, tmp_path
):
    town = make_town()
    await awake_at(town)
    world = town.world
    assert (await town.call("Mei", "message", to="Tomas", text="Hello?")).text == (
        "You have no phone."
    )
    world.residents["Mei"].inventory.items["phone"] = 1
    assert (await town.call("Mei", "message", to="Tomas", text="Hello?")).text == (
        "Tomas has no phone."
    )
    world.residents["Tomas"].inventory.items["phone"] = 1
    assert (await town.call("Mei", "message", to="Zoe", text="Hello?")).text == (
        "There is nobody called Zoe in the town."
    )
    assert (await town.call("Mei", "message", to="Mei", text="Hello?")).text == (
        "You cannot write to yourself."
    )
    assert (await town.call("Mei", "message", to="Tomas", text=" ")).text == "You wrote nothing."
    await town.call("Tomas", "go", place="workshop")
    await town.until("07:10")
    for name in world.residents:
        town.take(name)
    assert (await town.call("Mei", "message", to="Tomas", text="Lunch at one?")).text == (
        "You wrote to Tomas: “Lunch at one?”"
    )
    assert town.take("Tomas") == ["Mei wrote to you: “Lunch at one?”"]
    assert not world.ports["Tomas"].interrupt.is_set()  # read when he next looks up
    assert town.take("Aisha") == []  # nobody else sees it
    written = [e for e in world.log.entries() if e["kind"] == "message"]
    assert written[-1]["payload"] == {"to": "Tomas", "text": "Lunch at one?"}
    assert written[-1]["audience"] == ["Tomas"]
    assert written[-1]["text"] == "Mei wrote to Tomas: “Lunch at one?”"

    await town.call("Tomas", "go", place="college-flat")
    await town.until("07:20")
    await town.call("Tomas", "sleep", until="12:00", journal="A nap.")
    town.take("Tomas")
    town.rest("Tomas")
    await town.until("08:00")
    assert world.residents["Tomas"].suspended
    await town.call("Mei", "message", to="Tomas", text="Still on?")
    await town.until("12:00")
    assert [p.text for p in town.heard["Tomas"]][-2:] == [
        "Mei wrote to you: “Still on?”",
        "You woke up at home. It is Monday 1 January, 12:00. You are a little hungry. You are "
        "fresh. You are in good health.",
    ]


async def test_what_one_wears_is_seen_on_arrival_on_looking_around_and_in_conversation(make_town):
    town = make_town()
    await awake_at(town, "08:00")
    await town.call("Mei", "go", place="store")
    await town.call("Tomas", "go", place="workshop")
    await town.until("08:10")
    town.world.residents["Mei"].inventory.items["coat"] = 1
    for name in ("Mei", "Tomas"):
        town.take(name)
    await town.call("Mei", "go", place="workshop")
    await town.until("08:20")
    assert town.take("Tomas") == ["Mei arrived at the workshop, in a new coat."]
    assert town.take("Mei") == ["You arrived at the workshop. Also here: Tomas."]
    assert (await town.call("Tomas", "look_around")).text.endswith(
        "Also here: Mei (in a new coat)."
    )
    await town.call("Tomas", "claim_task", task=1)
    await town.call("Tomas", "say", text="New coat?", to=["Mei"])  # talking at his desk
    assert "in a conversation with Mei (in a new coat)." in town.world.ports["Tomas"].situation()
    assert "in a conversation with Tomas." in town.world.ports["Mei"].situation()
    assert (await town.call("Mei", "look_around")).text.endswith(
        "Also here: Tomas (working, in a conversation)."
    )


async def test_moving_house_needs_a_free_room_and_moves_the_rent(make_town, tmp_path):
    town = make_town()
    await awake_at(town)
    world = town.world
    assert (await town.call("Mei", "move_in")).text == "You live here already."
    await town.call("Mei", "go", place="store")
    await town.until("07:10")
    assert (await town.call("Mei", "move_in")).text == (
        "You can move into a home only when you are there."
    )
    await town.call("Mei", "go", place="college-flat")
    await town.until("07:20")
    town.take("Tomas")
    assert (await town.call("Mei", "move_in")).text == (
        "You moved into the flat by the college gates; your room at the shared house on Mill "
        "Street is given up. From the next midnight your rent is $30 a day."
    )
    assert town.take("Tomas") == ["Mei moved into the flat by the college gates."]
    assert world.residents["Mei"].home == "college-flat"
    moved = [e for e in world.log.entries() if e["kind"] == "move_in"]
    assert moved[-1]["payload"] == {"from": "mill-street-house", "to": "college-flat", "rent": 30}
    places = (await town.call("Mei", "help", topic="places")).text
    assert "the shared house on Mill Street $20 (3 rooms, 2 free, little comfort)" in places
    assert "the flat by the college gates $30 (6 rooms, 4 free)" in places
    rules = world.ports["Mei"].rules()  # the standing rules in her prompt move with her
    assert "less the rent for your room, $30 a day." in rules
    assert "You live in the flat by the college gates with Tomas;" in rules
    assert "You live in the flat by the college gates with Mei;" in world.ports["Tomas"].rules()
    assert "It is your home" in (await town.call("Mei", "look_around")).text
    await town.until("21:00")
    assert (await town.call("Mei", "sleep", until="07:00", journal="A new room.")).text == (
        "You went to bed."
    )
    town.take("Mei")
    await town.until("00:00", day=2)
    assert town.take("Mei")[0].startswith(
        "Your statement for Monday 1 January: no time at work; rent for your room at the flat by "
        "the college gates $30;"
    )

    # A home with no free room cannot be moved into.
    data = town_config().model_dump(mode="json")
    data["places"][1]["rooms"] = 1  # the flat: Tomas's
    full = make_town(TownConfig.model_validate(data), root=tmp_path / "full")
    await awake_at(full)
    await full.call("Mei", "go", place="college-flat")
    await full.until("07:10")
    assert (await full.call("Mei", "move_in")).text == (
        "There is no free room at the flat by the college gates."
    )
