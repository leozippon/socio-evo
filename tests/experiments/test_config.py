"""The experiments' configurations: the town, the run and the smoke town over it, the overlay
rule, and the residents' backgrounds."""

from __future__ import annotations

import re

import pytest
import yaml

from agent.wording import offences
from experiments.config import PROJECT_ROOT, ExperimentConfig, load_experiment, overlay
from infrastructure.config import ConfigError, load_config
from world.config import A_DAYS_FOOD, WORKPLACE_OF
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


def test_a_count_of_exchanges_kept_is_refused_and_set_aside_only_in_a_record_made_before(tmp_path):
    counted = tmp_path / "counted.yaml"
    counted.write_text(f"base: {CONFIGS / 'town.yaml'}\nruntime: {{kept_exchanges: 6}}\n")
    refusal = "kept_exchanges is no longer a setting: kept_tokens replaced it"
    with pytest.raises(ConfigError, match=refusal):
        load_experiment(counted)
    # A run frozen before kept_tokens named the count, and no kept_tokens.
    frozen = town().model_dump(mode="json")
    del frozen["runtime"]["kept_tokens"]
    frozen["runtime"]["kept_exchanges"] = 6
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(frozen))
    with pytest.raises(ConfigError, match=refusal):
        load_config(path, ExperimentConfig)
    assert load_config(path, ExperimentConfig, record=True) == town()


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
        assert text.split("\n\n")[2].startswith("Work. You are ")  # its occupation and workplace


# The work the fund's day is set against: the tasks arriving a day, half of them accepted.
ACCEPTED = 0.5
HOURS = 8
"""A day's work at one's workplace."""
TEAMS_SHARE = 2 / 5
"""The share of a client's payment that goes to the team: the programmer's and the leader's sums."""


def test_wages_rent_food_and_the_fund_are_set_against_one_another():
    config = town().town
    occupations = {occupation.id: occupation for occupation in config.occupations}
    assert set(occupations) == set(WORKPLACE_OF)  # the six of the design
    n = len(config.residents)
    rents = {place.id: place.rent for place in config.places if place.kind == "home"}
    wages = [occupation.wage_per_hour for occupation in occupations.values()]
    # The cheapest day's food: the helpings of ready food that make a day's need, at the price
    # the Store starts with.
    food = min(
        (item for item in config.supplied if item.ready),
        key=lambda good: good.price * round(A_DAYS_FOOD / good.nourishment),
    )
    helpings = round(A_DAYS_FOOD / food.nourishment)
    a_day = helpings * food.price
    cheapest = min(rents.values()) + a_day
    # A day's work at the lowest wage keeps the cheapest life with something over, and less than
    # half as much again; the dearest life, the dearest home and the dearest dish every day,
    # takes ten hours at the highest wage.
    assert cheapest < HOURS * min(wages) < 1.5 * cheapest
    dearest = max(rents.values()) + max(dish.price for dish in config.dishes)
    assert 9 * max(wages) < dearest <= 10 * max(wages)
    for resident in config.residents:  # a purse lasts three to six days of one's own life
        own = rents[resident.home] + a_day
        assert 3 * own <= resident.purse <= 6 * own, resident.name
    # The fund's day, everyone at work for a day, half the tasks arriving accepted from the
    # programmers, and everyone living on the cheapest food, bought in one sale each: clients,
    # rent and sales in; wages, the sums for tasks and sales and the supplier's price of the
    # food the town eats out; within a tenth of what passes through it.
    office = sum(r.occupation in ("programmer", "team-leader") for r in config.residents)
    assert config.work.tasks_a_day < office  # fewer than those who take them on
    accepted = config.work.tasks_a_day * ACCEPTED
    task = occupations["programmer"].per_service + occupations["team-leader"].per_service
    rent = sum(rents[resident.home] for resident in config.residents)
    paid_wages = HOURS * sum(occupations[r.occupation].wage_per_hour for r in config.residents)
    sales, supplier = n * a_day, n * helpings * food.wholesale
    sale_sums = n * occupations["shopkeeper"].per_service
    taken = accepted * config.work.payment + rent + sales
    paid = paid_wages + accepted * task + sale_sums + supplier
    assert abs(taken - paid) <= (taken + paid) / 10
    # With no task accepted, the fund pays out more than it takes, and its start lasts ten days.
    short = paid_wages + sale_sums + supplier - rent - sales
    assert short > 0 and config.fund.start >= 10 * short


def test_a_sum_per_service_is_at_most_a_fifth_of_what_the_customer_pays():
    config = town().town
    sums = {occupation.id: occupation.per_service for occupation in config.occupations}
    least = {
        "shopkeeper": min(item.price for item in config.supplied),
        "chef": min(dish.price for dish in config.dishes),
        "doctor": min(config.hospital.examination, config.hospital.treatment),
        "team-leader": config.work.payment,
        "mayor": 0,
    }
    for occupation, paid in least.items():
        assert sums[occupation] <= paid / 5, occupation
    assert sums["mayor"] == 0 and all(sums[o] > 0 for o in least if o != "mayor")
    # The programmers' sum is the exception, a share of the client's payment: with the leader's,
    # two fifths of it.
    assert sums["programmer"] + sums["team-leader"] <= TEAMS_SHARE * config.work.payment
