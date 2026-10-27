"""The residents' bodies: needs that fall by the hour and are read in bands, told as they cross
one; food and a stock that restore satiety; sleep that restores energy by the home's comfort and
never above health; work stopped by exhaustion and barred until one has slept; health worn at
midnight by starving, exhaustion and a poor home, mended by rest and by the clinic; the
examination's words; and death, which stops a life, is told to the others, and is kept by a
checkpoint."""

from __future__ import annotations

import json

import pytest

from agent.port import ToolResult
from tests.world.conftest import RESIDENTS, at, awake_at, stocked, town_config
from world.body import Body, Living
from world.clock import DAY, ManualClock
from world.events import ENDED, EXHAUSTED, Dead, Idle, Work
from world.testing import FakeBackend
from world.world import World


def test_the_arithmetic_of_the_needs():
    body = Body(town_config().needs)
    living = Living()
    body.elapse(living, 10 * 3600, "awake", 1.0)
    assert (living.satiety, living.energy) == (62.5, 85)  # 3.75 and 1.5 an hour
    body.elapse(living, 3600, "work", 1.0)
    assert living.energy == pytest.approx(78.5)  # 1.5 + 5 an hour at work
    body.elapse(living, 1800, "walk", 1.0)
    assert living.energy == pytest.approx(74.75)  # 1.5 an hour and 0.1 a minute on the road
    body.eat(living, 65)
    assert living.satiety == 100  # capped
    body.elapse(living, 5 * 3600, "sleep", 0.9)
    assert living.energy == pytest.approx(100)  # 12 an hour times the comfort, capped
    assert living.satiety == pytest.approx(81.25)  # satiety falls asleep too
    living.health, living.energy = 40, 30
    body.elapse(living, 3600, "sleep", 1.0)
    assert living.energy == 42  # sleep restores energy up to health, or up to 50
    body.elapse(living, 3600, "sleep", 1.0)
    assert living.energy == 50  # and no further, however long
    living.energy = 60
    body.elapse(living, 3600, "sleep", 1.0)
    assert living.energy == 60  # and never takes it away
    assert [body.band("satiety", v).name for v in (100, 65, 64.9, 35, 10, 9.9, 0)] == [
        "well fed", "well fed", "a little hungry", "a little hungry", "hungry", "starving",
        "starving",
    ]  # fmt: skip
    assert body.lowest("energy", 14.9) and not body.lowest("energy", 15)
    assert body.condition(living) == "You are well fed. You are a little tired. You are run down."
    assert body.warnings(living) == []
    living.satiety, living.energy = 5, 0
    assert body.warnings(living) == ["You are starving.", "You are exhausted."]
    assert body.seen(living) is None
    living.health = 20
    assert body.seen(living) == "looking unwell"


def test_health_moves_at_midnight_by_the_days_wear_and_recovery():
    body = Body(town_config().needs)
    living = Living()
    assert body.night(living, 1.0) == {"recovery": 5} and living.health == 100  # capped
    living.satiety = 5
    assert body.night(living, 0.9) == {"starving": -15, "poor_home": -2}
    assert living.health == 83 and living.night == {"starving": -15, "poor_home": -2}
    living.energy = 10
    assert body.night(living, 1.1) == {"starving": -15, "exhausted": -5} and living.health == 63
    living.satiety = 50
    assert body.night(living, 1.0) == {"exhausted": -5} and living.health == 58
    living.energy, living.health = 50, 3
    assert body.night(living, 0.9) == {"poor_home": -2, "recovery": 5} and living.health == 6
    living.health = 1
    living.satiety = 0
    body.night(living, 1.0)
    assert living.health == 0 and not living.alive
    body.treat(living, 25)
    assert living.health == 25
    assert body.examination(living) == (
        "The doctor looks you over. Food: 0 of 100, you are starving. Energy: 50 of 100, you "
        "are a little tired. Health: 25 of 100, you are unwell. Last night your health fell by "
        "15: you were starving at midnight."
    )
    living.night = {"poor_home": -2, "recovery": 5}
    assert body.examination(living).endswith(
        "Last night your health rose by 3: your home has little comfort and you had eaten and "
        "rested."
    )
    assert "Last night" not in body.examination(Living())


