"""A resident without an occupation lives a day like anyone, with no work and nothing paying it,
and the real town's three newcomers are as the design has them: newly come, liked by nobody,
liking nobody, with little money and a room each."""

from __future__ import annotations

import re

import pytest

from agent.wording import offences
from experiments.config import PROJECT_ROOT, load_experiment
from tests.support.towns import RESIDENTS, TRADES, at, awake_at, town_config
from tests.world.acts import give, take
from world.config import SEARCH_KEY

MAREK = {"name": "Marek", "home": "college-flat", "purse": 40}
"""A resident with no occupation."""


async def test_one_without_an_occupation_lives_a_day_with_no_work_and_nothing_paying_it(
    make_town,
):
    town = make_town(town_config(residents=(*RESIDENTS, *TRADES, MAREK)))
    world = town.world
    marek = world.residents["Marek"]
    assert marek.occupation is None and marek.work == frozenset() and marek.workplace is None
    rules = world.rules.sections("Marek")
    assert rules["work"] == (
        "You are without an occupation in the town and have no workplace: nobody pays you a "
        "wage, a share or a salary, and what you have is the money you came with and what comes "
        "to you from others."
    )
    assert "You have $40 to begin with. Your rent, $30 a day" in rules["money"]
    assert (
        "Olga is the shopkeeper at the store and Marek has no occupation."
        in (world.rules.sections("Mei")["people"])
    )
    await awake_at(town)
    await town.call("Marek", "go", place="workshop")
    await town.until("07:10")
    offered = {spec.name for spec in world.ports["Marek"].tool_specs()}
    assert {"start_work", "view_board", "claim_task", "order", "cook"}.isdisjoint(offered)
    assert (await town.call("Marek", "start_work")).text == (
        "You have no occupation, and no work to sit down to."
    )
    assert (await town.call("Marek", "view_board")).text == "That is not your work."
    await town.call("Marek", "go", place="store")
    await town.call("Olga", "go", place="store")
    await town.until("07:20")
    assert (await town.call("Marek", "set_price", item="bread", price=1)).text == (
        "That is not your work."
    )
    assert await take(town, "Marek", "bread", "shelves", 2) == (
        "You took 2 helpings of bread from the shelves. The price posted is $4 each, $8 in all. "
        "You carry 2 helpings of bread."
    )
    assert await give(town, "Marek", "money", "Olga", 8) == (
        "You gave Olga $8. Your purse holds $32."
    )
    await town.call("Marek", "go", place="college-flat")
    await town.until("22:00")
    slept = await town.call("Marek", "sleep", likes=["Olga"], until="07:00", journal="New here.")
    assert slept.text.endswith("You named Olga as someone you like.")
    town.rest()
    await town.until("07:00", day=2)
    entries = world.log.entries()
    statement = next(e for e in entries if e["kind"] == "settlement" and e["actor"] == "Marek")
    assert statement["payload"]["salary"] == 0 and statement["payload"]["rent"] == 30
    assert statement["payload"]["rent_paid"] == 22 and statement["payload"]["arrears"] == 8
    assert marek.inventory.money == 10 and marek.base.kind == "idle"
    assert world.liked_by()["Olga"] == 1 and town.world.clock.now() == at("07:00", day=2)


@pytest.fixture
def the_town(monkeypatch):
    monkeypatch.setenv(SEARCH_KEY, "a key")
    return load_experiment(PROJECT_ROOT / "experiments" / "configs" / "town.yaml")


def test_the_real_towns_newcomers_are_new_liked_by_nobody_and_short_of_money(the_town):
    town = the_town.town
    newcomers = [r for r in town.residents if r.newcomer]
    assert [(r.name, r.occupation) for r in newcomers] == [
        ("Marek", None), ("Ines", None), ("Selin", "programmer"),
    ]  # fmt: skip
    names = {r.name for r in newcomers}
    assert all(not r.likes for r in newcomers)
    assert all(names.isdisjoint(r.likes) for r in town.residents)
    assert max(r.purse for r in newcomers) < min(r.purse for r in town.residents if not r.newcomer)
    rooms = {p.id: p.rooms for p in town.places if p.kind == "home"}
    for home in {r.home for r in newcomers}:
        assert sum(r.home == home for r in town.residents) <= rooms[home]
    # The eight are each liked by someone at the start, as their backgrounds tell it.
    liked = {r.name: sum(r.name in o.likes for o in town.residents) for r in town.residents}
    assert all(liked[r.name] >= 2 for r in town.residents if not r.newcomer), liked
    assert {r.name for r in the_town.residents} >= names  # each with its background


def test_the_newcomers_backgrounds_are_in_the_form_of_the_eight_and_pass_the_guard(the_town):
    lengths = {}
    for resident in the_town.residents:
        text = resident.background_path.read_text(encoding="utf-8")
        paragraphs = text.strip().split("\n\n")
        lengths[resident.name] = [len(p.split()) for p in paragraphs]
        assert len(paragraphs) == 2, resident.name
        assert text.startswith(f"I am {resident.name}, "), resident.name
        assert not re.search(r"\byou\b|\byours?\b", text, re.IGNORECASE), resident.name
        assert offences(text) == [], (resident.name, offences(text))
    newcomers = [r.name for r in the_town.town.residents if r.newcomer]
    eight = [lengths[name] for name in lengths if name not in newcomers]
    for name in newcomers:
        for i in (0, 1):  # about the length of the eight's, each paragraph
            low, high = min(e[i] for e in eight), max(e[i] for e in eight)
            assert 0.9 * low <= lengths[name][i] <= 1.1 * high, (name, lengths[name])
        text = (PROJECT_ROOT / "experiments" / "residents" / f"{name.lower()}.md").read_text()
        assert "weeks ago" in text or "two weeks" in text  # newly come
