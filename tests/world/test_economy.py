"""Money: the inventory and the town's treasury. A client's payment shared between the one who
handed the task in and the team leader, a tenth withheld into the treasury at receipt; the rent
taken at midnight from the purse above a day's bread, the rest owed and taken later; the mayor's
salary paid as far as the treasury holds and the rest owed; the mayor's grants; the statement,
and the treasury's day in the mayor's; money and things handed over; and the invariant that the
purses and the treasury change only by what clients pay and the supplier is paid. The sales, the
dishes and the supplier are in test_shops."""

from __future__ import annotations

import pytest

from tests.support.towns import CARE, RESIDENTS, TRADES, awake_at, town_config
from world.economy import Inventory, Treasury

LEADER = dict(RESIDENTS[1], occupation="team-leader")
"""Tomas as the team leader."""


def statements(town, name: str) -> list[str]:
    """The statements `name` was told while its runtime rested."""
    return [p.text for p in town.heard[name] if p.kind == "settlement"]


def total(world) -> int:
    """The town's money: the treasury and every purse."""
    return world.treasury.balance + sum(r.inventory.money for r in world.residents.values())


def settled(world) -> dict[str, dict]:
    """The last settlement's payload of each resident."""
    return {e["actor"]: e["payload"] for e in world.log.entries() if e["kind"] == "settlement"}


async def test_a_client_pays_four_fifths_to_the_one_who_handed_it_in_and_a_fifth_to_the_leader(
    make_town,
):
    town = make_town(town_config(residents=(RESIDENTS[0], LEADER, RESIDENTS[2]), tax=0.1))
    await awake_at(town)
    world = town.world
    before = total(world)
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    for name, task in (("Mei", 1), ("Tomas", 2)):
        await town.call(name, "claim_task", task=task)
        await town.call(name, "write_repo_file", path="fix.py", content="FIX\n")
        town.take("Tomas")
    # A tenth of each share is withheld into the treasury as it is received, and told.
    assert (await town.call("Mei", "submit")).text == (
        "Accepted. You received $40 for task 1, of which $4 in tax. Your purse holds $156. It is "
        "09:00."
    )
    assert town.take("Tomas") == [
        "You received $10 for task 1, handed in by Mei, of which $1 in tax."
    ]
    assert (await town.call("Tomas", "submit")).text == (  # the leader's own: the whole
        "Accepted. You received $50 for task 2, of which $5 in tax. Your purse holds $234. It is "
        "09:00."
    )
    paid = [(e["actor"], e["payload"]) for e in world.log.entries() if e["kind"] == "service"]
    assert paid == [
        ("Mei", {"for": "task", "task": 1, "amount": 40, "tax": 4, "money": 156}),
        ("Tomas", {"for": "team", "task": 1, "amount": 10, "tax": 1, "money": 189}),
        ("Tomas", {"for": "task", "task": 2, "amount": 50, "tax": 5, "money": 234}),
    ]
    assert world.treasury.ledger == {"tax": 10} and world.treasury.balance == 1010
    assert total(world) == before + 100  # the clients' payments, and nothing else, came in
    # The statement sums what was earned, with the tax withheld.
    for name in world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    assert town.take("Tomas")[-1].startswith(
        "Your statement for Monday 1 January: received $10 for task 1, handed in by Mei, $1 of "
        "it in tax; received $50 for task 2, $5 of it in tax; rent for your room at the flat by "
        "the college gates $30; your purse paid it."
    )


