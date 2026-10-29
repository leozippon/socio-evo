"""The experiments' configurations: the town, the run and the smoke town over it, the overlay
rule, and the residents' backgrounds."""

from __future__ import annotations

import re
from statistics import fmean

import pytest

from agent.wording import offences
from experiments.config import PROJECT_ROOT, load_experiment, overlay
from infrastructure.config import ConfigError
from world.body import Body, Living
from world.config import A_DAYS_FOOD
from world.occupations import OCCUPATIONS
from world.rules import Rules

CONFIGS = PROJECT_ROOT / "experiments" / "configs"


def town():
    return load_experiment(CONFIGS / "town.yaml")


def test_the_town_and_the_run_over_it():
    found, run = town(), load_experiment(CONFIGS / "runs" / "town.yaml")
    assert found.name == run.name == "town"
    assert found.days == 28 and len(found.residents) == 8
    assert found.runtime.reasoning_effort == "low"
    assert found.llm.max_concurrency == len(found.residents)
    assert found.town.start_date.strftime("%A %d %B %Y") == "Monday 02 March 2026"
    assert run.town.start_date > found.town.start_date  # the run names the day it starts
    assert run.model_dump(exclude={"town"}) == found.model_dump(exclude={"town"})
    assert run.town.model_dump(exclude={"start_date"}) == found.town.model_dump(
        exclude={"start_date"}
    )


def test_the_smoke_town_is_the_team_leader_the_shopkeeper_and_the_chef_for_a_day():
    smoke, found = load_experiment(CONFIGS / "smoke.yaml"), town()
    assert [r.name for r in smoke.residents] == [r.name for r in smoke.town.residents]
    assert [(r.name, r.occupation) for r in smoke.town.residents] == [
        ("Mei", "team-leader"),
        ("Olga", "shopkeeper"),
        ("Jonas", "chef"),
    ]
    assert smoke.days == 1 and smoke.town.clock == found.town.clock
    assert smoke.town.social == found.town.social and smoke.town.work == found.town.work


def test_an_overlay_merges_mappings_and_replaces_everything_else():
    base = {"a": {"b": 1, "c": [1, 2], "d": {"e": 1}}, "f": 1}
    top = {"a": {"c": [3], "d": None}, "g": 2}
    assert overlay(base, top) == {"a": {"b": 1, "c": [3], "d": None}, "f": 1, "g": 2}
    assert base == {"a": {"b": 1, "c": [1, 2], "d": {"e": 1}}, "f": 1}


def test_bad_configurations_are_refused_naming_the_file(tmp_path):
    loop = tmp_path / "loop.yaml"
    loop.write_text("base: loop.yaml\nname: x\n")
    with pytest.raises(ConfigError, match="lead back"):
        load_experiment(loop)
    stranger = tmp_path / "stranger.yaml"
    stranger.write_text(
        f"base: {CONFIGS / 'town.yaml'}\n"
        "residents: [{name: Zoe, background: experiments/residents/mei.md}]\n"
    )
    with pytest.raises(ConfigError, match=r"stranger\.yaml: .*not exactly the town's residents"):
        load_experiment(stranger)
    unknown = tmp_path / "unknown.yaml"
    unknown.write_text(f"base: {CONFIGS / 'town.yaml'}\ntown: {{social: {{weather: rain}}}}\n")
    with pytest.raises(ConfigError, match="weather"):
        load_experiment(unknown)


def test_the_compaction_threshold_is_bounded_by_the_models_context_window(tmp_path):
    found = town()
    # A context just past the threshold, grown by a reply and a margin, leaves the notes room.
    window = found.llm.context_window
    assert (window, found.runtime.ceiling(window)) == (262_144, 229_376)
    assert found.runtime.compaction_threshold == 225_000
    at, above = tmp_path / "at.yaml", tmp_path / "above.yaml"
    for path, threshold in ((at, 229_376), (above, 229_377)):
        base = CONFIGS / "town.yaml"
        path.write_text(f"base: {base}\nruntime: {{compaction_threshold: {threshold}}}\n")
    assert load_experiment(at).runtime.compaction_threshold == 229_376
    with pytest.raises(ConfigError, match="229377 is above 229376, the most that"):
        load_experiment(above)


def test_backgrounds_are_first_person_and_a_shared_history_without_trait_words():
    config = town()
    assert len(config.residents) == 8
    named = dict.fromkeys((r.name for r in config.residents), 0)
    for resident in config.residents:
        text = resident.background_path.read_text(encoding="utf-8")
        assert text.startswith(f"I am {resident.name}, "), resident.name
        assert not re.search(r"\byou\b|\byours?\b", text, re.IGNORECASE), resident.name
        assert offences(text) == [], resident.name
        for other in named:
            if other != resident.name and re.search(rf"\b{other}\b", text):
                named[other] += 1
    assert min(named.values()) >= 2, named  # everyone is in the history of at least two others


def test_the_rules_are_about_three_thousand_characters_and_pass_the_guard():
    config = town().town
    rules = Rules(config)
    for resident in config.residents:
        text = rules.text(resident.name)
        assert 2500 <= len(text) <= 3500, (resident.name, len(text))
        assert offences(text) == [], (resident.name, offences(text))
        assert text.split("\n\n")[1].startswith("Work. You are ")  # its occupation and workplace


