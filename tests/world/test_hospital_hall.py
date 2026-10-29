"""The Hospital and the Town Hall: the doctor's examination and treatment, at the surgery while
at work there and at the bedside of one too ill to get up, for fees the patient pays into the
doctor's purse, the tax withheld, and the doctor sets; the treasury's day in the mayor's
statement, and announcements told to everyone, kept on the hall's board and by the checkpoint.
The mayor's grants are in test_economy."""

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
from world.clock import ManualClock
from world.events import Idle, Work
from world.testing import FakeBackend
from world.world import World

TOWN = town_config(residents=RESIDENTS + TRADES + CARE, tax=0.1)


def offered(town, name: str) -> list[str]:
    return [spec.name for spec in town.world.ports[name].tool_specs()]


async def test_the_doctor_examines_and_treats_at_the_surgery_and_the_patient_pays(make_town):
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
    assert "The surgery is closed." in world.ports["Mei"].situation()
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
    assert "The surgery is open: an examination costs $10, a treatment $30." in (
        world.ports["Mei"].situation()
    )
    world.body.fall_ill(mei.living)
    mei.living.health = 50
    town.take("Mei")
    examined = (await town.call("Lucia", "examine", patient="Mei")).text
    numbers = (
        "Food: 82 of 100, {who} well fed. Energy: 98 of 100, {who} fresh. Health: 50 of 100, "
        "{who} run down. {Who} ill; untreated, it passes after 5 more nights."
    )
    assert examined == (
        "You examined Mei for $10, of which $1 in tax. "
        + numbers.format(who="Mei is", Who="Mei is")
    )
    assert town.take("Mei") == [
        "Lucia examined you for $10. " + numbers.format(who="you are", Who="You are")
    ]
    treated = await town.call("Lucia", "treat", patient="Mei")
    assert treated.text == "You treated Mei for $30, of which $3 in tax."
    assert town.take("Mei") == ["Lucia treated you for $30.", "Your illness is over."]
    assert mei.living.health == 75 and mei.living.ill == 0 and mei.inventory.money == 80
    assert world.treasury.ledger == {"tax": 4} and lucia.inventory.money == 100 + 40 - 4
    entries = {e["kind"]: e for e in world.log.entries()}
    assert entries["examination"]["payload"] == {
        "patient": "Mei", "fee": 10, "tax": 1, "satiety": 81.9, "energy": 98.5, "health": 50.0,
        "ill": 5, "night": {},
    }  # fmt: skip
    assert entries["treatment"]["payload"] == {
        "patient": "Mei", "fee": 30, "tax": 3, "restores": 25.0, "before": 50.0, "health": 75.0,
        "ill": 5, "bedridden": False,
    }  # fmt: skip
    assert entries["recovered"]["payload"] == {
        "illness": True, "bedridden": False, "treated": True, "health": 75.0,
    }  # fmt: skip
    # The doctor sets the fees; a patient who cannot pay is not seen; the doctor may see herself,
    # for nothing.
    assert (await town.call("Lucia", "set_price", item="examination", price=12)).text == (
        "The price of examination is now $12; it was $10."
    )
    assert (await town.call("Lucia", "set_price", item="bread", price=1)).text == (
        "Bread is not a service of the clinic."
    )
    world.residents["Aisha"].inventory.money = 5
    assert (await town.call("Lucia", "examine", patient="Aisha")).text == (
        "Aisha does not have the $12 the examination costs."
    )
    assert (await town.call("Lucia", "examine", patient="Lucia")).text.startswith(
        "You examined yourself. Food: "
    )
    assert lucia.inventory.money == 136
    town.rest()
    await town.until("00:00", day=2)
    statement = [p.text for p in town.heard["Mei"] if p.kind == "settlement"][-1]
    assert statement.startswith(
        "Your statement for Monday 1 January: paid $10 for an examination; paid $30 for a "
        "treatment;"
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
    assert (await town.call("Lucia", "treat", patient="Mei")).text == (
        "You treated Mei for $30, of which $3 in tax."
    )
    assert isinstance(lucia.base, Idle) and lucia.worked == 0  # no hours at a bedside
    assert not mei.living.bedridden and isinstance(mei.base, Idle) and mei.living.health == 25
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
    await town.call("Aisha", "buy", item="bread", units=2)
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