def _live_day(body: Body, living: Living, comfort: float, hours: list[tuple[str, float]]) -> None:
    """A day from one midnight to the next as a list of (activity, hours), "eat" meaning a
    day's food, then the night's reckoning. Work stops, as the world stops it at the hour, once
    the resident is exhausted, and its hours left are spent awake."""
    for activity, span in hours:
        if activity == "eat":
            body.eat(living, 100)
        elif activity == "work":
            for _ in range(round(span)):
                spent = body.lowest("energy", living.energy)
                body.elapse(living, 3600, "awake" if spent else "work", comfort)
        else:
            body.elapse(living, round(span * 3600), activity, comfort)  # type: ignore[arg-type]
    body.night(living, comfort)


WORK_DAY = [
    ("sleep", 7), ("awake", 1), ("eat", 0), ("awake", 1), ("work", 12), ("awake", 2), ("sleep", 1),
]  # fmt: skip
"""Asleep to 07:00, a meal at 08:00, twelve hours of work from 09:00 and in bed at 23:00."""
LATE_DAY = [("awake", 2), ("sleep", 5), ("awake", 2), ("eat", 0), ("work", 15)]
"""Up until the forced sleep at 02:00, asleep to 07:00, a meal at 09:00 and work from then for
as long as the body allows, still up at midnight."""


def test_the_calibration_keeps_a_rested_working_life_well_and_overwork_wears_it_out():
    body = Body(town_config().needs)
    # Fresh in the morning, a resident is tired after ten hours of work and exhausted after
    # thirteen: in the eleventh hour and in the fourteenth.
    living, bands = Living(), []
    for _ in range(14):
        body.elapse(living, 3600, "work", 1.0)
        bands.append(body.band("energy", living.energy).name)
    assert bands.index("tired") == 10 and bands.index("exhausted") == 13
    # Twelve-hour days in a shared house, a meal a day, in bed at 23:00, for four weeks: tired at
    # bedtime, never exhausted, in full health.
    living = Living()
    for _ in range(28):
        _live_day(body, living, 0.9, WORK_DAY)
        assert living.health == 100 and not body.lowest("energy", living.energy)
    assert body.band("energy", living.energy).name == "tired"
    # Still up at midnight, eleven hours of work leave a fresh resident tired, twelve exhausted.
    for work, band in ((11, "tired"), (12, "exhausted")):
        living = Living()
        _live_day(body, living, 1.0, [("sleep", 7), ("work", work), ("awake", 17 - work)])
        assert body.band("energy", living.energy).name == band, work
    # Ill, a resident that eats and rests recovers: it wakes with half a day's energy.
    living = Living(health=10)
    for day in range(1, 5):
        _live_day(body, living, 1.0, [("sleep", 7), ("eat", 0), ("awake", 17)])
        assert living.health == 10 + 5 * day and living.night == {"recovery": 5}
    # One that never eats, full at its last meal, is starving from the second midnight and dies
    # in about a week: at the eighth midnight in a flat, the seventh in a shared house.
    for comfort, nights in ((1.0, 8), (0.9, 7)):
        living = Living()
        for night in range(1, nights + 1):
            _live_day(body, living, comfort, [("sleep", 7), ("awake", 17)])
            assert living.alive == (night < nights), (comfort, night)
    # One such day, worked to exhaustion and up past midnight, ends exhausted even after a full
    # night's rest, and a rested day after it mends it.
    living = Living()
    _live_day(body, living, 0.9, LATE_DAY)
    assert body.band("energy", living.energy).name == "exhausted"
    assert living.health == 93 and living.night == {"exhausted": -5, "poor_home": -2}
    _live_day(body, living, 0.9, WORK_DAY)
    assert body.band("energy", living.energy).name == "tired" and living.health == 96
    # Lived so every day, it is exhausted at every midnight and, eating every day, dies of it at
    # the fifteenth in a shared house and the twentieth in a flat, told run down and unwell first.
    for comfort, nights, first_told in (
        (0.9, 15, {"in good health": 1, "run down": 6, "unwell": 10, "gravely ill": 13}),
        (1.0, 20, {"in good health": 1, "run down": 8, "unwell": 14, "gravely ill": 19}),
    ):
        living, first = Living(), {}
        for night in range(1, nights + 1):
            assert living.alive
            _live_day(body, living, comfort, LATE_DAY)
            assert body.lowest("energy", living.energy)
            first.setdefault(body.band("health", living.health).name, night)
        assert not living.alive and first == first_told


