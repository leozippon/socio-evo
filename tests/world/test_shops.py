"""The Store and the Restaurant: the counter open only while the shopkeeper is at work there, and
its shelves seen by her always, a sale paid in cash and short of stock, an order paid to the
supplier and delivered onto the shelves the next morning, prices set, the chef buying for the
kitchen's larder and for itself, cooking from the larder and short of it, a dish served and
eaten, or handed over by the chef and paid by nobody, what is unsold gone at midnight, the
checkpoint that carries the Store, the kitchen and their holders, and the money that only
clients bring into the town and only the supplier takes out of it."""

from __future__ import annotations

import json

from tests.support.towns import RESIDENTS, TRADES, at, awake_at, make_agent_dirs, town_config
from world.clock import ManualClock
from world.testing import FakeBackend
from world.world import World

SHOPS = town_config(residents=RESIDENTS + TRADES)


def total(world) -> int:
    """The town's money: the fund and every purse."""
    return world.fund.balance + sum(r.inventory.money for r in world.residents.values())


def offered(town, name: str) -> list[str]:
    return [spec.name for spec in town.world.ports[name].tool_specs()]


async def test_the_store_sells_while_its_shopkeeper_is_at_the_counter_and_from_its_stock(
    make_town,
):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    olga = world.residents["Olga"]
    assert (await town.call("Mei", "buy", item="bread")).text == (
        "You can buy bread at the store, not here."
    )
    for name in ("Mei", "Aisha", "Olga"):
        await town.call(name, "go", place="store")
    await town.until("07:10")
    closed = "The store is closed: nobody is at the counter."
    assert (await town.call("Mei", "buy", item="bread")).text == closed
    assert closed in world.ports["Mei"].situation()
    assert "start_work" in offered(town, "Olga") and "order" in offered(town, "Olga")
    assert "start_work" not in offered(town, "Mei") and "order" not in offered(town, "Mei")
    assert (await town.call("Mei", "order", item="bread", quantity=1)).text == (
        "That is not your work: you are a programmer."
    )
    assert (await town.call("Mei", "start_work")).text == "Your work is at the workshop."
    shelves = (
        "bread $4 (10 left), eggs $2 (10 left), vegetables $3 (10 left), bicycle $50 (1 left), "
        "phone $40 (2 left) and coat $30 (1 left)."
    )
    assert f"{closed} On the shelves: {shelves}" in world.ports["Olga"].situation()  # hers
    assert f"On the shelves: {shelves}" in (await town.call("Olga", "look_around")).text
    assert "On the shelves" not in world.ports["Mei"].situation()
    assert (await town.call("Olga", "start_work")).text == (
        f"You sat down to work. It is 07:10. The counter is open. At the counter: {shelves}"
    )
    assert (await town.call("Olga", "start_work")).text == "You are at work already."
    assert (
        world.ports["Mei"]
        .situation()
        .endswith(
            "Also here: Aisha and Olga (working). At the counter: bread $4 (10 left), eggs $2 (10 "
            "left), vegetables $3 (10 left), bicycle $50 (1 left), phone $40 (2 left) and coat $30 "
            "(1 left). Your purse holds $120."
        )
    )
    town.take("Olga")
    assert (await town.call("Mei", "buy", item="bread", units=2)).text == (
        "You bought 2 helpings of bread for $8. You have 2 helpings of bread. Your purse holds "
        "$112."
    )
    assert town.take("Olga") == [
        "Mei bought 2 helpings of bread for $8.",
        "You received $2 for a sale.",
    ]
    assert (await town.call("Aisha", "buy", item="coat")).text == (
        "You bought a coat for $30. You have a coat. Your purse holds $0."
    )
    assert (await town.call("Aisha", "buy", item="bread")).text == (
        "You do not have $4. Your purse holds $0."  # a purse never goes below zero
    )
    assert (await town.call("Mei", "buy", item="coat")).text == "The store has no coat left."
    assert (await town.call("Mei", "buy", item="bread", units=9)).text == (
        "The store has only 8 helpings of bread left."
    )
    assert (await town.call("Mei", "buy", item="phone", units=2)).text == (
        "You can have only one phone."
    )
    assert world.holders["shelves"].items == {
        "bread": 8, "eggs": 10, "vegetables": 10, "bicycle": 1, "phone": 2,
    }  # fmt: skip
    assert "sold out: coat." in world.ports["Mei"].situation()
    sold = [e for e in world.log.entries() if e["kind"] == "move"]
    assert [(e["actor"], e["text"], e["audience"]) for e in sold] == [
        ("Mei", "Mei bought 2 helpings of bread for $8.", ["Olga"]),
        ("Aisha", "Aisha bought a coat for $30.", ["Olga"]),
    ]
    assert sold[0]["payload"] == {
        "item": "bread", "units": 2, "source": "shelves", "target": "Mei", "money": 8,
        "reason": "buy", "seller": "Olga",
    }  # fmt: skip
    assert world.fund.ledger == {"sale": 38, "service": 4} and olga.inventory.money == 104
    # The shopkeeper buys at her own counter, and is paid nothing for serving herself; once she
    # stops work the door is shut.
    assert (await town.call("Olga", "buy", item="bread")).text.startswith(
        "You bought 1 helping of bread for $4."
    )
    assert olga.inventory.money == 100 and world.fund.ledger["service"] == 4
    await town.call("Olga", "leave_work")
    assert (await town.call("Mei", "buy", item="bread")).text == closed


