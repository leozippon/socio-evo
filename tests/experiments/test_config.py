"""The experiments' configurations: the town, the run and the smoke town over it, the overlay
rule, and the residents' backgrounds."""

from __future__ import annotations

import re

import pytest
import yaml

from agent.wording import offences
from experiments.config import PROJECT_ROOT, ExperimentConfig, load_experiment, overlay
from infrastructure.config import ConfigError, load_config
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
    assert run.town.start_date.isoformat() == "2026-10-27"
    assert run.model_dump(exclude={"town"}) == found.model_dump(exclude={"town"})
    assert run.town.model_dump(exclude={"start_date"}) == found.town.model_dump(
        exclude={"start_date"}
    )


def test_the_smoke_town_is_two_residents_of_the_town_for_a_day():
    smoke, found = load_experiment(CONFIGS / "smoke.yaml"), town()
    assert [r.name for r in smoke.residents] == [r.name for r in smoke.town.residents]
    assert [r.name for r in smoke.residents] == ["Mei", "Tomas"]
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


def test_backgrounds_are_first_person_circumstances_without_trait_words():
    config = town()
    assert len(config.residents) == 8
    for resident in config.residents:
        text = resident.background_path.read_text(encoding="utf-8")
        assert text.startswith(f"I am {resident.name}, "), resident.name
        assert not re.search(r"\byou\b|\byours?\b", text, re.IGNORECASE), resident.name
        assert offences(text) == [], resident.name
        others = [r.name for r in config.residents if r.name != resident.name]
        assert not [name for name in others if name in text], resident.name


def test_ties_are_mutual_pass_the_guard_and_reach_everyone():
    config = town().town
    residents = {r.name: r for r in config.residents}
    for resident in residents.values():
        assert 1 <= len(resident.ties) <= 2, resident.name
        for other, how in resident.ties.items():
            assert how.startswith(other), (resident.name, other)
            assert resident.name in residents[other].ties  # mutual, as the configuration demands
    known = {name: set(resident.ties) for name, resident in residents.items()}
    reached, frontier = set(), {"Mei"}
    while frontier:
        reached |= frontier
        frontier = {other for name in frontier for other in known[name]} - reached
    assert reached == set(residents)  # everyone is reachable through someone they know
    rules = Rules(config)
    for name, resident in residents.items():
        text = rules.text(name)
        assert offences(text) == [], (name, offences(text))
        for how in resident.ties.values():
            assert how in text


# The share of the board paid in a day at the local model's pace: 12 and 13 of 56 on the first two
# days of the fourth start, on the pool of 1,912 tasks.
CLEARED = 0.25


def test_the_pay_is_set_against_the_towns_shared_board():
    config = town().town
    payment, n = config.work.payment, len(config.residents)
    rents = {place.id: place.rent for place in config.places if place.kind == "home"}
    food = [good for good in config.goods if good.effect == "food"]
    meals = [good.price for good in food if good.kind == "immediate"]
    a_day = min([good.price // good.days for good in food if good.kind == "consumable"] + meals)
    cheapest = min(rents.values()) + a_day
    dearest = max(rents.values()) + max(meals + [a_day])  # the cottage and suppers at the Anchor
    # One task keeps the cheapest life and not the dearest; a task and a half keeps the dearest.
    assert cheapest <= payment < dearest <= 1.5 * payment
    for resident in config.residents:  # and a purse lasts three to six days of one's own life
        own = rents[resident.home] + a_day
        assert 3 * own <= resident.purse <= 6 * own, resident.name
    # The board of the day is the town's pot if it were cleared; the local model clears about a
    # quarter of it (12 and 13 of 56 accepted on the fourth start's first two days), which pays
    # for the town's rent and food with a margin, but less than twice its cheapest costs, so the
    # slow fall behind.
    pot = config.work.board_size * payment * CLEARED
    rent = sum(rents[resident.home] for resident in config.residents)
    assert rent + n * max(meals) < pot < 2 * (rent + n * a_day)
    # What an average share saves over the cheapest life in one's own home buys the dearest
    # durable, which no purse covers at the start, in about a week; daily charges are small.
    saved = pot / n - (rent / n + a_day)
    durables = [good for good in config.goods if good.kind == "durable"]
    priciest = max(good.price for good in durables)
    assert priciest > max(resident.purse for resident in config.residents)
    assert 5 <= priciest / saved <= 10
    assert all(good.fee_per_day <= saved / 5 for good in durables)