async def test_the_needs_are_told_by_the_hour_as_they_cross_a_band_and_on_asking(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei = world.residents["Mei"]
    assert mei.living.satiety == pytest.approx(100 - 4.5 * 3.75)  # since 02:30, asleep
    assert (await town.call("Mei", "how_am_i")).text == (
        "You are well fed. You are fresh. You are in good health."
    )
    await town.call("Mei", "go", place="workshop")
    await town.until("09:00")
    await town.call("Mei", "claim_task", task=1)
    town.take("Mei")
    await town.until("20:00")
    assert town.take("Mei") == [
        "You are a little hungry.",  # 12:00
        "You are a little tired.",  # 14:00
        "You are tired.",  # 19:00, after ten hours at work
        "You are hungry.",  # 20:00
    ]
    assert (await town.call("Mei", "how_am_i")).text == (
        "You are hungry. You are tired. You are in good health."
    )
    situation = world.ports["Mei"].situation()
    assert "starving" not in situation and "exhausted" not in situation  # no need at its worst
    told = [e for e in world.log.entries() if e["kind"] == "condition" and e["actor"] == "Mei"]
    assert [(e["sim_time"], e["text"]) for e in told][:2] == [
        (at("12:00"), "Mei is a little hungry."),
        (at("14:00"), "Mei is a little tired."),
    ]
    assert told[-2]["payload"] == {
        "need": "energy", "band": "tired", "value": 31.0, "lowest": False,
    }  # fmt: skip
    assert told[-2]["audience"] == ["Mei"] and told[-2]["personal"] == {"Mei": "You are tired."}
    mei.living.energy = 5
    assert "You are exhausted." in world.ports["Mei"].situation()
    # Asleep, the body is reckoned and logged but nothing is told until the wake-up.
    town.take("Tomas")
    town.rest()
    await town.until("07:00", day=2)
    heard = [p.text for p in town.heard["Tomas"] if p.kind in ("condition", "wake")]
    assert heard[-1] == (
        "You woke up at home. It is Tuesday 2 January, 07:00. You are starving. You are fresh. "
        "You are in good health."
    )
    logged = [e for e in world.log.entries() if e["kind"] == "condition" and e["actor"] == "Tomas"]
    assert [e["payload"]["band"] for e in logged] == ["a little hungry", "hungry", "starving"]
    assert logged[-1]["audience"] == [] and logged[-1]["sim_time"] == at("03:00", day=2)


async def test_eating_restores_satiety_and_a_stock_is_drawn_on_as_one_gets_hungry(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei, tomas = world.residents["Mei"], world.residents["Tomas"]
    mei.living.satiety = 20
    await town.call("Mei", "go", place="cafe")
    await town.until("07:10")
    assert (await town.call("Mei", "buy", item="meal")).text == (
        "You bought a meal at the café for $10. You are well fed. Your purse holds $110."
    )
    assert mei.living.satiety == 100  # a day's food, capped
    eaten = [e for e in world.log.entries() if e["kind"] == "condition" and e["actor"] == "Mei"]
    assert [e["payload"]["band"] for e in eaten] == ["well fed"] and eaten[0]["audience"] == []

    stocked(town, days=1)  # three helpings
    tomas.living.satiety = 30
    await town.until("08:00")  # the hour's reckoning: he eats until he could eat no more
    assert tomas.living.things == {"groceries": 1} and tomas.living.eaten == {"groceries": 2}
    assert tomas.living.satiety == pytest.approx(30 - 3.75 + 68)
    assert town.take("Tomas")[-1] == "You are well fed."
    tomas.living.satiety = 30
    await town.until("09:00")
    assert tomas.living.things == {} and tomas.living.eaten == {"groceries": 3}  # the third
    tomas.living.things["groceries"] = 3
    tomas.living.satiety = 30
    await town.until("10:00")
    assert tomas.living.things == {"groceries": 3}  # three helpings a day, no more
    town.rest("Tomas")
    await town.until("07:00", day=2)
    assert tomas.living.things == {} and tomas.living.eaten == {"groceries": 3}  # at waking


async def test_sleep_restores_energy_by_the_homes_comfort_and_never_above_health(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei, tomas = world.residents["Mei"], world.residents["Tomas"]  # Mill Street 0.9, the flat 1
    mei.living.energy = tomas.living.energy = 20
    mei.living.health = 60
    for name in ("Mei", "Tomas"):
        await town.call(name, "sleep", until="12:00", journal="A nap.")
    town.rest()
    await town.until("12:00")
    assert tomas.living.energy == pytest.approx(20 + 5 * 12)  # 12 an hour, five hours
    assert mei.living.energy == pytest.approx(60)  # 20 + 5 * 10.8 = 74, capped by her health
    assert [p.text for p in town.heard["Mei"] if p.kind == "wake"][-1].endswith(
        "You are a little tired. You are run down."
    )
    mei.living.energy, mei.living.health = 20, 30
    await town.call("Mei", "sleep", until="19:00", journal="Another.")
    await town.until("19:00")
    assert mei.living.energy == pytest.approx(50)  # ill, one still wakes with half a day's
    assert [p.text for p in town.heard["Mei"] if p.kind == "wake"][-1].endswith(
        "You are a little tired. You are unwell."
    )


async def test_exhaustion_stops_work_and_bars_it_until_one_has_slept(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei, tomas = world.residents["Mei"], world.residents["Tomas"]
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("08:10")
    tomas.living.energy = 14
    assert (await town.call("Tomas", "claim_task", task=1)).text == EXHAUSTED
    assert "Tomas" not in world.board.claims and isinstance(tomas.base, Idle)
    assert "You are exhausted." in world.ports["Tomas"].situation()
    tomas.living.energy = 15
    claimed = await town.call("Tomas", "claim_task", task=1)
    assert claimed.text.startswith("You sat down to work and claimed task 1")
    town.take("Tomas")
    # Exhausted at work, an action in the workspace finds it so: work stops, the task is kept,
    # and nothing more is done in the workspace until one has slept.
    tomas.living.energy = 5
    assert (await town.call("Tomas", "shell", command="ls")).text == EXHAUSTED
    assert isinstance(tomas.base, Idle) and world.board.claims["Tomas"].task == 1
    assert town.take("Tomas") == [f"You stopped work. {EXHAUSTED} You still hold task 1."]
    for tool, args in (
        ("read_repo_file", {"path": "a.py"}),
        ("write_repo_file", {"path": "a.py", "content": "x"}),
        ("edit_repo_file", {"path": "a.py", "old_text": "x", "new_text": "y"}),
        ("submit", {}),
    ):
        assert (await town.call("Tomas", tool, **args)).text == EXHAUSTED, tool
    workspace = world.board.workspaces["Tomas"]
    assert workspace.commands == [] and workspace.changed == {}  # nothing ran, nothing written
    # At the hour, the body's reckoning finds Mei, who sat down tired, exhausted and stops her.
    mei.living.energy = 20
    await town.call("Mei", "claim_task", task=2)
    town.take("Mei")
    await town.until("09:00")  # 20 less 6.5 an hour for 50 minutes
    assert isinstance(mei.base, Idle) and world.board.claims["Mei"].task == 2
    assert town.take("Mei") == [
        "You are exhausted.",
        f"You stopped work. {EXHAUSTED} You still hold task 2.",
    ]
    stopped = [e for e in world.log.entries() if e["kind"] == "leave_work"]
    assert [(e["actor"], e["text"], e["audience"]) for e in stopped] == [
        ("Tomas", "Tomas stopped work, exhausted.", ["Tomas"]),
        ("Mei", "Mei stopped work, exhausted.", ["Mei"]),
    ]
    assert stopped[-1]["sim_time"] == at("09:00")
    # Asleep, energy comes back, and with it work.
    await town.call("Tomas", "go", place="college-flat")
    await town.until("09:10")
    await town.call("Tomas", "sleep", until="12:00")
    town.rest("Tomas")
    await town.until("12:00")
    assert (await town.call("Tomas", "shell", command="ls")).text.startswith(
        "You sat down to work. It is 12:00."
    )
    assert isinstance(tomas.base, Work)


async def test_health_is_worn_by_the_days_and_shows_to_others_and_the_clinic_mends_it(make_town):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei, tomas = world.residents["Mei"], world.residents["Tomas"]
    mei.living.health = 30  # unwell
    await town.call("Mei", "go", place="workshop")
    await town.call("Tomas", "go", place="workshop")
    await town.until("07:10")
    assert (await town.call("Tomas", "look_around")).text.endswith(
        "Also here: Mei (looking unwell)."
    )
    assert "looking unwell" not in (await town.call("Mei", "look_around")).text
    await town.call("Mei", "go", place="clinic")
    await town.until("07:20")
    assert (await town.call("Mei", "buy", item="examination", quantity=2)).text == (
        "One examination at a time."
    )
    examined = (await town.call("Mei", "buy", item="examination")).text
    assert examined == (
        "You bought an examination for $10. The doctor looks you over. Food: 82 of 100, you are "
        "well fed. Energy: 98 of 100, you are fresh. Health: 30 of 100, you are unwell. Your "
        "purse holds $110."
    )
    assert (await town.call("Mei", "buy", item="treatment")).text == (
        "You bought treatment for $25. You are run down. Your purse holds $85."
    )
    assert mei.living.health == 55
    bought = [e for e in world.log.entries() if e["kind"] == "purchase" and e["actor"] == "Mei"]
    assert bought[0]["text"] == "Mei bought an examination for $10."
    assert bought[0]["personal"]["Mei"].startswith(
        "You bought an examination for $10. The doctor looks you over. Food: 82 of 100"
    )
    assert bought[1]["personal"] == {"Mei": "You bought treatment for $25."}
    assert bought[1]["payload"]["effect"] == "treatment"
    mended = [e for e in world.log.entries() if e["kind"] == "condition" and e["actor"] == "Mei"]
    assert [e["payload"]["band"] for e in mended] == ["run down"]
    mei.living.health = 100
    assert (await town.call("Mei", "buy", item="treatment")).text == (
        "The doctor finds nothing to treat."
    )
    assert world.economy.purses["Mei"] == 85

    # The night's reckoning: Mei (Mill Street, 0.9) ends the day starving and exhausted; Tomas
    # (the flat) has eaten and rested.
    mei.living.satiety, mei.living.energy, mei.living.health = 5, 10, 50
    tomas.living.satiety, tomas.living.energy, tomas.living.health = 100, 100, 50
    for name in world.residents:
        town.take(name)
    town.rest()
    await town.until("00:00", day=2)
    assert mei.living.health == pytest.approx(50 - 15 - 5 - 2)
    assert tomas.living.health == pytest.approx(55)
    statements = {
        name: [p.text for p in town.heard[name] if p.kind == "settlement"][-1]
        for name in ("Mei", "Tomas")
    }
    assert "You are starving. You are exhausted. You are unwell." in statements["Mei"]
    assert "You are a little hungry. You are fresh. You are run down." in statements["Tomas"]
    settled = {e["actor"]: e["payload"] for e in world.log.entries() if e["kind"] == "settlement"}
    assert settled["Mei"]["night"] == {"starving": -15, "exhausted": -5, "poor_home": -2}
    assert (settled["Mei"]["satiety"], settled["Mei"]["energy"], settled["Mei"]["health"]) == (
        0, 0, 28,
    )  # fmt: skip
    assert settled["Tomas"]["night"] == {"recovery": 5} and settled["Tomas"]["health"] == 55
    await town.until("07:00", day=2)
    await town.call("Mei", "go", place="clinic")
    await town.until("07:20", day=2)
    assert (await town.call("Mei", "buy", item="examination")).text.endswith(
        "Health: 28 of 100, you are unwell. Last night your health fell by 22: you were starving "
        "at midnight, you were exhausted at midnight and your home has little comfort. Your "
        "purse holds $55."
    )


async def test_a_resident_whose_health_runs_out_dies_and_the_town_goes_on_without_it(
    make_town, tmp_path
):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei, tomas, aisha = (world.residents[name] for name in ("Mei", "Tomas", "Aisha"))
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("15:00")
    await town.call("Mei", "claim_task", task=1)  # at work at midnight, not yet exhausted
    mei.living.health = 10  # her last day, out of food
    mei.living.satiety = 0
    for name in world.residents:
        town.take(name)
    town.rest("Tomas", "Aisha")
    await town.until("00:00", day=2)
    assert not mei.alive and isinstance(mei.base, Dead) and mei.place is None
    assert mei.living.health == 0
    assert "Mei" not in world.board.claims and len(world.board.orphans) == 1
    midnight = [
        (e["kind"], e["actor"])
        for e in world.log.entries()
        if e["sim_time"] == DAY and e["kind"] not in ("condition", "time")
    ]
    assert midnight == [
        ("leave_work", "Mei"),
        ("death", "Mei"),
        ("settlement", "Tomas"),
        ("settlement", "Aisha"),
    ]
    death = [e for e in world.log.entries() if e["kind"] == "death"][0]
    assert death["text"] == "Mei died in the night." and death["personal"] == {}
    assert death["audience"] == ["Tomas", "Aisha"] and death["payload"] == {
        "day": 1, "home": "mill-street-house", "task": 1,
    }  # fmt: skip
    for name in ("Tomas", "Aisha"):  # both awake: told at once
        assert [p.text for p in town.heard[name] if p.kind == "death"] == ["Mei died in the night."]
    # Nothing reaches the dead, who is at no place and answers nothing; her room is free.
    town.take("Mei")  # what her body told her at work, before midnight
    await town.until("00:30", day=2)
    assert town.take("Mei") == [] and world.ports["Mei"].situation() == ENDED
    assert (await town.call("Mei", "look_around")) == ToolResult(ENDED, ends_turn=True)
    assert world.company(tomas) == [] and world.homes(tomas)["mill-street-house"] == ["Aisha"]
    assert (await town.call("Tomas", "say", text="Mei?", to=["Mei"])).text == "Mei is not here."
    tomas.living.things["phone"] = mei.living.things["phone"] = 1
    assert (await town.call("Tomas", "message", to="Mei", text="Mei?")).text == "Mei is dead."
    assert (
        "Mei" not in (await town.call("Tomas", "help", topic="places")).text.split("Your home")[0]
    )
    assert "Mei (" not in world.ports["Tomas"].rules()  # no longer among the living
    assert world.ports["Mei"].rules() == ENDED

    # The run goes on: the checkpoint is taken with her dead, and a restored world keeps her so.
    town.rest("Mei")
    await town.until("03:00", day=2)
    ((day, state),) = town.checkpoints
    assert day == 1 and state["residents"]["Mei"]["wake"] is None
    assert state["residents"]["Mei"]["living"]["health"] == 0
    assert state["residents"]["Mei"]["place"] is None and state["residents"]["Mei"]["claim"] is None
    restored = World(world.config, tmp_path, FakeBackend(), clock=ManualClock())
    restored.restore(json.loads(json.dumps(state)))
    again = restored.residents["Mei"]
    assert not again.alive and again.place is None and restored.snapshot() == state
    assert restored.ports["Mei"].situation() == ENDED
    await town.until("07:00", day=2)
    assert isinstance(aisha.base, Idle) and mei.day == [] and not mei.alive


async def test_a_resident_that_dies_while_its_checks_run_is_not_paid(make_town, monkeypatch):
    town = make_town()
    await awake_at(town)
    world = town.world
    mei = world.residents["Mei"]
    await town.call("Mei", "go", place="workshop")
    await town.until("23:50")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    mei.living.health, mei.living.satiety = 10, 0
    accept = world.board.backend.accept

    async def slow_accept(*args):  # midnight passes while the client's checks run
        await town.until("00:05", day=2)
        return await accept(*args)

    monkeypatch.setattr(world.board.backend, "accept", slow_accept)
    assert (await town.call("Mei", "submit")) == ToolResult(ENDED, ends_turn=True)
    assert not mei.alive and world.economy.purses["Mei"] == 120
    kinds = [e["kind"] for e in world.log.entries() if e["actor"] == "Mei"]
    assert "verdict" in kinds and "payment" not in kinds
    assert kinds.index("death") < kinds.index("verdict")  # the check ended after her life


async def test_in_a_town_of_ones_own_nobody_is_told_of_a_death(make_town):
    town = make_town(town_config("isolated", residents=RESIDENTS[:2]))
    await awake_at(town)
    world = town.world
    world.residents["Mei"].living.health = 1
    world.residents["Mei"].living.satiety = 0
    town.rest()
    await town.until("00:00", day=2)
    death = [e for e in world.log.entries() if e["kind"] == "death"][0]
    assert death["audience"] == [] and not world.residents["Mei"].alive
    assert [p.kind for p in town.heard["Tomas"] if p.kind == "death"] == []
