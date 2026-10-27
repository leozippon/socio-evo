"""The experiments' configurations: the four groups and the smoke town over the shared town, the
overlay rule, and the residents' backgrounds."""

from __future__ import annotations

import re

import pytest
import yaml

from agent.wording import offences
from experiments.config import PROJECT_ROOT, ExperimentConfig, load_experiment, overlay
from infrastructure.config import ConfigError, load_config
from world.rules import Rules

CONFIGS = PROJECT_ROOT / "experiments" / "configs"


def group(name: str):
    return load_experiment(CONFIGS / "groups" / f"{name}.yaml")


def test_the_four_groups_share_the_town_and_differ_only_in_their_rules():
    a, b, c, d = (group(name) for name in "abcd")
    assert (a.name, b.name, c.name, d.name) == ("a", "b", "c", "d")
    assert [g.town.social.mode for g in (a, b, c, d)] == ["isolated", "isolated", "town", "town"]
    exchange = b.town.social.exchange
    assert exchange is not None and (exchange.at, exchange.place, exchange.messages) == (
        "19:00",
        "cafe",
        8,
    )
    assert a.town.social.exchange is c.town.social.exchange is d.town.social.exchange is None
    assert [g.skills_writable for g in (a, b, c, d)] == [True, True, True, False]
    assert not d.town.social.skills_shareable and c.town.social.skills_shareable
    assert [g.town.work.for_two for g in (a, b, c, d)] == [0, 0, 0.25, 0.25]  # a board of one's own
    assert [g.town.work.projects_a_day for g in (a, b, c, d)] == [0, 0, 2, 2]  # likewise
    common = {"name", "town", "skills_writable"}
    for g in (a, b, d):
        assert g.model_dump(exclude=common) == c.model_dump(exclude=common)
        rules = {"social", "work"}
        assert g.town.model_dump(exclude=rules) == c.town.model_dump(exclude=rules)
        shared = {"for_two": c.town.work.for_two, "projects_a_day": c.town.work.projects_a_day}
        assert g.town.work.model_copy(update=shared) == c.town.work
    assert c.days == 28 and len(c.residents) == 8 and c.runtime.reasoning_effort == "low"
    assert c.llm.max_concurrency == len(c.residents)
    assert c.town.start_date.strftime("%A %d %B %Y") == "Monday 02 March 2026"


def test_the_smoke_town_is_two_residents_of_group_c_for_a_day():
    smoke, c = load_experiment(CONFIGS / "smoke.yaml"), group("c")
    assert [r.name for r in smoke.residents] == [r.name for r in smoke.town.residents]
    assert [r.name for r in smoke.residents] == ["Mei", "Tomas"]
    assert smoke.days == 1 and smoke.town.clock == c.town.clock
    assert smoke.town.social == c.town.social and smoke.skills_writable


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
        f"base: {CONFIGS / 'groups' / 'c.yaml'}\n"
        "residents: [{name: Zoe, background: experiments/residents/mei.md}]\n"
    )
    with pytest.raises(ConfigError, match=r"stranger\.yaml: .*not exactly the town's residents"):
        load_experiment(stranger)
    sharing = tmp_path / "sharing.yaml"
    sharing.write_text(f"base: {CONFIGS / 'groups' / 'c.yaml'}\nskills_writable: false\n")
    with pytest.raises(ConfigError, match="cannot be passed skills"):
        load_experiment(sharing)
    with pytest.raises(ConfigError):  # the shared town names no group
        load_experiment(CONFIGS / "town.yaml")


def test_the_compaction_threshold_is_bounded_by_the_models_context_window(tmp_path):
    c = group("c")
    # A context just past the threshold, grown by a reply and a margin, leaves the notes room.
    assert (c.llm.context_window, c.runtime.ceiling(c.llm.context_window)) == (262_144, 229_376)
    assert c.runtime.compaction_threshold == 225_000
    at, above = tmp_path / "at.yaml", tmp_path / "above.yaml"
    for path, threshold in ((at, 229_376), (above, 229_377)):
        base = CONFIGS / "groups" / "c.yaml"
        path.write_text(f"base: {base}\nruntime: {{compaction_threshold: {threshold}}}\n")
    assert load_experiment(at).runtime.compaction_threshold == 229_376
    with pytest.raises(ConfigError, match="229377 is above 229376, the most that"):
        load_experiment(above)


