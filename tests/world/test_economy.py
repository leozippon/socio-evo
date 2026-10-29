"""Money: the inventory and the fund. Hours at work and the sums per task paid by the fund, to
the programmer who handed it in and to the team leader, wages at midnight with the tax and the
rent taken out of them, the tax account that alone pays the mayor, what the wages do not cover
owed to the fund and what the fund cannot pay owed to the resident, the statement and the fund's
report, and money and things handed over. The sales, the dishes and the supplier are in
test_shops."""

from __future__ import annotations

import pytest

from tests.world.conftest import CARE, RESIDENTS, awake_at, town_config
from world.economy import Fund, Inventory

OWED = "you owe it, and it is taken from your next wages"


def statements(town, name: str) -> list[str]:
    """The statements `name` was told while its runtime rested."""
    return [p.text for p in town.heard[name] if p.kind == "settlement"]


def total(world) -> int:
    """The town's money: the fund and every purse."""
    fund = world.fund
    return fund.balance + fund.taxes + sum(r.inventory.money for r in world.residents.values())


async def test_wages_for_the_hours_at_work_are_paid_at_midnight_with_the_rent_taken_out(
    make_town,
):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei = world.residents["Mei"]
    before = total(world)
    for name in ("Mei", "Tomas", "Aisha"):
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    await town.call("Mei", "claim_task", task=1)  # she sits down to work at 09:00
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    assert (await town.call("Mei", "submit")).text == (
        "Accepted. You received $20 for task 1. Your purse holds $140. It is 09:00."
    )
    await town.call("Aisha", "say", text="Could you spare some money?")  # Mei works on
    await town.call("Mei", "pass", item="money", units=15, to="Aisha")
    await town.until("12:00")
    await town.call("Tomas", "say", text="Lunch?", to=["Mei"])  # a talk at her desk...
    await town.until("12:30")
    await town.call("Mei", "leave_conversation")  # ...counts as her time at work
    await town.until("17:00")
    await town.call("Mei", "leave_work")
    assert mei.worked == 8 * 3600
    for name in world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    assert town.take("Mei")[-1] == (
        "Your statement for Monday 1 January: received $20 for task 1; gave $15 to Aisha; 8 hours "
        "at work, $56 in wages; rent for your room at the shared house on Mill Street $20; $36 "
        "left of your wages, paid into your purse. You had nothing to eat today. You are hungry. "
        "You are tired. You are in good health. Your purse holds $161."
    )
    assert town.take("Aisha")[-1] == (
        "Your statement for Monday 1 January: received $15 from Mei; no time at work; rent for "
        "your room at the shared house on Mill Street $20; your wages fell $20 short of that; "
        f"{OWED}. You had nothing to eat today. You are hungry. You are fresh. You are in good "
        "health. Your purse holds $45."
    )
    paid = {e["actor"]: e for e in world.log.entries() if e["kind"] == "wage"}
    assert paid["Mei"]["payload"] == {
        "hours": 8.0, "wages": 56, "tax": 0, "tax_from_purse": 0, "owed_before": 0, "rent": 20,
        "charges": 0,
        "arrears_before": 0, "remainder": 36, "paid": 36, "owed": 0, "arrears": 0, "money": 161,
    }  # fmt: skip
    assert paid["Mei"]["text"] == "Mei was paid $36 at midnight."
    assert paid["Mei"]["personal"] == {
        "Mei": "At midnight your purse held $125, and $36 of your wages went into it."
    }
    assert paid["Mei"]["audience"] == []  # the statement tells it
    assert paid["Tomas"]["payload"]["arrears"] == 30 and mei.worked == 0
    # The client's payment is the only money that came into the town; the rest moved between
    # the fund and the residents.
    assert total(world) == before + 50
    assert world.fund.balance == 1000 + 50 - 20 - 36
    assert world.fund.ledger == {}
    assert world.fund.yesterday == {"client": 50, "service": 20, "rent": 20, "wage": 56}
    assert world.fund.arrears == {"Tomas": 30, "Aisha": 20} and world.fund.owed == {}
    assert world.fund_report() == (
        "The fund holds $994. Yesterday it took in $50 from clients and $20 in rent and daily "
        "charges and paid out $56 in wages and $20 in sums for services. Its tax account holds "
        "$0; yesterday it took in $0 in taxes and paid out $0 in wages. Owing rent the wages did "
        "not cover: Tomas $30 and Aisha $20."
    )

    # The next day Aisha works, and the rent she owed is taken from her wages with the day's.
    town.rest()
    await town.until("07:00", day=2)
    await town.call("Aisha", "go", place="workshop")
    await town.until("09:00", day=2)
    await town.call("Aisha", "claim_task", task=2)
    await town.until("17:00", day=2)
    await town.call("Aisha", "leave_work")
    await town.until("00:00", day=3)
    assert statements(town, "Aisha")[-1].startswith(
        "Your statement for Tuesday 2 January: 8 hours at work, $56 in wages; rent for your room "
        "at the shared house on Mill Street $20; $20 of rent you owed; $16 left of your wages, "
        "paid into your purse."
    )
    assert world.residents["Aisha"].inventory.money == 45 + 16
    assert world.fund.arrears == {"Mei": 20, "Tomas": 60}