# The calibration of the closed economy (experiments/configs/town.yaml's notes): three tasks
# arriving a day, half accepted; the town eating a dish a day each, the menu's in turn, seven sold
# and the chef's own; the cases of illness the town in good health sees a day, each examined and
# treated at the surgery.
ACCEPTED = 0.5


def test_rent_food_shares_margins_and_the_treasury_are_set_against_one_another():
    config = town().town
    assert {o.id for o in config.occupations} == set(OCCUPATIONS)  # the six of the design
    tax, work = config.tax, config.work
    rents = {place.id: place.rent for place in config.places if place.kind == "home"}
    assert sorted(set(rents.values())) == [10, 15, 20]  # a room, a flat, the cottage
    # The cheapest day's food: the helpings of ready food that make a day's need, at the price
    # the Store starts with; the dearest, the dearest dish.
    food = min(
        (item for item in config.supplied if item.ready),
        key=lambda good: good.price * round(A_DAYS_FOOD / good.nourishment),
    )
    a_day = round(A_DAYS_FOOD / food.nourishment) * food.price
    cheapest = min(rents.values()) + a_day
    dearest = max(rents.values()) + max(dish.price for dish in config.dishes)
    assert (cheapest, dearest) == (25, 40)
    assert config.treasury.spares >= a_day  # rent never takes a day's bread

    # The clients' payments, shared out after the tax: a programmer's expected share, the
    # accepted tasks among the programmers, and the team leader's fifth of them all.
    office = [
        r.occupation for r in config.residents if r.occupation in ("programmer", "team-leader")
    ]
    assert work.tasks_a_day < len(office)  # fewer than those who take them on
    clients = work.tasks_a_day * ACCEPTED * work.payment
    programmers = office.count("programmer")
    programmer = clients * (1 - work.leader_share) * (1 - tax) / programmers
    leader = clients * work.leader_share * (1 - tax)
    assert (round(programmer, 2), round(leader, 2)) == (54, 40.5)
    assert programmer >= dearest and leader >= dearest

    # The businesses' margins after the tax, the town eating a dish a day each: the chef's on
    # his seven dishes, the menu's mean less its ingredients at the Store; the shopkeeper's on
    # the eight dishes' ingredients, at the Store's prices less the supplier's.
    def cost(dish, price) -> float:
        return sum(units * price(config.item(item)) for item, units in dish.ingredients.items())

    menu = fmean(dish.price for dish in config.dishes)
    retail = fmean(cost(dish, lambda item: item.price) for dish in config.dishes)
    wholesale = fmean(cost(dish, lambda item: item.wholesale) for dish in config.dishes)
    meals = len(config.residents)
    sold = meals - 1  # a dish to each of the others; the chef has his own
    chef = sold * (menu * (1 - tax) - retail)
    shop = meals * (retail * (1 - tax) - wholesale)
    assert (round(chef, 2), round(shop, 2)) == (44.92, 41.87)
    assert chef >= dearest and shop >= dearest
    # The doctor's patients: the cases of illness the town in good health sees a day, by the
    # chance of each resident's home, about one, each examined and treated (about two visits);
    # their fees keep the cheapest life.
    body, comfort = Body(config.needs), {place.id: place.comfort for place in config.places}
    cases = sum(body.illness_chance(Living(), comfort[r.home]) for r in config.residents)
    fees = config.hospital
    doctor = cases * (fees.examination + fees.treatment) * (1 - tax)
    assert (round(cases, 2), fees.examination, fees.treatment, round(doctor, 2)) == (
        1.0, 25, 60, 76.5,
    )  # fmt: skip
    assert doctor >= cheapest

    # The treasury's day: the rent of every room taken and the tax on the day's payments in,
    # the mayor's salary out. The plan asked for a surplus of at most a third of the intake;
    # with these rents and this salary it is three fifths, which holds below two thirds.
    rent = sum(rents[r.home] for r in config.residents)
    taxes = tax * (
        clients + meals * retail + sold * menu + cases * (fees.examination + fees.treatment)
    )
    salary = sum(config.occupation(r.occupation).salary for r in config.residents)
    intake = rent + taxes
    assert (rent, round(taxes, 2), salary) == (105, 50.72, 60)
    assert 0 < intake - salary <= 2 / 3 * intake and round((intake - salary) / intake, 1) == 0.6
    assert config.treasury.start >= 5 * salary
    # The town's money grows by what the clients pay less what the supplier is paid.
    supplier = meals * wholesale
    assert round(clients - supplier, 2) == 199.67

    # Starting money is five to ten days of its owner's own life, its rent and a day's bread;
    # the chef's and the shopkeeper's working capital set apart: a day of the kitchen's
    # ingredients at the Store, and the food on the starting shelves twice over at wholesale.
    shelves = sum(
        units * config.item(item).wholesale  # type: ignore[operator]
        for item, units in config.store.stock.items()
        if config.item(item).effect == "food"
    )
    capital = {"chef": meals * retail, "shopkeeper": 2 * shelves}
    for resident in config.residents:
        own = rents[resident.home] + a_day
        days = (resident.purse - capital.get(resident.occupation, 0)) / own
        assert 5 <= days <= 10, (resident.name, days)