def test_a_count_of_exchanges_kept_is_refused_and_set_aside_only_in_a_record_made_before(tmp_path):
    counted = tmp_path / "counted.yaml"
    counted.write_text(f"base: {CONFIGS / 'groups' / 'c.yaml'}\nruntime: {{kept_exchanges: 6}}\n")
    refusal = "kept_exchanges is no longer a setting: kept_tokens replaced it"
    with pytest.raises(ConfigError, match=refusal):
        load_experiment(counted)
    # A run frozen before kept_tokens named the count, and no kept_tokens.
    frozen = group("c").model_dump(mode="json")
    del frozen["runtime"]["kept_tokens"]
    frozen["runtime"]["kept_exchanges"] = 6
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(frozen))
    with pytest.raises(ConfigError, match=refusal):
        load_config(path, ExperimentConfig)
    assert load_config(path, ExperimentConfig, record=True) == group("c")


def test_backgrounds_are_first_person_circumstances_without_trait_words():
    config = group("c")
    assert len(config.residents) == 8
    for resident in config.residents:
        text = resident.background_path.read_text(encoding="utf-8")
        assert text.startswith(f"I am {resident.name}, "), resident.name
        assert not re.search(r"\byou\b|\byours?\b", text, re.IGNORECASE), resident.name
        assert offences(text) == [], resident.name
        others = [r.name for r in config.residents if r.name != resident.name]
        assert not [name for name in others if name in text], resident.name


def test_ties_are_mutual_pass_the_guard_and_reach_only_the_town_groups():
    c, a = group("c"), group("a")
    residents = {r.name: r for r in c.town.residents}
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
    for g in (a, group("b"), c, group("d")):
        rules = Rules(g.town)
        for name in residents:
            for text in (rules.text(name), rules.people_notes(name)):
                assert offences(text) == [], (g.name, name, offences(text))
    for name, resident in residents.items():
        for how in resident.ties.values():
            assert how in Rules(c.town).text(name) and how in Rules(c.town).people_notes(name)
            assert how not in Rules(a.town).text(name)
        assert Rules(a.town).people_notes(name) == "# People\n"


CLEARED = 0.5  # the share of the board paid in a day at the local model's pace (29 of 56 on the town's first day)


def test_the_pay_is_set_against_the_towns_shared_board():
    town = group("c").town
    payment, n = town.work.payment, len(town.residents)
    rents = {place.id: place.rent for place in town.places if place.kind == "home"}
    food = [good for good in town.goods if good.effect == "food"]
    meals = [good.price for good in food if good.kind == "immediate"]
    a_day = min([good.price // good.days for good in food if good.kind == "consumable"] + meals)
    cheapest = min(rents.values()) + a_day
    assert payment < cheapest <= 1.5 * payment  # one task does not keep the cheapest life; one and a half do
    for resident in town.residents:  # and a purse lasts three to six days of one's own life
        own = rents[resident.home] + a_day
        assert 3 * own <= resident.purse <= 6 * own, resident.name
    # The board of the day is the town's pot if it were cleared; the local model clears about
    # half of it (29 of 56 accepted on the town's first day), which pays for the town's rent and
    # food with a margin, but less than twice its cheapest costs, so the slow fall behind.
    pot = town.work.board_size * payment * CLEARED
    rent = sum(rents[resident.home] for resident in town.residents)
    assert rent + n * max(meals) < pot < 2 * (rent + n * a_day)
    # What an average share saves over the cheapest life in one's own home buys the dearest
    # durable, which no purse covers at the start, in about a week; daily charges are small.
    saved = pot / n - (rent / n + a_day)
    durables = [good for good in town.goods if good.kind == "durable"]
    dearest = max(good.price for good in durables)
    assert dearest > max(resident.purse for resident in town.residents)
    assert 5 <= dearest / saved <= 10
    assert all(good.fee_per_day <= saved / 5 for good in durables)