async def test_a_fund_that_runs_short_pays_what_it_has_and_owes_the_rest(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    for name in ("Mei", "Aisha"):
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    for task, name in enumerate(("Mei", "Aisha"), 1):
        await town.call(name, "claim_task", task=task)
    await town.until("17:00")
    for name in ("Mei", "Aisha"):
        await town.call(name, "leave_work")
        town.take(name)
    world.fund.balance = 20
    await town.until("00:00", day=2)
    # Mei is settled first and paid what the fund has; Aisha's wages are owed to her whole.
    assert town.take("Mei")[-1].startswith(
        "Your statement for Monday 1 January: 8 hours at work, $56 in wages; rent for your room "
        "at the shared house on Mill Street $20; $36 left of your wages, of which $20 paid into "
        "your purse; the fund could not pay the other $16 and owes it to you."
    )
    assert town.take("Aisha")[-1].startswith(
        "Your statement for Monday 1 January: 8 hours at work, $56 in wages; rent for your room "
        "at the shared house on Mill Street $20; $36 left of your wages, which the fund could "
        "not pay and owes you."
    )
    assert world.fund.balance == 0
    assert world.fund_report() == (
        "The fund holds $0. Yesterday it took in $40 in rent and daily charges and paid out $60 "
        "in wages. Its tax account holds $0; yesterday it took in $0 in taxes and paid out $0 in "
        "wages. It owes in wages it could not pay: Mei $16 and Aisha $36. Owing rent the wages "
        "did not cover: Tomas $30."
    )
    # What the fund owes is paid with the next wages, as far as it has the money then.
    town.rest()
    await town.until("07:00", day=2)
    world.fund.take("client", 12)  # a client's payment meanwhile
    await town.until("00:00", day=3)
    assert statements(town, "Mei")[-1].startswith(
        "Your statement for Tuesday 2 January: no time at work; $16 the fund owed you; rent for "
        "your room at the shared house on Mill Street $20; your wages fell $4 short of that; "
        f"{OWED}."
    )
    assert statements(town, "Aisha")[-1].startswith(
        "Your statement for Tuesday 2 January: no time at work; $36 the fund owed you; rent for "
        "your room at the shared house on Mill Street $20; $16 left of your wages, of which $12 "
        "paid into your purse; the fund could not pay the other $4 and owes it to you."
    )
    assert world.fund.balance == 0
    assert world.fund.owed == {"Aisha": 4} and world.fund.arrears == {"Tomas": 60, "Mei": 4}


async def test_everyone_pays_a_tenth_into_the_tax_account_which_alone_pays_the_mayor(make_town):
    town = make_town(town_config(residents=(*RESIDENTS, CARE[1]), tax=0.1))
    await awake_at(town)
    world = town.world
    before = total(world)
    for name, place in (("Mei", "workshop"), ("Tomas", "workshop"), ("Vera", "hall")):
        await town.call(name, "go", place=place)
    await town.until("09:00")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Tomas", "claim_task", task=2)
    await town.call("Vera", "start_work")
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    await town.call("Mei", "submit")  # accepted: $20 for her task
    await town.until("17:00")
    for name in ("Mei", "Tomas", "Vera"):
        await town.call(name, "leave_work")
    for name in world.residents:
        town.take(name)
    await town.until("00:00", day=2)
    # A tenth of $56 in wages and the $20 sum, to the nearest dollar, comes out of the wages.
    assert town.take("Mei")[-1].startswith(
        "Your statement for Monday 1 January: received $20 for task 1; 8 hours at work, $56 in "
        "wages; tax on the day's earnings $8; rent for your room at the shared house on Mill "
        "Street $20; $28 left of your wages, paid into your purse."
    )
    # The mayor is settled last, from the $8 and $6 the day's taxes put in the account: it
    # pays them towards her rent of $30, keeps her own tax and owes her the rest of her wages.
    assert town.take("Vera")[-1].startswith(
        "Your statement for Monday 1 January: 8 hours at work, $64 in wages; tax on the day's "
        "earnings $6; rent for your room at the flat by the college gates $30; the tax account "
        "could not pay $44 of your wages and owes it to you, and what it paid fell $16 short of "
        "that; you owe it, and it is taken from your next wages."
    )
    assert [e["actor"] for e in world.log.entries() if e["kind"] == "wage"][-1] == "Vera"
    fund = world.fund
    assert (fund.taxes, fund.owed, fund.arrears) == (0, {"Vera": 44}, {"Aisha": 20, "Vera": 16})
    assert fund.balance == 1000 + 50 - 20 - 8 - 28 - 6 - 20 + 14
    assert total(world) == before + 50  # the account's money is the town's like any other
    assert world.fund_report() == (
        "The fund holds $982. Yesterday it took in $50 from clients and $64 in rent and daily "
        "charges and paid out $112 in wages and $20 in sums for services. Its tax account holds "
        "$0; yesterday it took in $20 in taxes and paid out $20 in wages. It owes in wages it "
        "could not pay: Vera $44. Owing rent the wages did not cover: Aisha $20 and Vera $16."
    )


async def test_the_tax_on_sums_without_wages_comes_from_the_purse_or_is_owed(make_town):
    leader = dict(RESIDENTS[1], occupation="team-leader")
    town = make_town(town_config(residents=(RESIDENTS[0], leader, RESIDENTS[2]), tax=0.1))
    await awake_at(town)
    world = town.world
    for name in ("Mei", "Tomas", "Aisha"):
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    await town.call("Mei", "submit")  # Tomas, the leader, is paid $10 without sitting down
    await town.call("Tomas", "pass", item="money", units=190, to="Aisha")  # all he has
    await town.call("Aisha", "pass", item="money", units=5, to="Mei")
    await town.until("09:10")
    await town.call("Mei", "leave_work")  # ten minutes' wages, $1, short of her $3 of tax
    for name in world.residents:
        town.take(name)
    before = total(world)
    await town.until("00:00", day=2)
    assert town.take("Tomas")[-1].startswith(
        "Your statement for Monday 1 January: received $10 for task 1, which Mei handed in; gave "
        "$190 to Aisha; no time at work; tax on the day's earnings $1; rent for your room at the "
        "flat by the college gates $30; your wages fell $31 short of that; you owe it, and it is "
        "taken from your next wages."
    )
    assert town.take("Mei")[-1].startswith(
        "Your statement for Monday 1 January: received $20 for task 1; received $5 from Aisha; "
        "10 minutes at work, $1 in wages; tax on the day's earnings $2, $1 of it from your purse; "
        "rent for your room at the shared house on Mill Street $20; your wages fell $20 short of "
        "that; you owe it, and it is taken from your next wages."
    )
    paid = {e["actor"]: e for e in world.log.entries() if e["kind"] == "wage"}
    assert paid["Mei"]["personal"]["Mei"] == (
        "At midnight your purse held $145, and $1 of it went in tax."
    )
    assert world.residents["Mei"].inventory.money == 144
    assert world.fund.taxes == 1 + 1 and world.fund.arrears["Tomas"] == 31
    assert total(world) == before


async def test_the_team_leader_is_paid_for_the_teams_tasks_and_her_own_as_a_programmer(make_town):
    leader = dict(RESIDENTS[1], occupation="team-leader")
    town = make_town(town_config(residents=(RESIDENTS[0], leader, RESIDENTS[2])))
    await awake_at(town)
    world = town.world
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("09:00")
    for name, task in (("Mei", 1), ("Tomas", 2)):
        await town.call(name, "claim_task", task=task)
        await town.call(name, "write_repo_file", path="fix.py", content="FIX\n")
        town.take("Tomas")
    assert (await town.call("Mei", "submit")).text == (
        "Accepted. You received $20 for task 1. Your purse holds $140. It is 09:00."
    )
    assert town.take("Tomas") == ["You received $10 for task 1, which Mei handed in."]
    assert (await town.call("Tomas", "submit")).text == (  # her own: the programmer's sum
        "Accepted. You received $20 for task 2. Your purse holds $210. It is 09:00."
    )
    paid = [(e["actor"], e["payload"]) for e in world.log.entries() if e["kind"] == "service"]
    assert paid == [
        ("Mei", {"for": "task", "task": 1, "amount": 20, "paid": 20, "owed": 0, "money": 140}),
        ("Tomas", {"for": "team", "task": 1, "amount": 10, "paid": 10, "owed": 0, "money": 190}),
        ("Tomas", {"for": "task", "task": 2, "amount": 20, "paid": 20, "owed": 0, "money": 210}),
    ]
    assert world.fund.ledger == {"client": 100, "service": 50}


def test_the_fund_pays_what_it_has_and_keeps_its_ledger_by_kind():
    fund = Fund(30)
    fund.take("client", 50)
    assert fund.service("Mei", 20) == 20 and fund.balance == 60
    assert fund.service("Mei", 100) == 60 and fund.owed == {"Mei": 40} and fund.balance == 0
    by_fund = {"tax": 0, "purse": 0, "from_taxes": False}
    settled = fund.settle("Mei", wages=56, rent=20, charges=5, **by_fund)  # 40 + 56 - 25 owed
    assert (settled.owed_before, settled.remainder, settled.paid, settled.owed) == (40, 71, 0, 71)
    assert fund.ledger == {"client": 50, "service": 80, "rent": 25, "wage": 25}
    settled = fund.settle("Tomas", wages=0, rent=30, charges=0, **by_fund)
    assert (settled.remainder, settled.arrears) == (-30, 30) and fund.arrears == {"Tomas": 30}
    fund.take("sale", 12)
    settled = fund.settle("Tomas", wages=70, rent=30, charges=0, **by_fund)
    assert (settled.arrears_before, settled.remainder, settled.paid) == (30, 10, 10)
    assert fund.arrears == {} and fund.balance == 2
    fund.close_day()
    assert fund.ledger == {} and fund.yesterday["rent"] == 25 + 60


def test_the_tax_account_takes_the_tax_from_the_wages_and_pays_only_what_it_holds():
    fund = Fund(100)
    by_fund = {"charges": 0, "from_taxes": False}
    # The tax comes out of the wages before the rent, into the account, from the fund's money.
    settled = fund.settle("Mei", wages=56, tax=6, purse=10, rent=20, **by_fund)
    assert (settled.tax, settled.tax_from_purse, settled.remainder, settled.paid) == (6, 0, 30, 30)
    assert (fund.balance, fund.taxes) == (100 - 6 - 30, 6)
    # On sums without wages, the tax comes from the purse, and what the purse lacks is owed
    # with the rent.
    settled = fund.settle("Ravi", wages=0, tax=1, purse=99, rent=20, **by_fund)
    assert (settled.tax_from_purse, settled.remainder, settled.arrears) == (1, -20, 20)
    settled = fund.settle("Aisha", wages=2, tax=5, purse=1, rent=20, **by_fund)
    assert (settled.tax_from_purse, settled.remainder, settled.arrears) == (1, -22, 22)
    assert fund.taxes == 6 + 1 + 2 + 1
    # The mayor's wages come from the account alone: his own tax stays in it, what it pays
    # covers his rent first, and what it lacks it owes him; the fund's money is not touched.
    settled = fund.settle("Vera", wages=64, tax=6, purse=0, rent=8, charges=0, from_taxes=True)
    assert (settled.tax, settled.remainder, settled.paid, settled.owed) == (6, 50, 2, 48)
    assert (fund.balance, fund.taxes, fund.owed) == (100 - 6 - 30 - 2 + 8, 0, {"Vera": 48})
    # Short even of the rent, it leaves both: wages owed to her and rent she owes.
    settled = fund.settle("Vera", wages=0, tax=0, purse=0, rent=30, charges=0, from_taxes=True)
    assert (settled.owed_before, settled.owed, settled.arrears) == (48, 48, 30)
    assert fund.ledger == {
        "wage": 6 + 30 + 20 + 2, "tax": 6 + 1 + 3 + 6, "rent": 20 + 8, "tax_wage": 6 + 8 + 2,
    }  # fmt: skip
    for refused in (lambda: fund.take("wage", 1), lambda: fund.pay("rent", 1)):
        try:
            refused()
        except ValueError:
            continue
        raise AssertionError("a movement of the wrong kind was taken")


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
         "reason": "pass", "seller": None},
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
    charges = {
        e["actor"]: e["payload"]["charges"] for e in world.log.entries() if e["kind"] == "wage"
    }
    assert charges == {"Mei": 0, "Tomas": 0, "Aisha": 2}
