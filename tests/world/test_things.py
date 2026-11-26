"""Things and money in the open: taken from a shelf, from where they were left and from a person,
awake or asleep, with nobody's leave and nothing charged; given to a person or left anywhere;
seen by everyone there and awake, each in the words of its part, and by nobody else; told to an
owner who did not see it, on waking or coming back, as what is gone and never by whom; taxed only
as money given to one at work; never made nor lost but by the town's sources and sinks, so that
the log alone rebuilds every holding; and kept whole by a checkpoint in the middle of it all."""

from __future__ import annotations

import json
import random
from collections import Counter

from tests.support.towns import (
    CARE,
    RESIDENTS,
    TRADES,
    Town,
    awake_at,
    make_agent_dirs,
    town_config,
)
from tests.world.acts import census, give, keys, money, moves, take
from world.clock import ManualClock
from world.events import Bedridden, Work
from world.testing import FakeBackend
from world.world import World

TOWN = town_config(residents=RESIDENTS + TRADES + CARE, tax=0.1)


async def gathered(town: Town, place: str, *names: str, hour: str = "07:10") -> None:
    """`names` walk to `place` and are there by `hour`; what they were told on the way is
    taken."""
    for name in names:
        await town.call(name, "go", place=place)
    await town.until(hour)
    for name in town.world.residents:
        town.take(name)


