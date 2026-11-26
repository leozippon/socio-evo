"""The Hospital and the Town Hall: the doctor's examination and treatment, at the surgery and at
the bedside of one too ill to get up, which charge nobody, the fee the doctor sets being told to
both and given by the patient or not, taxed as money given to one at work; the treasury's day in
the mayor's statement, and announcements told to everyone, kept on the hall's board and by the
checkpoint. The mayor's grants are in test_economy."""

from __future__ import annotations

import json

from tests.support.towns import (
    CARE,
    RESIDENTS,
    TRADES,
    at,
    awake_at,
    make_agent_dirs,
    stocked,
    town_config,
)
from tests.world.acts import give, take
from world.clock import DAY, ManualClock
from world.events import EXHAUSTED, Idle, Sleep, Work
from world.testing import FakeBackend
from world.world import World

TOWN = town_config(residents=RESIDENTS + TRADES + CARE, tax=0.1)


def offered(town, name: str) -> list[str]:
    return [spec.name for spec in town.world.ports[name].tool_specs()]


async def test_the_doctor_examines_and_treats_and_nothing_charges_the_patient(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    mei, lucia = world.residents["Mei"], world.residents["Lucia"]
    assert "examine" not in offered(town, "Lucia")  # her work is at the clinic
    assert (await town.call("Lucia", "examine", patient="Mei")).text == (
        "You can do that at the clinic, or at the bedside of one too ill to get up."
    )
    for name in ("Mei", "Aisha"):
        await town.call(name, "go", place="clinic")
    await town.until("07:10")
    fees = "An examination costs $10, a treatment $30."
    assert fees in world.ports["Mei"].situation()  # posted, the doctor there or not
    await town.call("Lucia", "go", place="clinic")
    await town.until("07:20")
    assert {"examine", "treat", "set_price", "start_work"} <= set(offered(town, "Lucia"))
    assert (await town.call("Mei", "examine", patient="Aisha")).text == (
        "That is not your work: you are a programmer."
    )
    assert (await town.call("Lucia", "examine", patient="Zoe")).text == (
        "There is nobody called Zoe in the town."
    )
    assert (await town.call("Lucia", "examine", patient="Tomas")).text == (
        "You sat down to work. It is 07:20. Tomas is not here."
    )
    assert isinstance(lucia.base, Work)
    world.body.fall_ill(mei.living)
    mei.living.health = 50
    town.take("Mei")
    examined = (await town.call("Lucia", "examine", patient="Mei")).text
    numbers = (
        "Food: 82 of 100, {who} well fed. Energy: 98 of 100, {who} fresh. Health: 50 of 100, "
        "{who} run down. {Who} ill; untreated, it passes after 7 more nights."
    )
    assert examined == (
        "You examined Mei. The fee posted for an examination is $10. "
        + numbers.format(who="Mei is", Who="Mei is")
    )
    assert town.take("Mei") == [
        "Lucia examined you. The fee posted for an examination is $10. "
        + numbers.format(who="you are", Who="You are")
    ]
    treated = await town.call("Lucia", "treat", patient="Mei")
    assert treated.text == "You treated Mei. The fee posted for a treatment is $30."
    assert town.take("Mei") == [
        "Lucia treated you. The fee posted for a treatment is $30.",
        "Your illness is over.",
    ]
    assert mei.living.health == 75 and mei.living.ill == 0
    # Nothing took the fees: the purses are as they were until the patient gives.
    assert (mei.inventory.money, lucia.inventory.money, world.treasury.ledger) == (120, 100, {})
    entries = {e["kind"]: e for e in world.log.entries()}
    assert entries["examination"]["audience"] == ["Mei"]  # between the two of them
    assert entries["examination"]["payload"] == {
        "patient": "Mei", "fee": 10, "satiety": 81.9, "energy": 98.5, "health": 50.0,
        "ill": 7, "night": {},
    }  # fmt: skip
    assert entries["treatment"]["payload"] == {
        "patient": "Mei", "fee": 30, "restores": 25.0, "before": 50.0, "health": 75.0,
        "ill": 7, "bedridden": False,
    }  # fmt: skip
    assert entries["recovered"]["payload"] == {
        "illness": True, "bedridden": False, "treated": True, "health": 75.0,
    }  # fmt: skip
    # Paying is the patient's own act: money given to the doctor at work, a tenth withheld.
    assert (
        await give(town, "Mei", "money", "Lucia", 40) == "You gave Lucia $40. Your purse holds $80."
    )
    assert town.take("Lucia")[-1] == "Mei gave you $40, of which $4 in tax."
    assert world.treasury.ledger == {"tax": 4} and lucia.inventory.money == 100 + 40 - 4
    # The doctor sets the fees; one who has nothing is seen all the same, and so is the doctor.
    assert (await town.call("Lucia", "set_price", item="examination", price=12)).text == (
        "The price of examination is now $12; it was $10."
    )
    assert (await town.call("Lucia", "set_price", item="bread", price=1)).text == (
        "Bread is not a service of the clinic."
    )
    assert "An examination costs $12, a treatment $30." in world.ports["Aisha"].situation()
    world.residents["Aisha"].inventory.money = 0
    assert (await town.call("Lucia", "examine", patient="Aisha")).text.startswith(
        "You examined Aisha. The fee posted for an examination is $12. Food: "
    )
    assert (await town.call("Lucia", "examine", patient="Lucia")).text.startswith(
        "You examined yourself. The fee posted for an examination is $12. Food: "
    )
    assert lucia.inventory.money == 136
    town.rest()
    await town.until("00:00", day=2)
    statement = [p.text for p in town.heard["Mei"] if p.kind == "settlement"][-1]
    assert statement.startswith("Your statement for Monday 1 January: gave $40 to Lucia; rent")
    statement = [p.text for p in town.heard["Lucia"] if p.kind == "settlement"][-1]
    assert statement.startswith(
        "Your statement for Monday 1 January: received $40 from Mei at work, $4 of it in tax; rent"
    )


async def test_the_doctor_treats_one_too_ill_to_get_up_at_the_bedside(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world = town.world
    mei, lucia = world.residents["Mei"], world.residents["Lucia"]
    mei.living.health, mei.living.satiety = 1, 0
    town.rest("Tomas", "Aisha", "Olga", "Jonas", "Vera", "Mei")
    await town.until("00:00", day=2)
    assert mei.living.bedridden
    await town.call("Lucia", "go", place="mill-street-house")  # up late, she goes to Mei
    await town.until("00:15", day=2)
    assert {"examine", "treat"} <= set(offered(town, "Lucia"))
    assert "start_work" not in offered(town, "Lucia")
    # In bed she can still hand over what she carries, and take what is within her reach.
    assert (
        await give(town, "Mei", "money", "Lucia", 10) == "You gave Lucia $10. Your purse holds $90."
    )
    assert await take(town, "Mei", "money", "Lucia", 10) == (
        "You took $10 from Lucia. Your purse holds $100."
    )
    assert (await town.call("Lucia", "treat", patient="Mei")).text == (
        "You treated Mei. The fee posted for a treatment is $30."
    )
    assert isinstance(lucia.base, Idle) and lucia.worked == 0  # no hours at a bedside
    assert not mei.living.bedridden and isinstance(mei.base, Idle) and mei.living.health == 25
    # The doctor is not at work at a bedside, so what she is given there is hers whole.
    purse = lucia.inventory.money
    await give(town, "Mei", "money", "Lucia", 30)
    assert lucia.inventory.money == purse + 30 and world.treasury.ledger == {}
    await town.call("Lucia", "go", place="college-flat")  # nobody in bed there
    await town.until("00:30", day=2)
    assert "treat" not in offered(town, "Lucia")
    assert (await town.call("Lucia", "treat", patient="Mei")).text == (
        "You can do that at the clinic, or at the bedside of one too ill to get up."
    )


async def test_the_mayors_statement_tells_the_treasurys_day_and_he_announces_at_the_hall(
    make_town, tmp_path
):
    town = make_town(TOWN)
    await awake_at(town)
    stocked(town)
    world = town.world
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    for name in ("Olga", "Aisha"):
        await town.call(name, "go", place="store")
    await town.call("Vera", "go", place="hall")
    await town.until("08:10")
    await town.call("Vera", "start_work")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    await town.call("Mei", "submit")
    await town.call("Tomas", "claim_task", task=3)
    await town.call("Olga", "start_work")
    await take(town, "Aisha", "bread", "shelves", 2)
    await give(town, "Aisha", "money", "Olga", 8)
    await town.until("16:10")
    for name in ("Mei", "Tomas", "Olga", "Vera"):
        await town.call(name, "leave_work")
    town.rest()
    await town.until("09:00", day=2)
    # Settled last, the mayor is told the treasury's whole day with his statement; nobody else is.
    settled = [e for e in world.log.entries() if e["kind"] == "settlement"]
    assert settled[-1]["actor"] == "Vera"
    assert settled[-1]["personal"]["Vera"].endswith(
        "Your purse holds $100. The treasury took in $5 in taxes and $182 in rent and daily "
        "charges and paid out $30 in salary, and holds $1157. Owing rent their purses could not "
        "spare: Aisha $8."
    )
    assert not any("The treasury took in" in e["personal"][e["actor"]] for e in settled[:-1])
    await town.call("Vera", "go", place="hall")
    await town.until("09:15", day=2)
    await town.call("Vera", "start_work")
    # An announcement is told to everyone, asleep or awake, without drawing anyone from what it
    # is doing, and stays on the board at the hall.
    assert (await town.call("Mei", "announce", text="Hello.")).text == (
        "That is not your work: you are a programmer."
    )
    assert (await town.call("Vera", "announce", text=" ")).text == "You announced nothing."
    await town.call("Aisha", "sleep", until="12:00")
    announced = await town.call("Vera", "announce", text="The well is dry; boil your water.")
    assert announced.text == (
        "You announced: “The well is dry; boil your water.” Everyone is told, and it stands on "
        "the board here."
    )
    told = "Vera announced at the hall: “The well is dry; boil your water.”"
    assert [p.text for p in town.heard["Mei"]][-1] == told
    assert not world.ports["Mei"].interrupt.is_set()
    assert world.ports["Aisha"].held and world.ports["Aisha"].held[-1].text == told
    assert (await town.call("Vera", "look_around")).text.endswith(
        "On the board, the mayor's announcements:\n"
        "Tuesday 2 January, 09:15: “The well is dry; boil your water.”"
    )
    # The mayor's duty runs on wherever she goes, until she stops; her work is done at the hall.
    vera = world.residents["Vera"]
    went = await town.call("Vera", "go", place="park")
    assert went.text == "You set off for the park and will arrive at 09:25."
    assert world.on_duty(vera) and world.activity(vera) == "walk"
    await town.until("09:30", day=2)
    assert isinstance(vera.base, Work) and vera.place == "park"
    assert (
        world.ports["Vera"]
        .situation()
        .startswith("Tuesday 2 January, 09:30. You are at the park, at work.")
    )
    assert (await town.call("Vera", "announce", text="Market day.")).text == (
        "You can do that only at the hall."
    )
    assert (await town.call("Vera", "leave_work")).text == "You stopped work. It is 09:30."
    assert vera.worked == 15 * 60  # from 09:15 at the hall, on the way and at the park
    await town.call("Vera", "how_am_i")  # the body reckoned: idle, the hours stand
    await town.until("10:00", day=2)
    await town.call("Vera", "how_am_i")
    assert vera.worked == 15 * 60
    # The checkpoint keeps the announcements.
    await town.until("03:00", day=3)
    (_, state) = town.checkpoints[-1]
    assert state["announcements"] == [[at("09:15", day=2), "The well is dry; boil your water."]]
    make_agent_dirs(tmp_path / "r", world.config)
    restored = World(world.config, tmp_path / "r", FakeBackend(), clock=ManualClock())
    restored.restore(json.loads(json.dumps(state)))
    assert restored.snapshot() == state


async def test_the_mayor_at_work_at_home_goes_to_bed_and_his_work_ends(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world, vera = town.world, town.world.residents["Vera"]
    for name, place in (("Vera", "hall"), ("Mei", "workshop")):
        await town.call(name, "go", place=place)
    await town.until("07:10")
    for name in ("Vera", "Mei"):
        await town.call(name, "start_work")
    await town.call("Vera", "go", place=vera.home)
    await town.until("07:20")
    assert isinstance(vera.base, Work) and vera.place == vera.home
    went = await town.call("Vera", "sleep", until="18:00")
    assert went.text == "You stopped work. You went to bed."
    assert isinstance(vera.base, Sleep) and not world.on_duty(vera)
    kinds = [e["kind"] for e in world.log.entries() if e["actor"] == "Vera"]
    assert kinds[-2:] == ["leave_work", "sleep"]
    # Away from home, work goes on.
    assert (await town.call("Mei", "sleep", until="18:00")).text == "You can sleep only at home."
    assert isinstance(world.residents["Mei"].base, Work)


def _kinds_at(world, name: str, t: int) -> list[str]:
    """What happened to `name` at the simulated time `t`, its needs and the hour aside."""
    return [
        e["kind"]
        for e in world.log.entries()
        if e["actor"] == name and e["sim_time"] == t and e["kind"] not in ("condition", "time")
    ]


async def test_the_mayors_duty_on_the_road_stops_as_work_does(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world, vera = town.world, town.world.residents["Vera"]
    await town.call("Vera", "go", place="hall")
    await town.until("07:10")
    await town.call("Vera", "start_work")
    town.take("Vera")
    # Exhausted on the way, she arrives off duty.
    vera.living.energy = 15.5  # the ten minutes' walk takes 1
    await town.call("Vera", "go", place="park")
    await town.until("07:20")
    assert isinstance(vera.base, Idle) and vera.place == "park"
    assert town.take("Vera")[0] == f"You stopped work. {EXHAUSTED}"
    # On the road at work at the night's end, her work ends before she falls asleep.
    vera.living.energy = 100
    await town.call("Vera", "go", place="hall")
    await town.until("23:00")
    await town.call("Vera", "start_work")
    town.rest()
    await town.until("01:55", day=2)
    await town.call("Vera", "go", place="park")
    await town.until("02:00", day=2)
    assert _kinds_at(world, "Vera", at("02:00", day=2)) == ["leave_work", "forced_sleep"]


async def test_the_mayor_taken_to_bed_on_the_road_stops_work_first(make_town):
    town = make_town(TOWN)
    await awake_at(town)
    world, vera = town.world, town.world.residents["Vera"]
    await town.call("Vera", "go", place="hall")
    await town.until("23:55")
    await town.call("Vera", "start_work")
    vera.living.health, vera.living.satiety = 10, 0  # her last day on her feet, out of food
    await town.call("Vera", "go", place="park")
    await town.until("00:00", day=2)
    assert vera.living.bedridden and vera.place == vera.home
    assert _kinds_at(world, "Vera", DAY) == ["leave_work", "bedridden", "settlement"]
