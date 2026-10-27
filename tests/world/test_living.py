"""The goods of the catalogue and the homes: buying where a good is sold and with cash in hand,
food eaten on the spot or from a stock drawn on as one gets hungry, a durable kept and billed, a
bicycle that shortens the walk, messages between phone owners wherever they are, what one wears
seen by others, and moving into a home with a free room. What the body makes of food, sleep and
work is in test_body."""

from __future__ import annotations

from tests.world.conftest import at, awake_at, town_config
from world.config import TownConfig


async def test_a_good_is_bought_only_where_it_is_sold_and_only_with_the_cash(make_town):
    town = make_town()
    await awake_at(town)
    assert (await town.call("Mei", "buy", item="groceries")).text == (
        "You can buy groceries at the store, not here."
    )
    for name in ("Mei", "Aisha"):
        await town.call(name, "go", place="store")
    await town.until("07:10")
    assert (await town.call("Aisha", "buy", item="bicycle")).text == (
        "You do not have $50. Your purse holds $30."
    )
    assert (await town.call("Aisha", "buy", item="coat", quantity=2)).text == (
        "One coat is all you can have."
    )
    assert (await town.call("Aisha", "buy", item="coat", quantity=0)).text == (
        "quantity must be a whole number of at least 1."
    )
    assert (await town.call("Aisha", "buy", item="coat")).text == (
        "You bought a coat for $30. You have a coat. Your purse holds $0."
    )
    assert (await town.call("Aisha", "buy", item="coat")).text == "You already have a coat."
    assert (await town.call("Aisha", "buy", item="groceries")).text == (
        "You do not have $12. Your purse holds $0."
    )
    assert (await town.call("Mei", "buy", item="groceries", quantity=2)).text == (
        "You bought 2 × groceries for $24. You have groceries (18 helpings). Your purse holds $96."
    )
    assert (await town.call("Mei", "help", topic="money")).text.endswith(
        "You have groceries (18 helpings)."
    )
    bought = [e for e in town.world.log.entries() if e["kind"] == "purchase"]
    assert [(e["actor"], e["text"], e["payload"]) for e in bought] == [
        (
            "Aisha",
            "Aisha bought a coat for $30.",
            {"item": "coat", "name": "a coat", "kind": "durable", "effect": "appearance",
             "quantity": 1, "amount": 30},
        ),
        (
            "Mei",
            "Mei bought 2 × groceries for $24.",
            {"item": "groceries", "name": "groceries", "kind": "consumable", "effect": "food",
             "quantity": 2, "amount": 24},
        ),
    ]  # fmt: skip
    assert town.world.economy.purses == {"Mei": 96, "Tomas": 180, "Aisha": 0}