async def test_rent_is_taken_at_midnight_from_the_purse_above_a_days_bread_and_the_rest_owed(
    make_town,
):
    town = make_town()
    await awake_at(town)
    world = town.world
    before = total(world)
    for name in ("Mei", "Aisha"):
        await town.call(name, "go", place="park")
    await town.until("08:00")
    await town.call("Aisha", "pass", item="money", units=15, to="Mei")
    for name in world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    assert town.take("Mei")[-1] == (
        "Your statement for Monday 1 January: received $15 from Aisha; rent for your room at the "
        "shared house on Mill Street $20; your purse paid it. You had nothing to eat today. You "
        "are hungry. You are fresh. You are in good health. Your purse holds $115."
    )
    assert town.take("Aisha")[-1].startswith(
        "Your statement for Monday 1 January: gave $15 to Mei; rent for your room at the shared "
        "house on Mill Street $20; your purse paid $5 of it, all it held above the $10 it keeps "
        "for your bread; you owe the other $15, taken from your purse at a later midnight."
    )
    payload = settled(world)["Aisha"]
    assert {key: payload[key] for key in ("rent", "charges", "arrears_before")} == {
        "rent": 20, "charges": 0, "arrears_before": 0,
    }  # fmt: skip
    assert (payload["rent_paid"], payload["arrears"], payload["money"]) == (5, 15, 10)
    assert (payload["salary"], payload["salary_paid"], payload["owed"]) == (0, 0, 0)
    assert "wage" not in town.kinds()
    treasury = world.treasury
    assert treasury.balance == 1000 + 20 + 30 + 5 and treasury.ledger == {}
    assert treasury.yesterday == {"rent": 55} and treasury.arrears == {"Aisha": 15}
    assert world.treasury_told(treasury.yesterday) == (
        "The treasury took in $55 in rent and daily charges and paid out nothing, and holds "
        "$1055. Owing rent their purses could not spare: Aisha $15."
    )  # as the run's log tells the day; a town without a mayor has nobody else told it
    assert total(world) == before  # rent moves money within the town
    # The next day what she owes is taken with the day's rent, as far as her purse spares it.
    town.rest()
    await town.until("08:00", day=2)
    await town.call("Mei", "go", place="park")
    await town.call("Aisha", "go", place="park")
    await town.until("08:20", day=2)
    await town.call("Mei", "pass", item="money", units=30, to="Aisha")
    await town.until("00:00", day=3)
    assert statements(town, "Aisha")[-1].startswith(
        "Your statement for Tuesday 2 January: received $30 from Mei; rent for your room at the "
        "shared house on Mill Street $20; $15 of rent you owed; your purse paid $30 of it, all it "
        "held above the $10 it keeps for your bread; you owe the other $5, taken from your purse "
        "at a later midnight."
    )
    assert world.residents["Aisha"].inventory.money == 10 and treasury.arrears == {"Aisha": 5}


async def test_the_treasury_pays_the_mayors_salary_as_far_as_it_holds_and_owes_the_rest(
    make_town,
):
    town = make_town(town_config(residents=(RESIDENTS[2], CARE[1])))
    await awake_at(town)
    world, treasury = town.world, town.world.treasury
    treasury.balance = 0
    town.rest()
    await town.until("00:00", day=2)
    # Settled last, once Aisha's $20 of rent is in: $20 of the $30 paid, the rest owed, and
    # the rent taken from the purse with the salary in it.
    assert statements(town, "Vera")[-1].startswith(
        "Your statement for Monday 1 January: your salary $30, of which the treasury paid $20 "
        "into your purse and owes you the other $10; rent for your room at the flat by the "
        "college gates $30; your purse paid it."
    )
    assert [e["actor"] for e in world.log.entries() if e["kind"] == "settlement"] == [
        "Aisha", "Vera",
    ]  # fmt: skip
    payload = settled(world)["Vera"]
    assert (payload["salary"], payload["salary_paid"], payload["owed"]) == (30, 20, 10)
    assert payload["money"] == 100 + 20 - 30
    assert (treasury.balance, treasury.owed) == (30, {"Vera": 10})
    assert treasury.yesterday == {"rent": 50, "salary": 20}
    # The mayor's statement ends with the treasury's whole day, his own salary and rent in it.
    assert statements(town, "Vera")[-1].endswith(
        "The treasury took in $50 in rent and daily charges and paid out $20 in salary, and holds "
        "$30. It owes you $10 in salary it could not pay."
    )
    assert "The treasury" not in statements(town, "Aisha")[-1]
    # What it owes is paid with the next salary, as far as it then holds the money.
    treasury.take("tax", 20)  # taxes meanwhile, which account for the balance as they come
    await town.until("00:00", day=3)
    told = statements(town, "Vera")[-1]
    assert told.startswith(
        "Your statement for Tuesday 2 January: your salary $30 and $10 the treasury owed you, "
        "paid into your purse; rent for your room at the flat by the college gates $30; your "
        "purse paid it."
    )
    assert told.endswith(
        "The treasury took in $20 in taxes and $30 in rent and daily charges and paid out $40 in "
        "salary, and holds $40. Owing rent their purses could not spare: Aisha $20."
    )
    assert treasury.owed == {} and treasury.arrears == {"Aisha": 20}  # her purse spares nothing
    assert treasury.balance == 30 + 20 - 40 + 30


