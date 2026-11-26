"""Money: the inventory and the town's treasury. A client's payment shared between the one who
handed the task in and the team leader, a tenth withheld into the treasury at receipt; the rent
taken at midnight from the purse above a day's bread, the rest owed and taken later; the mayor's
salary paid as far as the treasury holds and the rest owed; the mayor's grants; the statement,
and the treasury's day in the mayor's; a thing's daily charge, which goes with the thing; and the
invariant that the town's money changes only by what clients pay and the supplier is paid. Money
taken, given and left, and the tax on what is given to one at work, are in test_things; the Store
and the kitchen in test_shops."""

from __future__ import annotations

import pytest

from tests.support.towns import CARE, RESIDENTS, TRADES, awake_at, town_config
from tests.world.acts import give, take
from tests.world.acts import money as total
from world.economy import Holder, Inventory, Treasury

LEADER = dict(RESIDENTS[1], occupation="team-leader")
"""Tomas as the team leader."""


def statements(town, name: str) -> list[str]:
    """The statements `name` was told while its runtime rested."""
    return [p.text for p in town.heard[name] if p.kind == "settlement"]


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
    for name in ("Mei", "Tomas", "Aisha"):
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    # The team leader takes no task: she hands them out.
    assert (await town.call("Tomas", "claim_task", task=3)).text == (
        "That is not your work: you are the team leader."
    )
    for name, task in (("Mei", 1), ("Aisha", 2)):
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
    assert (await town.call("Aisha", "submit")).text == (
        "Accepted. You received $40 for task 2, of which $4 in tax. Your purse holds $66. It is "
        "09:00."
    )
    paid = [(e["actor"], e["payload"]) for e in world.log.entries() if e["kind"] == "service"]
    assert paid == [
        ("Mei", {"for": "task", "task": 1, "amount": 40, "tax": 4, "money": 156}),
        ("Tomas", {"for": "team", "task": 1, "amount": 10, "tax": 1, "money": 189}),
        ("Aisha", {"for": "task", "task": 2, "amount": 40, "tax": 4, "money": 66}),
        ("Tomas", {"for": "team", "task": 2, "amount": 10, "tax": 1, "money": 198}),
    ]
    assert world.treasury.ledger == {"tax": 10} and world.treasury.balance == 1010
    assert total(world) == before + 100  # the clients' payments, and nothing else, came in
    # The statement sums what was earned, with the tax withheld.
    for name in world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    assert town.take("Tomas")[-1].startswith(
        "Your statement for Monday 1 January: received $10 for task 1, handed in by Mei, $1 of "
        "it in tax; received $10 for task 2, handed in by Aisha, $1 of it in tax; rent for your "
        "room at the flat by the college gates $30; your purse paid it."
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
    await give(town, "Aisha", "money", "Mei", 15)
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
    await give(town, "Mei", "money", "Aisha", 30)
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
    await take(town, "Jonas", "vegetables", "shelves", 4)
    await give(town, "Jonas", "money", "Olga", 12)  # of which $1 in tax
    await give(town, "Jonas", "money", "here", 2)  # left at the store, and still the town's
    await take(town, "Olga", "bread", "shelves")  # her own
    await town.call("Vera", "grant", amount=7, to="Aisha", reason="For the doctor's fee.")
    await town.call("Lucia", "examine", patient="Aisha")
    await give(town, "Aisha", "money", "Lucia", 10)  # the fee, of which $1 in tax
    await town.call("Jonas", "go", place="cafe")
    await town.call("Mei", "go", place="cafe")
    await town.until("09:20")
    await town.call("Jonas", "cook", dish="soup", portions=2)
    await take(town, "Mei", "soup", "counter")
    await take(town, "Mei", "money", "Jonas", 3)
    town.rest()
    await town.until("00:00", day=2)  # rent and the salary
    kinds = {e["kind"] for e in world.log.entries()}
    assert {"service", "order", "move", "examination", "grant", "settlement"} <= kinds
    # The client's payment, the chef's and the patient's gifts taxed; Aisha's purse $3 short.
    assert world.treasury.yesterday == {"tax": 5 + 1 + 1, "rent": 187, "salary": 30, "grant": 7}
    assert world.holders["store"].money == 2
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


def test_a_purse_records_what_goes_in_and_out_and_no_holder_is_spent_below_nothing():
    purse = Inventory(money=10)
    purse.receive(5, "received", "Mei")
    purse.spend(15, "gave", "Olga")
    assert (purse.money, purse.moves) == (0, [["received", 5, "Mei"], ["gave", 15, "Olga"]])
    with pytest.raises(ValueError, match="only 0 held to spend 1 from"):
        purse.spend(1, "gave", "Mei")
    assert (purse.money, len(purse.moves)) == (0, 2)
    shelf = Holder(money=3)  # what is left on a shelf or at a place is money like any other
    shelf.receive(4, "left", "on the shelves")
    shelf.spend(7, "took", "from the shelves")
    with pytest.raises(ValueError, match="only 0 held"):
        shelf.spend(1, "took", "from the shelves")
    assert shelf.money == 0 and shelf.has("money") == 0


async def test_a_whole_number_written_in_digits_is_taken_as_the_number(make_town):
    town = make_town()
    await awake_at(town)
    given = await town.call("Aisha", "give", what="money", amount="10", to="Mei")
    assert given.text == "You gave Mei $10. Your purse holds $20."
    for wrong in ("ten", "2.5", "-3", "0", " 4", True):
        assert (await town.call("Aisha", "give", what="money", amount=wrong, to="Mei")).text == (
            "amount must be a whole number of at least 1."
        )
    assert (await town.call("Tomas", "wait", minutes="45")).text == "You wait for up to 45 minutes."
    assert town.world.residents["Tomas"].wait_minutes == 45


async def test_a_thing_goes_with_its_daily_charge_to_whoever_carries_it_at_midnight(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei, aisha = world.residents["Mei"], world.residents["Aisha"]
    mei.inventory.items.update({"bread": 9, "phone": 2})
    aisha.inventory.items["bread"] = 9
    assert (await town.call("Mei", "inventory")).text == (
        "Money: $120.\nBread: 9 helpings.\n2 phones, with a daily charge of $2."
    )
    assert await give(town, "Mei", "phone", "Aisha", 2) == (
        "You gave Aisha 2 phones. You carry 9 helpings of bread."
    )
    assert await take(town, "Mei", "phone", "Aisha") == (
        "You took a phone from Aisha. You carry 9 helpings of bread and a phone."
    )
    town.rest()
    await town.until("00:00", day=2)  # each carries one: the charge is on the kind of thing
    charges = {name: payload["charges"] for name, payload in settled(world).items()}
    assert charges == {"Mei": 2, "Tomas": 0, "Aisha": 2}
    assert "the daily charge on a phone $2" in statements(town, "Aisha")[-1]
