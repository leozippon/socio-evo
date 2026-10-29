"""Items and their holders: every unit held by exactly one holder, a resident, what is left at a
place, the Store's shelves, the kitchen's larder and portions, and moved only by `World.move`,
which needs the mover present and the source to hold what it gives; get, put, pass and eat; the
money that goes with a move conserved; and what a conversation lets one do with things."""

from __future__ import annotations

from collections import Counter

from tests.support.towns import RESIDENTS, TRADES, awake_at, town_config
from world.economy import SUPPLIER

SHOPS = town_config(residents=RESIDENTS + TRADES)


def census(world) -> Counter[str]:
    """The units of each item in the town, in every holder but the supplier, which is outside."""
    held: Counter[str] = Counter()
    for key in [*world.residents, *world.holders]:
        if key != SUPPLIER:
            held.update(world.holder(key).items)
    return held


def money(world) -> int:
    """The town's money: the treasury and every purse."""
    return world.treasury.balance + sum(r.inventory.money for r in world.residents.values())


async def test_units_change_hands_but_are_never_made_or_lost_and_money_is_conserved(make_town):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    start, cash = census(world), money(world)
    assert start == Counter(world.config.store.stock)  # all on the shelves at the start
    for name in ("Mei", "Aisha", "Olga", "Jonas"):
        await town.call(name, "go", place="store")
    await town.until("07:10")
    await town.call("Olga", "start_work")
    await town.call("Mei", "buy", item="eggs", units=3)
    await town.call("Mei", "buy", item="coat")
    await town.call("Jonas", "buy", item="vegetables", units=2, for_the_kitchen=True)
    await town.call("Mei", "put", item="eggs", units=2)
    await town.call("Aisha", "get", item="eggs")
    await town.call("Aisha", "pass", item="eggs", to="Jonas")
    await town.call("Mei", "pass", item="coat", to="Aisha")
    await town.call("Mei", "pass", item="money", units=5, to="Aisha")
    assert census(world) == start  # every unit is still in exactly one holder
    assert money(world) == cash  # the purchases and the money passed stayed in the town
    places = {key: dict(world.holder(key).items) for key in ("store", "shelves", "larder")}
    assert places == {
        "store": {"eggs": 1},  # left there for anyone
        "shelves": {"bread": 10, "eggs": 7, "vegetables": 8, "bicycle": 1, "phone": 2},
        "larder": {"vegetables": 2},
    }
    held = {name: dict(world.residents[name].inventory.items) for name in ("Mei", "Aisha", "Jonas")}
    assert held == {"Mei": {"eggs": 1}, "Aisha": {"coat": 1}, "Jonas": {"eggs": 1}}
    moves = [
        (e["actor"], e["payload"]["reason"], e["payload"]["source"], e["payload"]["target"])
        for e in world.log.entries()
        if e["kind"] == "move"
    ]
    assert moves == [
        ("Mei", "buy", "shelves", "Mei"),
        ("Mei", "buy", "shelves", "Mei"),
        ("Jonas", "buy", "shelves", "larder"),
        ("Mei", "put", "Mei", "store"),
        ("Aisha", "get", "store", "Aisha"),
        ("Aisha", "pass", "Aisha", "Jonas"),
        ("Mei", "pass", "Mei", "Aisha"),
        ("Mei", "pass", "Mei", "Aisha"),
    ]
    # Into nothing and out of it: cooking, eating and perishing, and nothing else.
    await town.call("Jonas", "go", place="cafe")
    await town.until("07:20")
    await town.call("Jonas", "cook", dish="soup", portions=1)
    assert census(world) == start - Counter({"vegetables": 2}) + Counter({"soup": 1})
    await town.call("Jonas", "eat", item="eggs")  # an ingredient is not eaten as it is
    assert world.residents["Jonas"].inventory.items == {"eggs": 1}


async def test_get_takes_only_what_is_left_and_put_leaves_it_for_anyone(make_town):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    mei, aisha = world.residents["Mei"], world.residents["Aisha"]
    mei.inventory.items.update({"bread": 2, "phone": 1})
    town.take("Aisha")
    assert (await town.call("Mei", "put", item="phone")).text == (
        "You left a phone here, for anyone to take. You have 2 helpings of bread."
    )
    assert town.take("Aisha") == [
        "Mei left a phone at the shared house on Mill Street, for anyone to take."
    ]
    assert "Left here for anyone to take: a phone." in world.ports["Aisha"].situation()
    assert (await town.call("Aisha", "look_around")).text.endswith(
        "Left here for anyone to take: a phone."
    )
    assert (await town.call("Mei", "put", item="bread", units=3)).text == (
        "You have only 2 helpings of bread."
    )
    assert (await town.call("Aisha", "get", item="phone", units=2)).text == (
        "You find only a phone here."
    )
    assert (await town.call("Aisha", "get", item="phone")).text == (
        "You took a phone. You have a phone."
    )
    assert world.holders["mill-street-house"].items == {} and aisha.inventory.items == {"phone": 1}
    # Food taken by one who could eat is eaten at once, as far as it could eat, and told.
    await town.call("Mei", "put", item="bread", units=2)
    town.take("Mei")
    aisha.living.satiety = 40
    assert (await town.call("Aisha", "get", item="bread", units=2)).text == (
        "You took 2 helpings of bread and ate a helping at once, being hungry. You have 1 helping "
        "of bread and a phone."
    )
    assert town.take("Mei") == [
        "Aisha took 2 helpings of bread left at the shared house on Mill Street."
    ]
    # The Store's shelves are the business's: they are bought from, not taken from.
    await town.call("Mei", "go", place="store")
    await town.until("07:10")
    assert (await town.call("Mei", "get", item="bread")).text == "You find no bread here."
    assert world.holders["shelves"].units("bread") == 10


