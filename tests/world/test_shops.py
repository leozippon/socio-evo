"""The Store and the Restaurant, their keepers' businesses, under the open actions: the shelves
read and taken from by whoever is there, the keeper at work or not, a purchase being a take, the
price posted for it told, and a gift of that price to the keeper, taxed as she is at work; a
hungry taker eating of what it took; an order paid from the shopkeeper's purse to the supplier
and delivered onto the shelves the next morning, prices set; the chef taking what he cooks with
like any customer, cooking from the larder and from what he carries, short of it or not, the
portions standing on the counter for diners to take, eat and pay him for, what is left of them
gone at midnight; the checkpoint that carries the Store, the kitchen and their holders; and the
money that only clients bring into the town and only the supplier takes out of it. Taking and
giving themselves, who sees them and what an absent keeper is told are in test_things."""

from __future__ import annotations

import json

from tests.support.towns import RESIDENTS, TRADES, at, awake_at, make_agent_dirs, town_config
from tests.world.acts import give, money, moves, take
from world.clock import ManualClock
from world.log import counted_move
from world.testing import FakeBackend
from world.world import World

SHOPS = town_config(residents=RESIDENTS + TRADES, tax=0.1)


def offered(town, name: str) -> list[str]:
    return [spec.name for spec in town.world.ports[name].tool_specs()]


async def test_a_purchase_at_the_store_is_a_take_and_a_gift_of_the_price_to_its_keeper(make_town):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    mei, olga = world.residents["Mei"], world.residents["Olga"]
    assert await take(town, "Mei", "bread", "shelves") == "You are not at the store."
    for name in ("Mei", "Aisha", "Olga"):
        await town.call(name, "go", place="store")
    await town.until("07:10")
    shelves = (
        "bread $4 (10 left), eggs $2 (10 left), vegetables $3 (10 left), bicycle $50 (1 left), "
        "phone $40 (2 left) and coat $30 (1 left)."
    )
    # The shelves and their prices are read by whoever is there; the work is the keeper's alone.
    for name in ("Mei", "Olga"):
        assert f"On the shelves: {shelves}" in world.ports[name].situation()
    assert f"On the shelves: {shelves}" in (await town.call("Mei", "look_around")).text
    assert "start_work" in offered(town, "Olga") and "order" in offered(town, "Olga")
    assert "start_work" not in offered(town, "Mei") and "order" not in offered(town, "Mei")
    assert {"take", "give", "use"} <= set(offered(town, "Mei"))
    assert (await town.call("Mei", "order", item="bread", quantity=1)).text == (
        "That is not your work: you are a programmer."
    )
    assert (await town.call("Mei", "start_work")).text == "Your work is at the workshop."
    assert (await town.call("Olga", "start_work")).text == (
        f"You sat down to work. It is 07:10. On the shelves: {shelves}"
    )
    assert (await town.call("Olga", "start_work")).text == "You are at work already."
    assert (
        world.ports["Mei"]
        .situation()
        .endswith(f"Also here: Aisha (liked by 0) and Olga (working, liked by 0). On the shelves: "
                  f"{shelves} Your purse holds $120. None of the others likes you.")
    )  # fmt: skip
    # A purchase is two acts of the customer's: the take, which tells the price, and the gift.
    town.take("Olga")
    assert await take(town, "Mei", "bread", "shelves", 3) == (
        "You took 3 helpings of bread from the shelves. The price posted is $4 each, $12 in "
        "all. You carry 3 helpings of bread."
    )
    assert (
        await give(town, "Mei", "money", "Olga", 12) == "You gave Olga $12. Your purse holds $108."
    )
    assert town.take("Olga") == [
        "Mei took 3 helpings of bread from your shelves.",
        "Mei gave you $12, of which $1 in tax.",
    ]
    assert (olga.inventory.money, world.treasury.ledger) == (100 + 12 - 1, {"tax": 1})
    # What the keeper takes of her own is a take like any other; nothing is owed to anyone.
    assert await take(town, "Olga", "bread", "shelves") == (
        "You took 1 helping of bread from your shelves. The price posted for it is $4. You "
        "carry 1 helping of bread."
    )
    # Nothing ties a take to a payment: the coat goes with nothing given, before the keeper's
    # eyes, and the purse of one who has nothing takes like any other.
    world.residents["Aisha"].inventory.money = 0
    assert await take(town, "Aisha", "coat", "shelves") == (
        "You took a coat from the shelves. The price posted for it is $30. You carry a coat."
    )
    assert town.take("Olga") == ["Aisha took a coat from your shelves."]
    assert await take(town, "Mei", "coat", "shelves") == "You find no coat on the shelves."
    assert world.holders["shelves"].items == {
        "bread": 6, "eggs": 10, "vegetables": 10, "bicycle": 1, "phone": 2,
    }  # fmt: skip
    assert "phone $40 (2 left); none left: coat." in world.ports["Mei"].situation()
    done = moves(world)
    assert [(e["actor"], e["text"]) for e in done] == [
        ("Mei", "Mei took 3 helpings of bread from the shelves."),
        ("Mei", "Mei gave Olga $12."),
        ("Olga", "Olga took 1 helping of bread from the shelves."),
        ("Aisha", "Aisha took a coat from the shelves."),
    ]
    assert [(e["payload"]["price"], e["payload"]["tax"]) for e in done] == [
        (4, 0), (None, 1), (4, 0), (30, 0),
    ]  # fmt: skip
    # The run's log counts a take off the shelves and a gift, paid for or not: no entry says.
    assert [counted_move(e["payload"]) for e in done] == ["sale", "gift", "sale", "sale"]
    # The statement tells the keeper who gave her what at work; the customer what it gave.
    for name in world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    assert town.take("Olga")[-1].startswith(
        "Your statement for Monday 1 January: received $12 from Mei at work, $1 of it in tax; "
        "rent for your room"
    )
    assert town.take("Mei")[-1].startswith(
        "Your statement for Monday 1 January: gave $12 to Olga; rent for your room"
    )
    assert mei.living.eaten == {}  # the statement closed the day's food