async def test_the_mayor_grants_money_from_the_treasury_at_the_hall_for_a_reason(make_town):
    town = make_town(town_config(residents=(*RESIDENTS, CARE[1]), tax=0.1))
    await awake_at(town)
    world, treasury = town.world, town.world.treasury
    before = total(world)
    grant = {"amount": 15, "to": "Mei", "reason": "For the new roof."}
    assert (await town.call("Vera", "grant", **grant)).text == "You can do that only at the hall."
    await town.call("Vera", "go", place="hall")
    await town.until("07:10")
    assert (await town.call("Vera", "grant", **grant | {"to": "Zoe"})).text == (
        "There is nobody called Zoe in the town."
    )
    assert (await town.call("Vera", "grant", **grant | {"reason": " "})).text == (
        "Give the reason for the grant."
    )
    treasury.balance = 14
    assert (await town.call("Vera", "grant", **grant)).text == (
        "You sat down to work. It is 07:10. The treasury holds only $14."
    )
    treasury.balance = 1000
    town.take("Mei")
    assert (await town.call("Vera", "grant", **grant)).text == (
        "You granted Mei $15 from the treasury: “For the new roof.” The treasury holds $985."
    )
    assert town.take("Mei") == ["Vera granted you $15 from the treasury: “For the new roof.”"]
    assert world.residents["Mei"].inventory.money == 135  # a grant is not taxed
    await town.call("Vera", "grant", amount=5, to="Vera", reason="Stamps for the Hall.")
    granted = [(e["audience"], e["payload"]) for e in world.log.entries() if e["kind"] == "grant"]
    assert granted == [
        (["Mei"], {"to": "Mei", "amount": 15, "reason": "For the new roof.", "treasury": 985}),
        ([], {"to": "Vera", "amount": 5, "reason": "Stamps for the Hall.", "treasury": 980}),
    ]
    assert treasury.ledger == {"grant": 20} and total(world) == before
    for name in world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    assert town.take("Mei")[-1].startswith(
        "Your statement for Monday 1 January: received $15 from the treasury, granted by Vera: "
        "“For the new roof.”; rent for your room"
    )
    assert "and paid out $30 in salary and $20 in grants, and holds" in town.take("Vera")[-1]


async def test_purses_and_the_treasury_change_only_by_the_clients_and_the_supplier(make_town):
    town = make_town(town_config(residents=(*RESIDENTS, *TRADES, *CARE), tax=0.1))
    await awake_at(town)
    world = town.world
    before = total(world)
    for name, place in (("Mei", "workshop"), ("Olga", "store"), ("Jonas", "store")):
        await town.call(name, "go", place=place)
    for name, place in (("Lucia", "clinic"), ("Aisha", "clinic"), ("Vera", "hall")):
        await town.call(name, "go", place=place)
    await town.until("09:00")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    await town.call("Mei", "submit")  # a client pays $50
    await town.call("Olga", "order", item="eggs", quantity=4)  # the supplier is paid $4
    await town.call("Olga", "start_work")
    await town.call("Jonas", "buy", item="vegetables", units=2, for_the_kitchen=True)
    await town.call("Olga", "buy", item="bread")  # her own, for nothing
    await town.call("Lucia", "examine", patient="Aisha")
    await town.call("Vera", "grant", amount=7, to="Aisha", reason="For the doctor's fee.")
    await town.call("Jonas", "go", place="cafe")
    await town.call("Mei", "go", place="cafe")
    await town.until("09:20")
    await town.call("Jonas", "cook", dish="soup", portions=1)
    await town.call("Mei", "buy", item="soup")
    await town.call("Mei", "pass", item="money", units=3, to="Jonas")
    town.rest()
    await town.until("00:00", day=2)  # rent and the salary
    kinds = {e["kind"] for e in world.log.entries()}
    assert {"service", "order", "move", "examination", "grant", "settlement"} <= kinds
    assert world.treasury.yesterday["tax"] > 0 and world.treasury.yesterday["salary"] == 30
    assert total(world) == before + 50 - 4


def test_the_treasury_takes_and_pays_only_its_kinds_and_settles_a_midnight():
    treasury = Treasury(40)
    treasury.take("tax", 5)
    with pytest.raises(ValueError, match="takes no 'client'"):
        treasury.take("client", 1)
    with pytest.raises(ValueError, match="pays no 'wage'"):
        treasury.pay("wage", 1)
    with pytest.raises(ValueError, match="holds only 45 to pay 46"):
        treasury.pay("grant", 46)
    # The salary first, as far as the treasury holds it; then the rent from the purse, salary
    # included, above what it spares.
    done = treasury.settle("Vera", purse=4, spares=10, salary=60, rent=30, charges=5)
    assert (done.salary_paid, done.owed, done.rent_paid, done.arrears) == (45, 15, 35, 0)
    assert (treasury.balance, treasury.owed) == (35, {"Vera": 15})
    done = treasury.settle("Mei", purse=25, spares=10, salary=0, rent=20, charges=0)
    assert (done.rent_paid, done.arrears) == (15, 5) and treasury.arrears == {"Mei": 5}
    done = treasury.settle("Mei", purse=8, spares=10, salary=0, rent=20, charges=0)
    assert (done.arrears_before, done.rent_paid, done.arrears) == (5, 0, 25)
    assert treasury.ledger == {"tax": 5, "salary": 45, "rent": 50}
    treasury.close_day()
    assert treasury.ledger == {} and treasury.yesterday["rent"] == 50