async def test_an_order_is_paid_at_once_and_arrives_the_next_morning_and_prices_are_set(make_town):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    await town.call("Olga", "go", place="store")
    await town.until("07:10")
    ordered = await town.call("Olga", "order", item="bread", quantity=5)
    assert ordered.text == (
        "You sat down to work. It is 07:10. You ordered 5 helpings of bread from the supplier for "
        "$10, which the fund paid; it arrives tomorrow at 08:00."
    )
    assert world.fund.balance == 1000 - 10 and world.fund.ledger == {"supplier": 10}
    assert world.store.pending == [["bread", 5, at("08:00", day=2)]]
    assert "On order from the supplier: 5 helpings of bread." in world.ports["Olga"].situation()
    world.fund.balance = 3
    assert (await town.call("Olga", "order", item="phone", quantity=1)).text == (
        "The fund cannot pay the supplier $25 now."
    )
    world.fund.balance = 990
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
    town.rest()
    await town.until("07:59", day=2)
    assert world.holders["shelves"].units("bread") == 10
    await town.until("08:00", day=2)
    assert world.holders["shelves"].units("bread") == 15 and world.store.pending == []
    delivered = [e for e in world.log.entries() if e["kind"] == "delivery"]
    assert [(e["text"], e["audience"], e["payload"]) for e in delivered] == [
        (
            "It is 08:00: the supplier delivered 5 helpings of bread to the store.",
            ["Olga"],
            {"items": {"bread": 5}},
        )
    ]
    assert [p.text for p in town.heard["Olga"] if p.kind == "delivery"] == [delivered[0]["text"]]