async def test_a_thing_on_a_shelf_is_taken_without_paying_and_those_there_see_it(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    await gathered(town, "store", "Mei", "Aisha", "Olga")
    # The shelves are simply there, the keeper at work or not, and are read by whoever is.
    shelves = (
        "On the shelves: bread $4 (10 left), eggs $2 (10 left), vegetables $3 (10 left), "
        "bicycle $50 (1 left), phone $40 (2 left) and coat $30 (1 left)."
    )
    assert shelves in world.ports["Mei"].situation() and shelves in world.ports["Olga"].situation()
    # Nothing is charged: the price posted is told, and the purse is as it was.
    assert await take(town, "Mei", "bread", "shelves", 3) == (
        "You took 3 helpings of bread from the shelves. The price posted is $4 each, $12 in "
        "all. You carry 3 helpings of bread."
    )
    assert world.residents["Mei"].inventory.money == 120
    assert world.holders["shelves"].units("bread") == 7
    # Everyone there and awake saw it, each in the words of its part; nobody elsewhere did.
    assert town.take("Olga") == ["Mei took 3 helpings of bread from your shelves."]
    assert town.take("Aisha") == ["Mei took 3 helpings of bread from the shelves."]
    assert town.take("Tomas") == []
    taken = moves(world)[-1]
    assert (taken["actor"], taken["place"], taken["audience"]) == (
        "Mei",
        "store",
        ["Aisha", "Olga"],
    )
    assert taken["payload"] == {
        "what": "bread", "amount": 3, "source": "shelves", "target": "Mei", "reason": "take",
        "price": 4, "tax": 0,
    }  # fmt: skip
    # One thing has its price told plainly; the keeper's own take is told the same.
    assert await take(town, "Aisha", "coat", "shelves") == (
        "You took a coat from the shelves. The price posted for it is $30. You carry a coat."
    )
    assert await take(town, "Olga", "phone", "shelves", 2) == (
        "You took 2 phones from your shelves. The price posted is $40 each, $80 in all. You "
        "carry 2 phones."
    )
    assert "none left: phone and coat." in world.ports["Mei"].situation()
    # Paying is giving the keeper the money, a gift of its own that nothing ties to the take.
    assert (
        await give(town, "Mei", "money", "Olga", 12) == "You gave Olga $12. Your purse holds $108."
    )
    assert moves(world)[-1]["payload"] == {
        "what": "money", "amount": 12, "source": "Mei", "target": "Olga", "reason": "give",
        "price": None, "tax": 0,
    }  # fmt: skip


async def test_a_person_is_taken_from_awake_and_what_is_left_anywhere_by_whoever_comes(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    mei, aisha = world.residents["Mei"], world.residents["Aisha"]
    aisha.inventory.items.update({"coat": 1, "bread": 2})
    await gathered(town, "park", "Mei", "Aisha", "Tomas")
    # From a person standing there: the thing, and money, as much as is asked or as there is.
    assert (
        await take(town, "Mei", "coat", "Aisha") == "You took a coat from Aisha. You carry a coat."
    )
    assert town.take("Aisha") == ["Mei took a coat from you."]
    assert town.take("Tomas") == ["Mei took a coat from Aisha."]
    assert await take(town, "Mei", "money", "Aisha", 10) == (
        "You took $10 from Aisha. Your purse holds $130."
    )
    assert await take(town, "Mei", "money", "Aisha", 500) == (
        "You took $20 from Aisha, all there was. Your purse holds $150."
    )
    assert (aisha.inventory.money, mei.inventory.money) == (0, 150)
    assert [e["payload"]["price"] for e in moves(world)] == [None, None, None]  # none posted
    # Left where one is, a thing or money is there for whoever comes, and is told to those there.
    assert await give(town, "Mei", "coat", "here") == (
        "You left a coat at the park. You carry nothing but your money."
    )
    assert await give(town, "Mei", "money", "here", 7) == (
        "You left $7 at the park. Your purse holds $143."
    )
    assert town.take("Tomas")[-2:] == ["Mei left a coat at the park.", "Mei left $7 at the park."]
    assert (
        world.ports["Tomas"]
        .situation()
        .endswith("Left here: $7 and a coat. Your purse holds $180. None of the others likes you.")
    )
    assert (await town.call("Tomas", "look_around")).text.endswith("Left here: $7 and a coat.")
    for name in ("Mei", "Aisha", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.call("Olga", "go", place="park")
    await town.until("07:30")
    assert "Left here: $7 and a coat." in world.ports["Olga"].situation()
    assert await take(town, "Olga", "money", "here", 7) == (
        "You took $7 left at the park. Your purse holds $107."
    )
    assert await take(town, "Olga", "coat", "here") == (
        "You took a coat left at the park. You carry a coat."
    )
    assert world.holders["park"].items == {} and world.holders["park"].money == 0
    assert moves(world)[-1]["audience"] == []  # nobody was there to see it
    # What each purse saw of its money, the statement tells; who took, it does not say.
    town.rest()
    await town.until("00:00", day=2)
    told = {n: [p.text for p in town.heard[n] if p.kind == "settlement"][-1] for n in town.heard}
    assert told["Mei"].startswith(
        "Your statement for Monday 1 January: took $10 from Aisha; took $20 from Aisha; left $7 "
        "at the park; rent for your room"
    )
    assert told["Aisha"].startswith(
        "Your statement for Monday 1 January: $10 was taken from you; $20 was taken from you; "
        "rent for your room"
    )
    assert told["Olga"].startswith(
        "Your statement for Monday 1 January: took $7 left at the park; rent for your room"
    )


async def test_giving_is_of_what_one_carries_to_a_person_or_a_shelf(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    mei, aisha = world.residents["Mei"], world.residents["Aisha"]
    mei.inventory.items.update({"bread": 6, "phone": 1})
    await gathered(town, "store", "Mei", "Aisha")
    assert await give(town, "Mei", "phone", "Aisha") == (
        "You gave Aisha a phone. You carry 6 helpings of bread."
    )
    assert town.take("Aisha") == ["Mei gave you a phone."]
    assert (
        await give(town, "Mei", "money", "Aisha", 5) == "You gave Aisha $5. Your purse holds $115."
    )
    # More than one carries is not given, and nothing moves.
    assert await give(town, "Mei", "phone", "Aisha") == "You have no phone."
    assert await give(town, "Mei", "bread", "Aisha", 7) == "You have only 6 helpings of bread."
    assert await give(town, "Aisha", "money", "Mei", 36) == "You have only $35."
    aisha.inventory.money = 0
    assert await give(town, "Aisha", "money", "Mei") == "You have no money."
    assert (await town.call("Mei", "give", what="money", amount=0, to="Aisha")).text == (
        "amount must be a whole number of at least 1."
    )
    assert (await town.call("Mei", "give", what="money", amount="4", to="Aisha")).text == (
        "You gave Aisha $4. Your purse holds $111."
    )  # a whole number written in digits is taken as the number
    assert (mei.inventory.money, aisha.inventory.money, mei.inventory.units("bread")) == (111, 4, 6)
    # Food handed to one who could eat is eaten at once, as far as it could eat, and it is told.
    aisha.living.satiety = 30
    town.take("Aisha")
    assert await give(town, "Mei", "bread", "Aisha", 3) == (
        "You gave Aisha 3 helpings of bread. You carry 3 helpings of bread."
    )
    assert town.take("Aisha") == [
        "Mei gave you 3 helpings of bread.",
        "You ate 1 helping of bread.",
        "You ate 1 helping of bread.",
        "You are well fed.",
    ]
    assert aisha.inventory.units("bread") == 1 and aisha.living.eaten == {"bread": 2}
    # Onto a shelf goes whatever one carries, money too; it stands there with the rest.
    assert await give(town, "Mei", "bread", "shelves", 3) == (
        "You left 3 helpings of bread on the shelves. You carry nothing but your money."
    )
    assert await give(town, "Mei", "money", "shelves", 12) == (
        "You left $12 on the shelves. Your purse holds $99."
    )
    assert world.holders["shelves"].units("bread") == 13 and world.holders["shelves"].money == 12
    assert "coat $30 (1 left); also there: $12. Your purse" in world.ports["Mei"].situation()


async def test_a_take_finds_only_what_is_there_and_reaches_only_where_one_is(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    await gathered(town, "store", "Mei", "Aisha", "Jonas")
    start = census(world)
    # What is not there is not taken: on a shelf, on a person, where one stands.
    assert await take(town, "Mei", "omelette", "shelves") == "You find no omelette on the shelves."
    assert await take(town, "Mei", "money", "shelves") == "You find no money on the shelves."
    assert await take(town, "Mei", "phone", "Aisha") == "Aisha has no phone."
    assert await take(town, "Mei", "bread", "here", 2) == "You find no bread at the store."
    assert await take(town, "Mei", "money", "here") == "You find no money at the store."
    # Less than asked is all there was, and said so.
    assert await take(town, "Mei", "bicycle", "shelves", 2) == (
        "You took a bicycle from the shelves, all there was. The price posted for it is $50. "
        "You carry a bicycle."
    )
    # One reaches only what is where one is: not a shelf elsewhere, nor one who is elsewhere.
    assert (
        await take(town, "Mei", "omelette", "counter") == "You are not at the café on the square."
    )
    assert await give(town, "Mei", "bicycle", "larder") == "You are not at the café on the square."
    assert await take(town, "Mei", "money", "Tomas") == "Tomas is not here."
    assert await give(town, "Mei", "money", "Tomas") == "Tomas is not here."
    await town.call("Aisha", "go", place="park")
    assert await take(town, "Mei", "money", "Aisha") == "Aisha is not here."  # on her way
    await town.until("07:20")
    assert await take(town, "Mei", "money", "Aisha") == "Aisha is not here."  # and gone
    # A name that is nobody's, oneself, and what the town has no such thing as.
    assert await take(town, "Mei", "bread", "Zoe") == (
        "There is nobody called Zoe in the town. Name a person, shelves, counter, larder or here."
    )
    assert await take(town, "Mei", "bread", "Mei") == "You cannot take from yourself."
    assert await give(town, "Mei", "bicycle", "Mei") == "You cannot give to yourself."
    assert (await take(town, "Mei", "gold", "shelves")).startswith("what must be one of: money, ")
    assert (await town.call("Mei", "take", what="bread")).text == "take needs from."
    assert await take(town, "Mei", "bread", "Shelves") == (
        "You took 1 helping of bread from the shelves. The price posted for it is $4. You carry "
        "1 helping of bread and a bicycle."
    )  # however the shelf's name is written
    assert census(world) == start and len(moves(world)) == 2  # the refused moved nothing


async def test_money_given_to_one_at_work_is_taxed_and_no_other_money_is(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world, treasury = town.world, town.world.treasury
    olga, tomas = world.residents["Olga"], world.residents["Tomas"]
    before = money(world)
    await gathered(town, "store", "Mei", "Olga")
    # The keeper not yet at work: what she is given is hers whole.
    assert (
        await give(town, "Mei", "money", "Olga", 30) == "You gave Olga $30. Your purse holds $90."
    )
    assert town.take("Olga") == ["Mei gave you $30."]
    assert (olga.inventory.money, treasury.ledger) == (130, {})
    # At work, the same gift is payment for her work: a tenth withheld, rounded down, and told.
    await town.call("Olga", "start_work")
    assert (
        await give(town, "Mei", "money", "Olga", 39) == "You gave Olga $39. Your purse holds $51."
    )
    assert town.take("Olga") == ["Mei gave you $39, of which $3 in tax."]
    assert (olga.inventory.money, treasury.ledger) == (130 + 39 - 3, {"tax": 3})
    assert await give(town, "Mei", "money", "Olga", 9) == "You gave Olga $9. Your purse holds $42."
    assert town.take("Olga") == ["Mei gave you $9."]  # a tenth of $9, rounded down, is nothing
    paid = [e["payload"] for e in moves(world)]
    assert [(p["amount"], p["tax"]) for p in paid] == [(30, 0), (39, 3), (9, 0)]
    # Money left on her shelves, and money taken from her at work, is not money given to her.
    await give(town, "Mei", "money", "shelves", 20)
    assert await take(town, "Olga", "money", "shelves", 20) == (
        "You took $20 from your shelves. Your purse holds $195."
    )
    assert await take(town, "Mei", "money", "Olga", 50) == (
        "You took $50 from Olga. Your purse holds $72."
    )
    assert treasury.ledger == {"tax": 3} and olga.inventory.money == 145
    # The rule is the same for every occupation: a programmer at work, the mayor on her rounds.
    await town.call("Olga", "leave_work")
    await town.call("Mei", "go", place="workshop")
    await town.call("Tomas", "go", place="workshop")
    await town.call("Vera", "go", place="hall")
    await town.until("07:30")
    await town.call("Tomas", "start_work")
    await town.call("Vera", "start_work")
    await give(town, "Mei", "money", "Tomas", 20)
    assert (tomas.inventory.money, treasury.ledger) == (180 + 20 - 2, {"tax": 5})
    await town.call("Tomas", "say", text="Thanks.", to=["Mei"])  # talking, he is still at work
    await give(town, "Mei", "money", "Tomas", 10)
    assert treasury.ledger == {"tax": 6}
    await town.call("Vera", "go", place="workshop")  # her duty goes with her
    await town.until("07:40")
    await give(town, "Mei", "money", "Vera", 10)
    assert treasury.ledger == {"tax": 7} and isinstance(world.residents["Vera"].base, Work)
    assert money(world) == before  # the tax moved money within the town, and nothing else did
    # The statement tells what was earned at work, by whom it was given, with the tax, apart
    # from what was given otherwise.
    town.rest()
    await town.until("00:00", day=2)
    statement = [p.text for p in town.heard["Olga"] if p.kind == "settlement"][-1]
    assert statement.startswith(
        "Your statement for Monday 1 January: received $48 from Mei at work, $3 of it in tax; "
        "received $30 from Mei; took $20 from the shelves; $50 was taken from you; rent for"
    )


async def test_one_asleep_sees_nothing_and_is_told_on_waking_what_is_gone_never_who(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    mei, aisha = world.residents["Mei"], world.residents["Aisha"]
    aisha.inventory.items.update({"phone": 1, "coat": 1})
    await town.call("Aisha", "sleep", likes=[], until="12:00")
    town.rest("Aisha")
    await town.until("07:05")
    assert (
        aisha.suspended
        and "Also here: Aisha (asleep, liked by 0)." in world.ports["Mei"].situation()
    )
    town.heard["Aisha"].clear()  # what going to bed told her
    # Asleep in the same house, she is taken from like anyone, and perceives nothing.
    assert await take(town, "Mei", "money", "Aisha", 25) == (
        "You took $25 from Aisha. Your purse holds $145."
    )
    assert (
        await take(town, "Mei", "phone", "Aisha")
        == "You took a phone from Aisha. You carry a phone."
    )
    assert await take(town, "Mei", "coat", "Aisha") == (
        "You took a coat from Aisha. You carry a phone and a coat."
    )
    assert [e["audience"] for e in moves(world)] == [[], [], []]
    assert world.ports["Aisha"].held == [] and town.heard["Aisha"] == []
    # What is put back while she sleeps is not missing; what she is given, she finds.
    assert await give(town, "Mei", "coat", "Aisha") == "You gave Aisha a coat. You carry a phone."
    assert (
        await give(town, "Mei", "money", "Aisha", 5) == "You gave Aisha $5. Your purse holds $140."
    )
    assert aisha.missing == {"Aisha": {"money": 20, "phone": 1, "coat": 0}}
    await town.until("12:00")
    woke = [p.text for p in town.heard["Aisha"]]
    assert woke[0].startswith("You woke up at home. It is Monday 1 January, 12:00.")
    assert woke[1] == "While you slept, $20 and a phone went from what you carry."
    assert aisha.missing == {} and len(woke) == 2
    told = [e for e in world.log.entries() if e["kind"] == "missing"]
    assert [(e["actor"], e["audience"], e["text"], e["payload"]) for e in told] == [
        (
            "Aisha",
            ["Aisha"],
            "Aisha found $20 and a phone gone from what it carried.",
            {"holder": "Aisha", "gone": {"money": 20, "phone": 1}},
        )
    ]
    assert "Mei" not in woke[1] and aisha.inventory.money == 10
    # Awake, she sees for herself, and nothing is told her a second time.
    await take(town, "Mei", "money", "Aisha", 10)
    assert town.heard["Aisha"][-1].text == "Mei took $10 from you." and aisha.missing == {}
    assert mei.inventory.money == 150


async def test_a_keeper_away_is_told_on_coming_back_what_went_from_the_business(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    olga, jonas = world.residents["Olga"], world.residents["Jonas"]
    world.holders["counter"].add("soup", 2)
    world.holders["larder"].add("eggs", 6)
    await gathered(town, "store", "Mei", "Aisha")
    # The shelves unattended: emptied before a customer's eyes, and the keeper knows nothing.
    assert await take(town, "Mei", "bread", "shelves", 10) == (
        "You took 10 helpings of bread from the shelves. The price posted is $4 each, $40 in "
        "all. You carry 10 helpings of bread."
    )
    await take(town, "Mei", "bicycle", "shelves")
    await take(town, "Mei", "eggs", "shelves", 4)
    await give(town, "Mei", "eggs", "shelves", 1)  # one put back
    await give(town, "Aisha", "money", "shelves", 6)  # and money left there by another
    assert town.take("Aisha")[:2] == [
        "Mei took 10 helpings of bread from the shelves.",
        "Mei took a bicycle from the shelves.",
    ]
    assert town.take("Olga") == [] and world.ports["Olga"].held == []
    assert olga.missing == {"shelves": {"bread": 10, "bicycle": 1, "eggs": 3, "money": -6}}
    # She is told as she comes in, what and how much, less what was put back, and not by whom.
    for name in ("Mei", "Aisha"):
        await town.call(name, "go", place="cafe")
    await town.call("Olga", "go", place="store")
    await town.until("07:30")
    arrived = town.take("Olga")
    assert arrived[0].startswith("You arrived at the store. Nobody else is here.")
    assert arrived[1:] == [
        "Since you were last here, 10 helpings of bread, 3 units of eggs and a bicycle went "
        "from the shelves."
    ]
    assert "none left: bread and bicycle; also there: $6." in world.ports["Olga"].situation()
    assert olga.missing == {}
    # What she sees taken herself is not told her again when she next comes back.
    await town.call("Tomas", "go", place="store")
    await town.until("07:45")
    await take(town, "Tomas", "phone", "shelves")
    assert town.take("Olga")[-1] == "Tomas took a phone from your shelves."
    await town.call("Olga", "go", place="park")
    await town.until("08:00")
    await town.call("Olga", "go", place="store")
    await town.until("08:15")
    assert [text for text in town.take("Olga") if "went from" in text] == []
    # The kitchen's counter and its larder are the chef's the same way, each told of its own.
    assert await take(town, "Mei", "soup", "counter", 2) == (
        "You took 2 portions of vegetable soup from the counter. The price posted is $8 each, "
        "$16 in all. You ate 2 portions of vegetable soup at once. You carry 10 helpings of "
        "bread, 3 units of eggs and a bicycle."
    )
    assert await take(town, "Aisha", "eggs", "larder", 5) == (
        "You took 5 units of eggs from the larder. You carry 5 units of eggs."
    )
    assert moves(world)[-1]["payload"]["price"] is None  # nothing in the larder has a price
    await town.call("Jonas", "go", place="cafe")
    await town.until("08:30")
    assert town.take("Jonas")[-2:] == [
        "Since you were last here, 2 portions of vegetable soup went from the counter.",
        "Since you were last here, 5 units of eggs went from the larder.",
    ]
    assert jonas.missing == {}
    gone = [e["payload"] for e in world.log.entries() if e["kind"] == "missing"]
    assert gone == [
        {"holder": "shelves", "gone": {"bread": 10, "bicycle": 1, "eggs": 3}},
        {"holder": "counter", "gone": {"soup": 2}},
        {"holder": "larder", "gone": {"eggs": 5}},
    ]


def rebuilt(config, entries) -> tuple[dict[str, Counter], Counter, int]:
    """The things and the money of every holder, and the treasury's money, as the town's
    start and the log's entries alone give them."""
    things: dict[str, Counter] = {"shelves": Counter(config.store.stock)}
    purses: Counter = Counter({r.name: r.purse for r in config.residents})
    treasury = config.treasury.start
    for entry in entries:
        kind, actor, p = entry["kind"], entry["actor"], entry["payload"]
        if kind == "move":
            for key, sign in ((p["source"], -1), (p["target"], 1)):
                if key is not None and p["what"] == "money":
                    purses[key] += sign * p["amount"]
                elif key is not None:
                    things.setdefault(key, Counter())[p["what"]] += sign * p["amount"]
            if p["tax"]:
                purses[p["target"]] -= p["tax"]
                treasury += p["tax"]
        elif kind == "cook":
            for item, units in p["used"].items():
                carried = p["carried"].get(item, 0)
                things.setdefault("larder", Counter())[item] -= units - carried
                things.setdefault(actor, Counter())[item] -= carried
            things.setdefault("counter", Counter())[p["dish"]] += p["portions"]
        elif kind == "delivery":
            things["shelves"].update(p["items"])
        elif kind == "perished":
            things[p["source"]][p["item"]] -= p["units"]
        elif kind == "order":
            purses[actor] -= p["amount"]
        elif kind == "service":
            purses[actor] += p["amount"] - p["tax"]
            treasury += p["tax"]
        elif kind == "grant":
            purses[p["to"]] += p["amount"]
            treasury -= p["amount"]
        elif kind == "settlement":
            purses[actor] += p["salary_paid"] - p["rent_paid"]
            treasury += p["rent_paid"] - p["salary_paid"]
    return things, purses, treasury


def as_it_stands(world) -> tuple[dict[str, Counter], Counter, int]:
    """The same of the world as it stands."""
    things = {key: Counter(world.holder(key).items) for key in keys(world)}
    purses = Counter({key: world.holder(key).money for key in keys(world)})
    return things, purses, world.treasury.balance


def same(rebuilt_: tuple, standing: tuple) -> bool:
    """Whether what was rebuilt is what stands, a holder of nothing being no holder."""
    (things, purses, treasury), (held, kept, balance) = rebuilt_, standing
    stripped = {key: +counter for key, counter in things.items() if +counter}
    return (
        stripped == {key: counter for key, counter in held.items() if counter}
        and +purses == +kept
        and treasury == balance
    )


async def test_any_run_of_takes_and_gives_conserves_everything_and_the_log_rebuilds_it(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    await gathered(town, "store", "Mei", "Aisha", "Olga", "Jonas", "Tomas")
    await town.call("Olga", "start_work")
    # The kitchen is stocked and has cooked, by the town's own actions, before the run.
    await take(town, "Jonas", "eggs", "shelves", 6)
    await take(town, "Jonas", "vegetables", "shelves", 7)
    await gathered(town, "cafe", "Jonas", "Lucia", "Vera", hour="07:20")
    await give(town, "Jonas", "vegetables", "larder", 4)
    await town.call("Jonas", "cook", dish="omelette", portions=2)
    await town.call("Jonas", "cook", dish="soup", portions=1)
    for r in world.residents.values():
        r.living.satiety = 100  # nobody eats bread during the run; a dish is eaten as taken
    cash, units = money(world), census(world)
    here = {"store": ["Mei", "Aisha", "Olga", "Tomas"], "cafe": ["Jonas", "Lucia", "Vera"]}
    ends = {"store": ["shelves", "here"], "cafe": ["counter", "larder", "here"]}
    things = ["money", *(item.id for item in world.config.items)]
    rng = random.Random(20261126)
    done = 0
    for _ in range(600):
        place = rng.choice(list(here))
        who = rng.choice(here[place])
        other = rng.choice([name for name in here[place] if name != who] + ends[place])
        act = rng.choice([take, give])
        # Mostly of what its source holds, sometimes of what it does not, and often too much.
        source = world.holder(who if act is give else place if other == "here" else other)
        held = [what for what in things if source.has(what)]
        what = rng.choice(held if held and rng.random() < 0.8 else things)
        told = await act(town, who, what, other, rng.randint(1, 12))
        done += told.startswith(("You took", "You gave", "You left"))
        # Money is never made nor lost, and no holder is ever short of what it gave.
        assert money(world) == cash, told
        assert all(world.holder(key).money >= 0 for key in keys(world)), told
    assert done > 200  # the run took and gave in earnest, and was refused in earnest too
    assert len(moves(world)) > done  # with what was eaten
    # Units went nowhere but into those who ate them.
    eaten = Counter()
    for entry in moves(world):
        if entry["payload"]["reason"] == "eat":
            eaten[entry["payload"]["what"]] += entry["payload"]["amount"]
    assert census(world) + eaten == units and set(eaten) <= {"omelette", "soup"}
    # The log alone gives every holding: every transfer has its from, to, what and how much.
    entries = list(world.log.entries())
    assert same(rebuilt(world.config, entries), as_it_stands(world))
    for entry in moves(world):
        payload = entry["payload"]
        assert payload["amount"] > 0 and payload["what"] in things
        assert (payload["price"] is not None) == (
            payload["reason"] == "take"
            and (payload["source"], payload["what"])
            in {
                *(("shelves", item.id) for item in world.config.supplied),
                *(("counter", dish.id) for dish in world.config.dishes),
                *(("larder", dish.id) for dish in world.config.dishes),
            }
        ), payload


async def test_the_towns_sources_and_sinks_are_in_the_log_too_through_a_whole_day(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    cash = money(world)
    await town.call("Mei", "go", place="workshop")
    await town.call("Vera", "go", place="hall")
    await gathered(town, "store", "Olga", "Jonas", "Aisha")
    await town.call("Olga", "order", item="bread", quantity=5)  # $10 to the supplier
    await take(town, "Jonas", "vegetables", "shelves", 6)
    await give(town, "Jonas", "money", "Olga", 18)
    await take(town, "Aisha", "bread", "shelves", 4)
    await town.call("Vera", "grant", amount=7, to="Aisha", reason="For bread.")
    await town.until("09:00")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    await town.call("Mei", "submit")  # a client pays $50
    await gathered(town, "cafe", "Jonas", "Aisha", hour="09:10")
    await give(town, "Jonas", "vegetables", "larder", 2)
    await town.call("Jonas", "cook", dish="soup", portions=3)
    await take(town, "Aisha", "soup", "counter")
    await give(town, "Aisha", "money", "Jonas", 8)
    town.rest()
    await town.until("09:00", day=2)  # midnight's rent, salary and perishing, and a delivery
    kinds = {entry["kind"] for entry in world.log.entries()}
    assert {"order", "delivery", "cook", "perished", "service", "grant", "settlement"} <= kinds
    assert money(world) == cash + 50 - 10
    assert same(rebuilt(world.config, list(world.log.entries())), as_it_stands(world))


async def test_a_checkpoint_in_the_middle_keeps_what_is_left_and_what_is_still_to_be_told(
    make_town, tmp_path
):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    for r in world.residents.values():
        r.inventory.items["bread"] = 9  # nobody goes hungry on the way
    await gathered(town, "store", "Mei", hour="22:00")
    await town.call("Aisha", "sleep", likes=[], until="09:00")
    # Late in the evening, with the keeper at home: the shelves, and money left behind.
    await take(town, "Mei", "phone", "shelves", 2)
    await give(town, "Mei", "money", "shelves", 15)
    await give(town, "Mei", "money", "here", 4)
    await give(town, "Mei", "bread", "here", 2)
    # Then home, where a housemate sleeps.
    await town.call("Mei", "go", place="mill-street-house")
    await town.until("22:15")
    await take(town, "Mei", "money", "Aisha", 12)
    town.rest()
    await town.until("03:00", day=2)
    ((day, state),) = town.checkpoints
    state = json.loads(json.dumps(state))  # as it is written and read
    assert day == 1
    assert state["holders"]["shelves"] == {
        "items": {"bread": 10, "eggs": 10, "vegetables": 10, "bicycle": 1, "coat": 1},
        "money": 15,
    }
    assert state["holders"]["store"] == {"items": {"bread": 2}, "money": 4}
    assert state["holders"]["counter"] == state["holders"]["larder"] == {"items": {}, "money": 0}
    assert state["residents"]["Aisha"]["missing"] == {"Aisha": {"money": 12}}
    assert state["residents"]["Olga"]["missing"] == {"shelves": {"phone": 2, "money": -15}}
    assert state["residents"]["Mei"]["missing"] == {}
    assert state["residents"]["Mei"]["inventory"]["items"]["phone"] == 2
    # A world restored from it stands in the same state, and tells what was still to be told.
    make_agent_dirs(tmp_path / "r", world.config)
    again = Town(World(world.config, tmp_path / "r", FakeBackend(), clock=ManualClock()), None)
    again.world.restore(state)
    try:
        assert again.world.snapshot() == state
        assert money(again.world) == money(world) and census(again.world) == census(world)
        again.start(until_day=3)
        again.rest()
        await again.until("09:00", day=2)
        aisha = [p.text for p in again.heard["Aisha"] if p.kind in ("wake", "missing")]
        assert aisha[0].startswith("You woke up at home. It is Tuesday 2 January, 09:00.")
        assert aisha[1:] == ["While you slept, $12 went from what you carry."]
        await again.world.ports["Olga"].call("go", {"place": "store"})
        await again.until("09:15", day=2)
        assert [p.text for p in again.heard["Olga"]][-1] == (
            "Since you were last here, 2 phones went from the shelves."
        )
        assert "also there: $15. Left here: $4 and 2 helpings of bread." in (
            again.world.ports["Olga"].situation()
        )
    finally:
        await again.close()


async def test_food_is_eaten_by_choice_a_dish_as_it_is_taken_and_what_is_left_perishes(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    mei, jonas = world.residents["Mei"], world.residents["Jonas"]
    mei.inventory.items.update({"bread": 1, "eggs": 2})
    mei.living.satiety = 90  # well fed: the body would not eat it by itself yet
    assert (await town.call("Mei", "use", what="bread")).text == (
        "You ate 1 helping of bread. You are well fed. You carry 2 units of eggs."
    )
    assert (await town.call("Mei", "use", what="bread")).text == "You carry no bread."
    for raw_or_dish in ("eggs", "soup"):  # not eaten as it is; never carried to be eaten later
        refused = (await town.call("Mei", "use", what=raw_or_dish)).text
        assert refused == "what must be one of: bread."
    assert mei.living.eaten == {"bread": 1} and mei.inventory.items == {"eggs": 2}
    assert moves(world)[-1]["payload"] == {
        "what": "bread", "amount": 1, "source": "Mei", "target": None, "reason": "eat",
        "price": None, "tax": 0,
    }  # fmt: skip
    # A dish is eaten by whoever takes it, hungry or not, and so is never carried away.
    world.holders["counter"].add("soup", 3)
    world.holders["counter"].add("omelette", 1)
    world.holders["park"].add("soup", 2)  # a dish someone left
    await gathered(town, "cafe", "Mei", "Jonas")
    mei.living.satiety = 90
    assert await take(town, "Mei", "soup", "counter") == (
        "You took vegetable soup from the counter. The price posted for it is $8. You ate "
        "vegetable soup at once. You carry 2 units of eggs."
    )
    assert mei.living.eaten == {"bread": 1, "soup": 1} and world.nourishment(mei) == 134
    jonas.living.satiety = 90
    assert await take(town, "Jonas", "soup", "counter") == (
        "You took vegetable soup from your counter. The price posted for it is $8. You ate "
        "vegetable soup at once. You carry nothing but your money."
    )  # the chef's own, taken like anyone's
    assert await give(town, "Jonas", "soup", "Mei") == "You have no vegetable soup."
    assert world.holders["counter"].items == {"soup": 1, "omelette": 1}
    # At midnight what perishes is gone from wherever it is; what keeps, keeps.
    town.rest()
    await town.until("00:00", day=2)
    assert world.holders["park"].items == {} and world.holders["counter"].items == {}
    assert mei.inventory.items == {"eggs": 2}
    perished = [e for e in world.log.entries() if e["kind"] == "perished"]
    assert [(e["text"], e["payload"], e["audience"]) for e in perished] == [
        ("2 portions of vegetable soup perished.", {"item": "soup", "units": 2, "source": "park"},
         []),
        ("Vegetable soup perished.", {"item": "soup", "units": 1, "source": "counter"}, []),
        ("An omelette perished.", {"item": "omelette", "units": 1, "source": "counter"}, []),
    ]  # fmt: skip
    statement = [p.text for p in town.heard["Jonas"] if p.kind == "settlement"][-1]
    assert (
        "The dishes left on the counter are gone: an omelette and vegetable soup; what the "
        "larder holds keeps." in statement
    )


async def test_talking_and_in_bed_too_ill_to_get_up_one_still_takes_gives_and_uses(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    mei, aisha = world.residents["Mei"], world.residents["Aisha"]
    mei.inventory.items["bread"] = 4
    mei.living.satiety = 90
    await town.call("Aisha", "say", text="I have not eaten.", to=["Mei"])
    assert mei.conversation is not None
    offered = {spec.name for spec in world.ports["Mei"].tool_specs()}
    assert {"take", "give", "use", "inventory", "look_around", "how_am_i"} <= offered
    for told in (
        await give(town, "Mei", "bread", "Aisha"),
        await give(town, "Mei", "bread", "here"),
        await take(town, "Aisha", "bread", "here"),
        (await town.call("Mei", "use", what="bread")).text,
        (await town.call("Mei", "inventory")).text,
    ):
        assert "conversation" not in told, told
        assert mei.conversation is not None and aisha.conversation is mei.conversation
    await town.call("Mei", "leave_conversation")
    # In bed, too ill to get up: what is handed her she eats, and she pays the one who came.
    mei.living.bedridden, mei.base = True, Bedridden()
    assert {"take", "give", "use"} <= {spec.name for spec in world.ports["Mei"].tool_specs()}
    assert (
        await give(town, "Mei", "money", "Aisha", 3) == "You gave Aisha $3. Your purse holds $117."
    )
    assert await take(town, "Mei", "money", "Aisha", 1) == (
        "You took $1 from Aisha. Your purse holds $118."
    )