async def test_a_hungry_taker_eats_of_what_it_took_at_once_and_is_told(make_town):
    town = make_town(SHOPS)
    await awake_at(town)
    world, mei = town.world, town.world.residents["Mei"]
    await town.call("Mei", "go", place="store")
    await town.until("07:10")
    mei.living.satiety = 0
    assert await take(town, "Mei", "bread", "shelves", 3) == (
        "You took 3 helpings of bread from the shelves. The price posted is $4 each, $12 in "
        "all. You ate 2 helpings of bread at once. You carry 1 helping of bread."
    )
    eaten = [e["payload"] for e in moves(world)][-2:]
    assert [(m["reason"], m["what"], m["amount"]) for m in eaten] == [("eat", "bread", 1)] * 2
    mei.living.satiety = 10
    assert await take(town, "Mei", "bread", "shelves") == (
        "You took 1 helping of bread from the shelves. The price posted for it is $4. You ate "
        "1 helping of bread at once. You carry nothing but your money."
    )  # the helping it held eaten first, as the body would have eaten it by now
    assert await take(town, "Mei", "bread", "shelves") == (
        "You took 1 helping of bread from the shelves. The price posted for it is $4. You "
        "carry 1 helping of bread."
    )  # well fed, it keeps it


async def test_an_order_is_paid_at_once_and_arrives_the_next_morning_and_prices_are_set(make_town):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    await town.call("Olga", "go", place="store")
    await town.until("07:10")
    ordered = await town.call("Olga", "order", item="bread", quantity=5)
    assert ordered.text == (
        "You sat down to work. It is 07:10. You ordered 5 helpings of bread from the supplier for "
        "$10; it arrives tomorrow at 08:00. Your purse holds $90."
    )
    olga = world.residents["Olga"]
    assert olga.inventory.moves == [["paid", 10, "5 helpings of bread from the supplier"]]
    assert world.treasury.ledger == {} and world.treasury.balance == 1000
    assert world.store.pending == [["bread", 5, at("08:00", day=2)]]
    assert "On order from the supplier: 5 helpings of bread." in world.ports["Olga"].situation()
    olga.inventory.money = 3
    assert (await town.call("Olga", "order", item="phone", quantity=1)).text == (
        "You do not have $25. Your purse holds $3."
    )
    assert world.store.pending == [["bread", 5, at("08:00", day=2)]]
    olga.inventory.money = 90
    assert (await town.call("Olga", "set_price", item="bread", price=5)).text == (
        "The price of bread is now $5; it was $4."
    )
    assert (await town.call("Olga", "set_price", item="soup", price=5)).text == (
        "Vegetable soup is not sold at the store."
    )
    assert "bread $5 (10 left)" in world.ports["Olga"].situation()
    priced = [e for e in world.log.entries() if e["kind"] == "price"]
    assert priced[0]["payload"] == {
        "item": "bread", "name": "bread", "place": "store", "price": 5, "before": 4,
    }  # fmt: skip
    # The price told on a take, and logged with it, is the one posted at that moment.
    await town.call("Mei", "go", place="store")
    await town.until("07:20")
    assert "On order" not in world.ports["Mei"].situation()  # the keeper's to read
    assert "The price posted for it is $5." in await take(town, "Mei", "bread", "shelves")
    assert moves(world)[-1]["payload"]["price"] == 5
    town.rest()
    await town.until("07:59", day=2)
    assert world.holders["shelves"].units("bread") == 9
    await town.until("08:00", day=2)
    assert world.holders["shelves"].units("bread") == 14 and world.store.pending == []
    delivered = [e for e in world.log.entries() if e["kind"] == "delivery"]
    assert [(e["text"], e["audience"], e["payload"]) for e in delivered] == [
        (
            "It is 08:00: the supplier delivered 5 helpings of bread to the store.",
            ["Olga"],
            {"items": {"bread": 5}},
        )
    ]
    assert [p.text for p in town.heard["Olga"] if p.kind == "delivery"] == [delivered[0]["text"]]