async def test_the_chef_buys_for_the_kitchen_cooks_and_serves_and_what_is_left_goes(make_town):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    jonas, mei = world.residents["Jonas"], world.residents["Mei"]
    before = total(world)
    for name in ("Olga", "Jonas"):
        await town.call(name, "go", place="store")
    await town.until("07:10")
    await town.call("Olga", "start_work")
    # Without for_the_kitchen the chef buys for himself; with it, for the kitchen, and the fund
    # pays. Only the chef's buy takes it, and his work is not here.
    assert (await town.call("Jonas", "buy", item="eggs", units=2)).text == (
        "You bought 2 units of eggs for $4. You have 2 units of eggs. Your purse holds $96."
    )
    assert "start_work" not in offered(town, "Jonas") and "cook" not in offered(town, "Jonas")
    assert (
        await town.call("Jonas", "start_work")
    ).text == "Your work is at the café on the square."
    chefs = {spec.name: spec for spec in town.world.ports["Jonas"].tool_specs()}
    assert "for_the_kitchen" in chefs["buy"].parameters["properties"]
    olgas = {spec.name: spec for spec in town.world.ports["Olga"].tool_specs()}
    assert "for_the_kitchen" not in olgas["buy"].parameters["properties"]
    assert (await town.call("Olga", "buy", item="eggs", for_the_kitchen=True)).text == (
        "buy takes no for_the_kitchen."
    )
    assert (await town.call("Jonas", "buy", item="eggs", units=4, for_the_kitchen=True)).text == (
        "You bought 4 units of eggs for the kitchen for $8, which the fund paid. The kitchen "
        "holds 4 units of eggs."
    )
    await town.call("Jonas", "buy", item="vegetables", units=5, for_the_kitchen=True)
    assert (await town.call("Jonas", "buy", item="coat", for_the_kitchen=True)).text == (
        "A coat is nothing the kitchen cooks with."
    )
    assert world.holders["larder"].items == {"eggs": 4, "vegetables": 5}
    assert jonas.inventory.money == 96
    assert world.fund.ledger == {"sale": 4 + 8 + 15, "kitchen": 23, "service": 6}
    assert (await town.call("Jonas", "cook", dish="omelette", portions=1)).text == (
        "You can do that only at the café on the square."
    )
    await town.call("Jonas", "go", place="cafe")
    await town.until("07:20")
    assert jonas.worked == 0  # an hour at work counts at one's own workplace only
    assert (await town.call("Jonas", "cook", dish="omelette", portions=3)).text == (
        "You sat down to work. It is 07:20. For 3 portions of omelette the kitchen is short: it "
        "needs 6 units of eggs, of which it holds 4."
    )
    assert (await town.call("Jonas", "cook", dish="omelette", portions=2)).text == (
        "You cooked 2 portions of omelette; 2 ready to serve. The kitchen holds 3 units of "
        "vegetables."
    )
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
    assert "On the menu: omelette $12 (2 ready) and vegetable soup $8 (none ready)." in (
        world.ports["Mei"].situation()
    )
    assert (await town.call("Mei", "buy", item="soup")).text == (
        "The kitchen has no vegetable soup ready."
    )
    assert (await town.call("Mei", "buy", item="omelette", units=2)).text == ("One dish at a time.")
    town.take("Jonas")
    mei.living.satiety = 40
    assert (await town.call("Mei", "buy", item="omelette")).text == (
        "You had an omelette for $12. You are well fed. Your purse holds $108."
    )
    assert mei.living.eaten == {"omelette": 1} and world.nourishment(mei) == 100
    assert town.take("Jonas") == [
        "You served Mei an omelette for $12.",
        "You received $3 for a dish served.",
    ]
    served = [e for e in world.log.entries() if e["kind"] == "move" and e["actor"] == "Mei"]
    assert [e["text"] for e in served] == [
        "Jonas served Mei an omelette for $12.",
        "Mei ate an omelette.",  # out of her hands into nothing, there and then
    ]
    assert [e["payload"] for e in served] == [
        {"item": "omelette", "units": 1, "source": "portions", "target": "Mei", "money": 12,
         "reason": "buy", "seller": "Jonas"},
        {"item": "omelette", "units": 1, "source": "Mei", "target": None, "money": 0,
         "reason": "eat", "seller": None},
    ]  # fmt: skip
    assert (await town.call("Jonas", "buy", item="omelette")).text == (
        "You cook the dishes here; you cannot buy them."
    )
    await town.call("Jonas", "cook", dish="soup", portions=1)
    # On duty, the chef can hand a dish over: it is eaten there and then, and nobody pays.
    assert (await town.call("Jonas", "pass", item="omelette", to="Mei")).text == (
        "You served Mei an omelette, which nobody paid for."
    )
    assert mei.living.eaten == {"omelette": 2} and mei.inventory.money == 108
    assert town.take("Mei")[-1] == "Jonas served you an omelette, which nobody paid for."
    assert (await town.call("Jonas", "pass", item="omelette", to="Mei")).text == (
        "The kitchen has no omelette ready."
    )
    await town.until("08:20")
    await town.call("Jonas", "leave_work")
    assert jonas.worked == 3600
    assert (await town.call("Mei", "buy", item="omelette")).text == "The kitchen is closed."
    assert "The kitchen is closed." in world.ports["Mei"].situation()
    assert "On the menu" not in world.ports["Mei"].situation()
    assert "On the menu" in world.ports["Jonas"].situation()  # the chef sees it, open or shut
    # At midnight the portion left is gone, and the chef's statement says so. The money in the
    # town changed by what the supplier was paid, nothing, and the clients, nothing: the rest
    # moved between the fund and the purses.
    for name in world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    assert world.holders["portions"].items == {} and world.holders["larder"].items == {
        "vegetables": 1
    }
    statement = town.take("Jonas")[-1]
    assert "What the kitchen did not sell is gone: vegetable soup." in statement
    assert "received $3 for a dish served" in statement
    statement = town.take("Mei")[-1]
    assert statement.startswith(
        "Your statement for Monday 1 January: bought an omelette for $12; no time at work;"
    )
    assert "You ate today: 2 portions of omelette." in statement
    assert total(world) == before


async def test_the_checkpoint_keeps_the_store_and_the_kitchen_and_money_comes_only_from_clients(
    make_town, tmp_path
):
    town = make_town(SHOPS)
    await awake_at(town)
    world = town.world
    before = total(world)
    for name in ("Olga", "Jonas", "Tomas"):
        await town.call(name, "go", place="store")
    await town.until("07:10")
    await town.call("Olga", "order", item="eggs", quantity=6)
    await town.call("Olga", "set_price", item="vegetables", price=4)
    await town.call("Jonas", "buy", item="vegetables", units=6, for_the_kitchen=True)
    await town.call("Tomas", "buy", item="phone")
    await town.call("Jonas", "go", place="cafe")
    await town.call("Mei", "go", place="workshop")
    await town.until("09:00")
    await town.call("Jonas", "cook", dish="soup", portions=2)
    await town.call("Jonas", "set_price", item="soup", price=9)
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    await town.call("Mei", "submit")  # the client pays the fund $50
    await town.call("Mei", "go", place="cafe")
    await town.until("09:10")
    await town.call("Mei", "buy", item="soup")
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
        "bread": 10, "eggs": 10, "vegetables": 4, "bicycle": 1, "phone": 1, "coat": 1,
    }  # fmt: skip
    assert holders["larder"] == {"vegetables": 2} and holders["portions"] == {}  # the soup perished
    # Only the client's $50 came in and only the supplier's $6 went out; every other movement,
    # the sales, the dish, the kitchen's purchase, wages, rent and sums, stayed in the town.
    assert world.fund.yesterday["client"] == 50 and world.fund.yesterday["supplier"] == 6
    assert total(world) == before + 50 - 6
    make_agent_dirs(tmp_path / "r", world.config)
    restored = World(world.config, tmp_path / "r", FakeBackend(), clock=ManualClock())
    restored.restore(json.loads(json.dumps(state)))
    assert restored.snapshot() == state
