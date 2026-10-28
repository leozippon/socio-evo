"""Money: the inventory and the fund. Hours at work and the sums per task paid by the fund, to
the programmer who handed it in and to the team leader, wages at midnight with the rent taken
out of them, what the wages do not cover owed to the fund and what the fund cannot pay owed to
the resident, the statement and the fund's report, and money and things handed over. The sales,
the dishes and the supplier are in test_shops."""

from __future__ import annotations

from tests.world.conftest import RESIDENTS, awake_at, town_config
from world.economy import Fund

OWED = "you owe it, and it is taken from your next wages"


def statements(town, name: str) -> list[str]:
    """The statements `name` was told while its runtime rested."""
    return [p.text for p in town.heard[name] if p.kind == "settlement"]


def total(world) -> int:
    """The town's money: the fund and every purse."""
    return world.fund.balance + sum(r.inventory.money for r in world.residents.values())


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
    await town.call("Mei", "give", to="Aisha", what="money", amount=15)
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
        "hours": 8.0, "wages": 56, "owed_before": 0, "rent": 20, "charges": 0,
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
        "charges and paid out $56 in wages and $20 in sums for services. Owing rent the wages "
        "did not cover: Tomas $30 and Aisha $20."
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
        "in wages. It owes in wages it could not pay: Mei $16 and Aisha $36. Owing rent the "
        "wages did not cover: Tomas $30."
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
    settled = fund.settle("Mei", wages=56, rent=20, charges=5)  # 40 owed + 56 - 25: 71 owed
    assert (settled.owed_before, settled.remainder, settled.paid, settled.owed) == (40, 71, 0, 71)
    assert fund.ledger == {"client": 50, "service": 80, "rent": 25, "wage": 25}
    settled = fund.settle("Tomas", wages=0, rent=30, charges=0)
    assert (settled.remainder, settled.arrears) == (-30, 30) and fund.arrears == {"Tomas": 30}
    fund.take("sale", 12)
    settled = fund.settle("Tomas", wages=70, rent=30, charges=0)
    assert (settled.arrears_before, settled.remainder, settled.paid) == (30, 10, 10)
    assert fund.arrears == {} and fund.balance == 2
    fund.close_day()
    assert fund.ledger == {} and fund.yesterday["rent"] == 25 + 60
    for refused in (lambda: fund.take("wage", 1), lambda: fund.pay("rent", 1)):
        try:
            refused()
        except ValueError:
            continue
        raise AssertionError("a movement of the wrong kind was taken")


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
    assert town.world.residents["Mei"].inventory.money == 130
    await town.until("21:00")
    await town.call("Mei", "sleep", until="07:00")
    asleep = await town.call("Aisha", "give", to="Mei", what="money", amount=1)
    assert asleep.text == "Mei is asleep."


async def test_a_thing_goes_with_its_daily_charge_and_a_stock_feeds_whom_it_is_given(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei, aisha = world.residents["Mei"], world.residents["Aisha"]
    mei.inventory.items.update({"bread": 6, "phone": 1})
    assert (await town.call("Aisha", "give", to="Mei", what="phone", amount=1)).text == (
        "You have no phone."
    )
    assert (await town.call("Mei", "give", to="Aisha", what="phone", amount=2)).text == (
        "You have one phone to give."
    )
    assert (await town.call("Mei", "give", to="Aisha", what="bread", amount=7)).text == (
        "You have only 6 helpings of bread."
    )
    given = await town.call("Mei", "give", to="Aisha", what="phone", amount=1)
    assert given.text == "You gave Aisha a phone. You have 6 helpings of bread."
    assert "phone" not in mei.inventory.items and aisha.inventory.items["phone"] == 1
    town.take("Aisha")
    aisha.living.satiety = 30  # hungry: she eats what she is given
    given = await town.call("Mei", "give", to="Aisha", what="bread", amount=2)
    assert given.text == "You gave Aisha 2 helpings of bread. You have 4 helpings of bread."
    assert "bread" not in aisha.inventory.items and aisha.living.eaten == {"bread": 2}
    assert town.take("Aisha") == ["Mei gave you 2 helpings of bread.", "You are well fed."]
    gifts = [e["payload"] for e in world.log.entries() if e["kind"] == "gift"]
    assert gifts == [
        {"to": "Aisha", "item": "phone", "name": "a phone", "quantity": 1},
        {"to": "Aisha", "item": "bread", "name": "bread", "quantity": 2},
    ]
    town.rest()
    await town.until("00:00", day=2)  # the phone's daily charge is now Aisha's
    charges = {
        e["actor"]: e["payload"]["charges"] for e in world.log.entries() if e["kind"] == "wage"
    }
    assert charges == {"Mei": 0, "Tomas": 0, "Aisha": 2}
