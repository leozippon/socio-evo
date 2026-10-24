"""The experiments' configurations: the four groups and the smoke town over the shared town, the
overlay rule, and the residents' backgrounds."""

from __future__ import annotations

import pytest

from agent.wording import offences
from experiments.config import PROJECT_ROOT, load_experiment, overlay
from infrastructure.config import ConfigError

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
    common = {"name", "town", "skills_writable"}
    for g in (a, b, d):
        assert g.model_dump(exclude=common) == c.model_dump(exclude=common)
        social = {"social"}
        assert g.town.model_dump(exclude=social) == c.town.model_dump(exclude=social)
    assert c.days == 28 and len(c.residents) == 8 and c.runtime.reasoning_effort == "low"
    assert c.llm.max_concurrency == len(c.residents)
    assert c.town.start_date.strftime("%A %d %B %Y") == "Monday 02 March 2026"


def test_the_smoke_town_is_two_residents_of_group_c_for_a_day():
    smoke, c = load_experiment(CONFIGS / "smoke.yaml"), group("c")
    assert [r.name for r in smoke.residents] == [r.name for r in smoke.town.residents]
    assert [r.name for r in smoke.residents] == ["Mei", "Tomas"]
    assert smoke.days == 1 and smoke.town.clock.speed_active == 8
    assert smoke.town.social == c.town.social and smoke.skills_writable
    assert smoke.town.clock.speed_idle == c.town.clock.speed_idle


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


def test_backgrounds_are_second_person_circumstances_without_trait_words():
    config = group("c")
    for resident in config.residents:
        text = resident.background_path.read_text(encoding="utf-8")
        assert text.startswith(f"You are {resident.name}, "), resident.name
        assert offences(text) == [], resident.name
        others = [r.name for r in config.residents if r.name != resident.name]
        assert not [name for name in others if name in text], resident.name