async def test_a_move_needs_the_mover_where_the_holders_are_and_the_units_held(make_town):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    mei = world.residents["Mei"]
    mei.inventory.items["coat"] = 1
    # Presence, checked in one place: a place's holder at that place, a resident awake there.
    assert world.move("bread", 1, "shelves", "Mei", by=mei) == "You are not at the store."
    assert world.move("coat", 1, "Mei", "Tomas", by=mei) == "Tomas is not here."
    assert world.move("coat", 1, "Mei", "park", by=mei) == "You are not at the park."
    assert world.move("eggs", 1, "larder", None, by=mei) == "You are not at the café on the square."
    assert (await town.call("Mei", "pass", item="coat", to="Tomas")).text == "Tomas is not here."
    await town.call("Aisha", "sleep", until="12:00")
    town.rest("Aisha")
    await town.until("07:01")
    assert (await town.call("Mei", "pass", item="coat", to="Aisha")).text == "Aisha is asleep."
    # Stock: the source gives only what it holds, and a resident holds one of a durable.
    assert world.move("eggs", 11, "shelves", "Mei") == "The store has only 10 units of eggs left."
    assert world.move("eggs", 1, "larder", "Mei") == "The kitchen holds no eggs."
    assert world.move("soup", 1, "portions", "Mei") == "The kitchen has no vegetable soup ready."
    assert world.move("coat", 1, "shelves", "Mei", by=None) == "Mei already has a coat."
    assert census(world) == Counter(world.config.store.stock) + Counter({"coat": 1})  # refused
    # The supplier holds what it sells without end; nothing goes back to it.
    assert world.move("bread", 500, SUPPLIER, "shelves") is None
    assert world.holders["shelves"].units("bread") == 510


async def test_eating_is_a_move_into_nothing_and_what_perishes_is_gone_at_midnight(make_town):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    mei = world.residents["Mei"]
    mei.inventory.items.update({"bread": 1, "eggs": 2})
    mei.living.satiety = 90  # well fed: the body would not eat it by itself yet
    assert (await town.call("Mei", "eat", item="bread")).text == (
        "You ate 1 helping of bread. You are well fed. You have 2 units of eggs."
    )
    assert (await town.call("Mei", "eat", item="bread")).text == "You have no bread."
    assert (await town.call("Mei", "eat", item="eggs")).text.startswith("item must be one of:")
    assert mei.living.eaten == {"bread": 1} and mei.inventory.items == {"eggs": 2}
    world.holders["park"].add("soup", 2)  # a dish someone left, and portions not sold
    world.holders["portions"].add("omelette", 1)
    town.rest()
    await town.until("00:00", day=2)
    assert world.holders["park"].items == {} and world.holders["portions"].items == {}
    assert mei.inventory.items == {"eggs": 2}  # what keeps, keeps


async def test_in_a_conversation_one_shops_eats_and_hands_things_over_without_leaving_it(
    make_town,
):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    mei, aisha = world.residents["Mei"], world.residents["Aisha"]
    mei.inventory.items["bread"] = 3
    await town.call("Aisha", "say", text="I have not eaten.", to=["Mei"])
    assert mei.conversation is not None
    offered = {spec.name for spec in world.ports["Mei"].tool_specs()}
    assert {"get", "pass", "put", "eat", "buy", "inventory", "look_around", "how_am_i"} <= offered
    for tool, args in (
        ("pass", {"item": "bread", "to": "Aisha"}),
        ("put", {"item": "bread"}),
        ("eat", {"item": "bread"}),
        ("inventory", {}),
    ):
        result = await town.call("Mei", tool, **args)
        assert "conversation" not in result.text, result.text
        assert mei.conversation is not None and aisha.conversation is mei.conversation
    assert (await town.call("Aisha", "get", item="bread")).text.startswith("You took")
    assert aisha.conversation is not None