async def test_the_chef_takes_what_he_cooks_with_cooks_and_diners_take_from_the_counter(make_town):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    jonas, mei = world.residents["Jonas"], world.residents["Mei"]
    before = money(world)
    for name in ("Olga", "Jonas"):
        await town.call(name, "go", place="store")
    await town.until("07:10")
    await town.call("Olga", "start_work")
    # The chef takes what the kitchen cooks with like any customer, and carries it.
    assert await take(town, "Jonas", "eggs", "shelves", 4) == (
        "You took 4 units of eggs from the shelves. The price posted is $2 each, $8 in all. "
        "You carry 4 units of eggs."
    )
    await take(town, "Jonas", "vegetables", "shelves", 5)
    assert await give(town, "Jonas", "money", "Olga", 23) == (
        "You gave Olga $23. Your purse holds $77."
    )
    assert world.residents["Olga"].inventory.money == 100 + 23 - 2
    assert "start_work" not in offered(town, "Jonas") and "cook" not in offered(town, "Jonas")
    assert (
        await town.call("Jonas", "start_work")
    ).text == "Your work is at the café on the square."
    assert (await town.call("Jonas", "cook", dish="omelette", portions=1)).text == (
        "You can do that only at the café on the square."
    )
    await town.call("Jonas", "go", place="cafe")
    await town.until("07:20")
    assert jonas.worked == 0  # an hour at work counts at one's own workplace only
    # He cooks from the larder and, where it is short, from what he carries; short of both,
    # nothing is cooked.
    assert await give(town, "Jonas", "eggs", "larder", 3) == (
        "You left 3 units of eggs in your larder. You carry 1 unit of eggs and 5 units of "
        "vegetables."
    )
    assert (await town.call("Jonas", "cook", dish="omelette", portions=3)).text == (
        "You sat down to work. It is 07:20. For 3 portions of omelette you are short: it takes "
        "6 units of eggs, of which the larder holds 3 and you carry 1."
    )
    assert (await town.call("Jonas", "cook", dish="omelette", portions=2)).text == (
        "You cooked 2 portions of omelette; 2 ready on the counter. The larder is empty. You "
        "carry 3 units of vegetables."
    )
    cooked = [e["payload"] for e in world.log.entries() if e["kind"] == "cook"]
    assert cooked == [
        {
            "dish": "omelette", "name": "an omelette", "portions": 2,
            "used": {"eggs": 4, "vegetables": 2}, "carried": {"eggs": 1, "vegetables": 2},
        }
    ]  # fmt: skip
    assert world.holders["larder"].items == {} and jonas.inventory.items == {"vegetables": 3}
    assert (await town.call("Jonas", "set_price", item="omelette", price=12)).text == (
        "The price of omelette is now $12; it was $10."
    )
    assert (await town.call("Jonas", "set_price", item="bread", price=1)).text == (
        "Bread is not on the menu of the café on the square."
    )
    assert (await town.call("Mei", "cook", dish="soup", portions=1)).text == (
        "That is not your work: you are a programmer."
    )
    await town.call("Mei", "go", place="cafe")
    await town.until("07:30")
    # The counter and the larder are read by whoever is there.
    assert (
        "On the counter: omelette $12 (2 ready) and vegetable soup $8 (none ready). The larder "
        "is empty." in world.ports["Mei"].situation()
    )
    assert (
        await take(town, "Mei", "soup", "counter") == "You find no vegetable soup on the counter."
    )
    # A meal: the diner takes a portion, eats it there, and gives the chef its price.
    town.take("Jonas")
    mei.living.satiety = 40
    assert await take(town, "Mei", "omelette", "counter") == (
        "You took an omelette from the counter. The price posted for it is $12. You ate an "
        "omelette at once. You carry nothing but your money."
    )
    assert mei.living.eaten == {"omelette": 1} and world.nourishment(mei) == 100
    assert (
        await give(town, "Mei", "money", "Jonas", 12)
        == "You gave Jonas $12. Your purse holds $108."
    )
    assert town.take("Jonas") == [
        "Mei took an omelette from your counter.",
        "Mei gave you $12, of which $1 in tax.",
    ]
    assert jonas.inventory.money == 77 + 12 - 1
    served = [e for e in moves(world) if e["actor"] == "Mei"]
    assert [e["text"] for e in served] == [
        "Mei took an omelette from the counter.",
        "Mei ate an omelette.",  # out of her hands into nothing, there and then
        "Mei gave Jonas $12.",
    ]
    assert [e["payload"] for e in served[:2]] == [
        {"what": "omelette", "amount": 1, "source": "counter", "target": "Mei", "reason": "take",
         "price": 12, "tax": 0},
        {"what": "omelette", "amount": 1, "source": "Mei", "target": None, "reason": "eat",
         "price": None, "tax": 0},
    ]  # fmt: skip
    assert counted_move(served[0]["payload"]) == "dish"
    # The chef's own meal comes off the counter the same way; nobody is charged for anything.
    assert await take(town, "Jonas", "omelette", "counter") == (
        "You took an omelette from your counter. The price posted for it is $12. You ate an "
        "omelette at once. You carry 3 units of vegetables."
    )
    await town.call("Jonas", "cook", dish="soup", portions=1)
    await town.until("08:20")
    await town.call("Jonas", "leave_work")
    assert jonas.worked == 3600
    # At work or not, the counter stands there; what is given the chef off work is not taxed.
    assert "vegetable soup $8 (1 ready)" in world.ports["Mei"].situation()
    await give(town, "Mei", "money", "Jonas", 10)
    assert jonas.inventory.money == 88 + 10 and world.treasury.ledger == {"tax": 3}
    # At midnight the portion left is gone, and the chef's statement says so. The money in the
    # town changed by what the supplier was paid, nothing, and the clients, nothing: the rest
    # moved between the purses and the treasury.
    for name in world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    assert world.holders["counter"].items == {} and jonas.inventory.items == {"vegetables": 1}
    statement = town.take("Jonas")[-1]
    assert (
        "The dishes left on the counter are gone: vegetable soup; what the larder holds keeps."
        in statement
    )
    assert statement.startswith(
        "Your statement for Monday 1 January: received $12 from Mei at work, $1 of it in tax; "
        "gave $23 to Olga; received $10 from Mei; rent for your room"
    )
    statement = town.take("Mei")[-1]
    assert statement.startswith(
        "Your statement for Monday 1 January: gave $12 to Jonas; gave $10 to Jonas; rent for "
        "your room"
    )
    assert "You ate today: an omelette." in statement
    assert money(world) == before