async def test_food_on_the_spot_or_from_a_stock_is_the_days_food(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei, tomas = world.residents["Mei"], world.residents["Tomas"]
    await town.call("Mei", "go", place="cafe")
    await town.call("Tomas", "go", place="store")
    await town.until("07:10")
    assert (await town.call("Mei", "buy", item="meal")).text == (
        "You bought a meal at the café for $10. You are well fed. Your purse holds $110."
    )
    assert world.nourishment(mei) == 100 and mei.living.eaten == {"meal": 1}
    assert (await town.call("Tomas", "buy", item="groceries")).text == (
        "You bought groceries for $12. You have groceries (9 helpings). Your purse holds $168."
    )
    assert world.nourishment(tomas) == 0 and tomas.living.things == {"groceries": 9}
    for name in world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    statements = {name: town.take(name)[-1] for name in world.residents}
    assert statements["Mei"] == (
        "Your statement for Monday 1 January: bought a meal at the café for $10; rent for your "
        "room at the shared house on Mill Street $20. You ate today: a meal at the café. You are "
        "a little hungry. You are fresh. You are in good health. Your purse holds $90."
    )
    assert statements["Tomas"] == (  # helpings of the stock, eaten as he could eat
        "Your statement for Monday 1 January: bought groceries for $12; rent for your room at "
        "the flat by the college gates $30. You ate today: 2 helpings of groceries. You are "
        "well fed. You are fresh. You are in good health. Your purse holds $138."
    )
    assert statements["Aisha"] == (
        "Your statement for Monday 1 January: rent for your room at the shared house on Mill "
        "Street $20. You had nothing to eat today. You are hungry. You are fresh. You are in "
        "good health. Your purse holds $10."
    )
    # The day's record starts afresh; the stock went down by the two helpings Tomas ate when
    # he could eat, at 12:00 and 21:00. Aisha, full when the town began, is hungry but not yet
    # starving at the first midnight.
    assert world.nourishment(mei) == 0 and tomas.living.things == {"groceries": 7}
    settled = [e for e in world.log.entries() if e["kind"] == "settlement"]
    assert [e["payload"]["nourishment"] for e in settled] == [100, 68, 0]
    assert [e["payload"]["purse"] for e in settled] == [90, 138, 10]
    assert settled[2]["payload"]["night"] == {"poor_home": -2, "recovery": 5}

    # The stock is drawn on as its owner gets hungry, at most three helpings a day, and the
    # statement tells what is left when it is nearly gone and when it is gone.
    town.rest()
    await town.until("00:01", day=6)
    statements = [p.text for p in town.heard["Tomas"] if p.kind == "settlement"]
    notes = [
        note
        for text in statements
        for note in ("helpings of groceries left", "used up your groceries")
        if note in text
    ]
    assert notes == ["helpings of groceries left", "used up your groceries"]
    assert tomas.living.things == {} and "You had nothing to eat today." in statements[-1]


async def test_a_durable_is_kept_and_its_charge_is_billed_each_midnight_while_owned(make_town):
    town = make_town()
    await awake_at(town)
    await town.call("Mei", "go", place="store")
    await town.until("07:10")
    assert (await town.call("Mei", "buy", item="phone")).text == (
        "You bought a phone for $40. You have a phone. Your purse holds $80."
    )
    town.take("Mei")
    await town.until("00:00", day=2)
    assert town.take("Mei")[-1] == (
        "Your statement for Monday 1 January: bought a phone for $40; rent for your room at the "
        "shared house on Mill Street $20; the daily charge on a phone $2. You had nothing to eat "
        "today. You are hungry. You are fresh. You are in good health. Your purse holds $58."
    )
    settled = [e for e in town.world.log.entries() if e["kind"] == "settlement"]
    assert {k: settled[0]["payload"][k] for k in ("rent", "fees", "nourishment", "purse")} == {
        "rent": 20, "fees": 2, "nourishment": 0, "purse": 58,
    }  # fmt: skip
    assert town.world.residents["Mei"].living.things == {"phone": 1}


async def test_a_bicycle_halves_the_walk(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei = world.residents["Mei"]
    await town.call("Mei", "go", place="store")
    assert mei.base.arrival == at("07:10")  # ten minutes on foot
    await town.until("07:10")
    await town.call("Mei", "buy", item="bicycle")
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
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="store")
    await town.until("07:10")
    await town.call("Mei", "buy", item="phone")
    assert (await town.call("Mei", "message", to="Tomas", text="Hello?")).text == (
        "Tomas has no phone."
    )
    await town.call("Tomas", "buy", item="phone")
    assert (await town.call("Mei", "message", to="Zoe", text="Hello?")).text == (
        "There is nobody called Zoe in the town."
    )
    assert (await town.call("Mei", "message", to="Mei", text="Hello?")).text == (
        "You cannot write to yourself."
    )
    assert (await town.call("Mei", "message", to="Tomas", text=" ")).text == "You wrote nothing."
    await town.call("Tomas", "go", place="workshop")
    await town.until("07:20")
    for name in world.residents:
        town.take(name)
    assert (await town.call("Mei", "message", to="Tomas", text="Lunch at one?")).text == (
        "You wrote to Tomas: “Lunch at one?”"
    )
    assert town.take("Tomas") == ["Mei wrote to you: “Lunch at one?”"]
    assert not world.ports["Tomas"].interrupt.is_set()  # read when he next looks up
    assert town.take("Aisha") == []  # nobody else sees it
    assert world.ratings.met["Tomas"] == {"Mei"}
    written = [e for e in world.log.entries() if e["kind"] == "message"]
    assert written[-1]["payload"] == {"to": "Tomas", "text": "Lunch at one?"}
    assert written[-1]["audience"] == ["Tomas"]
    assert written[-1]["text"] == "Mei wrote to Tomas: “Lunch at one?”"

    await town.call("Tomas", "go", place="college-flat")
    await town.until("07:30")
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

    # In the isolated mode nobody else is in the town to write to: nothing to write with is sold.
    alone = make_town(town_config("isolated"), root=tmp_path / "alone")
    assert "message" not in [spec.name for spec in alone.world.tool_specs]
    assert [good.id for good in alone.world.for_sale] == [
        "groceries", "meal", "bicycle", "coat", "examination", "treatment",
    ]  # fmt: skip


async def test_what_one_wears_is_seen_on_arrival_on_looking_around_and_in_conversation(make_town):
    town = make_town()
    await awake_at(town, "08:00")
    await town.call("Mei", "go", place="store")
    await town.call("Tomas", "go", place="workshop")
    await town.until("08:10")
    await town.call("Mei", "buy", item="coat")
    for name in ("Mei", "Tomas"):
        town.take(name)
    await town.call("Mei", "go", place="workshop")
    await town.until("08:20")
    assert town.take("Tomas") == ["Mei arrived at the workshop, in a new coat."]
    assert town.take("Mei") == ["You arrived at the workshop. Also here: Tomas."]
    assert (await town.call("Tomas", "look_around")).text.endswith(
        "Also here: Mei (in a new coat)."
    )
    await town.call("Tomas", "say", text="New coat?", to=["Mei"])
    assert "in a conversation with Mei (in a new coat)." in town.world.ports["Tomas"].situation()
    assert "in a conversation with Tomas." in town.world.ports["Mei"].situation()
    await town.call("Tomas", "claim_task", task=1)  # sitting down to work while they talk
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
    assert "Your home is the flat by the college gates." in places
    rules = world.ports["Mei"].rules()  # the standing rules in her prompt move with her
    assert "Your home is the flat by the college gates." in rules
    assert "Your room at the flat by the college gates costs $30 a day" in rules
    assert "Mill Street costs" not in rules
    assert "Mei (the flat by the college gates)" in world.ports["Tomas"].rules()
    assert "It is your home" in (await town.call("Mei", "look_around")).text
    await town.until("21:00")
    assert (await town.call("Mei", "sleep", until="07:00", journal="A new room.")).text == (
        "You went to bed."
    )
    town.take("Mei")
    await town.until("00:00", day=2)
    assert town.take("Mei")[0].startswith(
        "Your statement for Monday 1 January: rent for your room at the flat by the college "
        "gates $30."
    )

    # A home with no free room cannot be moved into; in the isolated mode, where each resident
    # lives in a town of its own, another resident's room is no obstacle.
    data = town_config().model_dump(mode="json")
    data["places"][1]["rooms"] = 1  # the flat: Tomas's
    full = make_town(TownConfig.model_validate(data), root=tmp_path / "full")
    await awake_at(full)
    await full.call("Mei", "go", place="college-flat")
    await full.until("07:10")
    assert (await full.call("Mei", "move_in")).text == (
        "There is no free room at the flat by the college gates."
    )
    data["social"]["mode"] = "isolated"
    alone = make_town(TownConfig.model_validate(data), root=tmp_path / "alone")
    await awake_at(alone)
    await alone.call("Mei", "go", place="college-flat")
    await alone.until("07:10")
    assert (await alone.call("Mei", "move_in")).text.startswith(
        "You moved into the flat by the college gates;"
    )