def test_a_purse_records_what_goes_in_and_out_and_is_never_spent_below_nothing():
    purse = Inventory(money=10)
    purse.receive(5, "received", "Mei")
    purse.spend(15, "bought", "a coat")
    assert (purse.money, purse.moves) == (0, [["received", 5, "Mei"], ["bought", 15, "a coat"]])
    with pytest.raises(ValueError, match="only 0 in the purse"):
        purse.spend(1, "gave", "Mei")
    assert (purse.money, len(purse.moves)) == (0, 2)


async def test_money_goes_to_anyone_awake_here_and_only_from_what_one_has(make_town):
    town = make_town()
    await awake_at(town)
    gift = await town.call("Mei", "pass", item="money", units=5, to="Tomas")
    assert gift.text == "Tomas is not here."
    assert (await town.call("Mei", "pass", item="money", units=5, to="Mei")).text == (
        "You cannot pass anything to yourself."
    )
    too_much = await town.call("Aisha", "pass", item="money", units=31, to="Mei")
    assert too_much.text == "You do not have $31. Your purse holds $30."
    assert (await town.call("Aisha", "pass", item="money", units=0, to="Mei")).text == (
        "units must be a whole number of at least 1."
    )
    town.take("Mei")
    given = await town.call("Aisha", "pass", item="money", units=10, to="Mei")  # no word said
    assert given.text == "You passed Mei $10. Your purse holds $20."
    assert town.take("Mei") == ["Aisha passed you $10."]
    assert not town.world.ports["Mei"].interrupt.is_set()
    assert town.world.residents["Mei"].inventory.money == 130
    moved = [e["payload"] for e in town.world.log.entries() if e["kind"] == "move"]
    assert moved == [
        {"item": None, "units": 0, "source": "Aisha", "target": "Mei", "money": 10,
         "reason": "pass", "seller": None, "tax": 0},
    ]  # fmt: skip
    await town.until("21:00")
    await town.call("Mei", "sleep", until="07:00")
    asleep = await town.call("Aisha", "pass", item="money", units=1, to="Mei")
    assert asleep.text == "Mei is asleep."


async def test_a_thing_goes_with_its_daily_charge_and_a_stock_feeds_whom_it_is_given(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei, aisha = world.residents["Mei"], world.residents["Aisha"]
    mei.inventory.items.update({"bread": 6, "phone": 1})
    assert (await town.call("Aisha", "pass", item="phone", to="Mei")).text == ("You have no phone.")
    assert (await town.call("Mei", "pass", item="phone", units=2, to="Aisha")).text == (
        "You have only a phone."
    )
    assert (await town.call("Mei", "pass", item="bread", units=7, to="Aisha")).text == (
        "You have only 6 helpings of bread."
    )
    given = await town.call("Mei", "pass", item="phone", to="Aisha")
    assert given.text == "You passed Aisha a phone. You have 6 helpings of bread."
    assert "phone" not in mei.inventory.items and aisha.inventory.items["phone"] == 1
    aisha.inventory.items["coat"] = 1
    assert (await town.call("Mei", "get", item="coat")).text == "You find no coat here."
    town.take("Aisha")
    aisha.living.satiety = 30  # hungry: she eats what she is given
    given = await town.call("Mei", "pass", item="bread", units=2, to="Aisha")
    assert given.text == "You passed Aisha 2 helpings of bread. You have 4 helpings of bread."
    assert "bread" not in aisha.inventory.items and aisha.living.eaten == {"bread": 2}
    assert town.take("Aisha") == ["Mei passed you 2 helpings of bread.", "You are well fed."]
    moved = [
        (e["payload"]["reason"], e["payload"]["item"], e["payload"]["units"], e["audience"])
        for e in world.log.entries()
        if e["kind"] == "move"
    ]
    assert moved == [
        ("pass", "phone", 1, ["Aisha"]),
        ("pass", "bread", 2, ["Aisha"]),
        ("eat", "bread", 1, []),  # the body eats, a helping at a time, as it is hungry
        ("eat", "bread", 1, []),
    ]
    town.rest()
    await town.until("00:00", day=2)  # the phone's daily charge is now Aisha's
    charges = {name: payload["charges"] for name, payload in settled(world).items()}
    assert charges == {"Mei": 0, "Tomas": 0, "Aisha": 2}