async def test_the_checkpoint_keeps_the_store_and_the_kitchen_and_money_comes_only_from_clients(
    make_town, tmp_path
):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    before = money(world)
    for name in ("Olga", "Jonas", "Tomas"):
        await town.call(name, "go", place="store")
    await town.until("07:10")
    await town.call("Olga", "order", item="eggs", quantity=6)
    await town.call("Olga", "set_price", item="vegetables", price=4)
    await take(town, "Jonas", "vegetables", "shelves", 6)
    await give(town, "Jonas", "money", "Olga", 24)
    await take(town, "Tomas", "phone", "shelves")
    await give(town, "Tomas", "money", "Olga", 40)
    await town.call("Jonas", "go", place="cafe")
    await town.call("Mei", "go", place="workshop")
    await town.until("09:00")
    await give(town, "Jonas", "vegetables", "larder", 6)
    await town.call("Jonas", "cook", dish="soup", portions=2)
    await town.call("Jonas", "set_price", item="soup", price=9)
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    await town.call("Mei", "submit")  # the client pays Mei $50
    await town.call("Mei", "go", place="cafe")
    await town.until("09:10")
    await take(town, "Mei", "soup", "counter")
    await give(town, "Mei", "money", "Jonas", 9)
    town.rest()
    await town.until("03:00", day=2)
    ((day, state),) = town.checkpoints
    assert state["store"] == {
        "prices": {"bread": 4, "eggs": 2, "vegetables": 4, "bicycle": 50, "phone": 40, "coat": 30},
        "pending": [["eggs", 6, at("08:00", day=2)]],
    }
    assert state["kitchen"] == {"menu": {"omelette": 10, "soup": 9}}
    holders = state["holders"]
    assert holders["shelves"] == {
        "items": {"bread": 10, "eggs": 10, "vegetables": 4, "bicycle": 1, "phone": 1, "coat": 1},
        "money": 0,
    }
    assert holders["larder"] == {"items": {"vegetables": 2}, "money": 0}
    assert holders["counter"] == {"items": {}, "money": 0}  # the soup left perished
    # Only the client's $50 came in and only the supplier's $6 went out; every other movement,
    # what was given for the goods and the dish, the tax and the rent, stayed in the town.
    assert state["treasury"] == {
        "balance": world.treasury.balance, "ledger": {}, "yesterday": world.treasury.yesterday,
        "owed": {}, "arrears": {},
    }  # fmt: skip
    assert world.treasury.yesterday["tax"] == 2 + 4 + 5  # of $24 and $40 at the Store, of $50
    assert money(world) == before + 50 - 6
    make_agent_dirs(tmp_path / "r", world.config)
    restored = World(world.config, tmp_path / "r", FakeBackend(), clock=ManualClock())
    restored.restore(json.loads(json.dumps(state)))
    assert restored.snapshot() == state
