"""Academy services preserve money, body and checkpoint behavior without provider agents."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from experiments.config import load_experiment
from tests.support.towns import make_agent_dirs, town_config
from world.clock import ManualClock
from world.config import TownConfig
from world.events import Bedridden, Idle, Movement, Sleep
from world.research import RESEARCH_NAMES, NoTasks
from world.world import World


@pytest.fixture
def academy(tmp_path):
    data = town_config().model_dump()
    data.update(external_services=True, research={})
    data["occupations"] = [
        {"id": "teacher", "title": "a teacher", "workplace": "workshop"},
        {"id": "student", "title": "a student", "workplace": "workshop"},
    ]
    for i, r in enumerate(data["residents"]):
        r["occupation"] = "teacher" if i == 0 else "student"
    config = TownConfig.model_validate(data)
    make_agent_dirs(tmp_path, config)
    world = World(config, tmp_path, NoTasks(), clock=ManualClock())
    world.research.initialize(world)
    for r in world.residents.values():
        r.base = Idle()
    return world


def money(world):
    return world.treasury.balance + sum(r.inventory.money for r in world.residents.values())


def offered(world, r):
    return {s.name for s in world.usable(r)}


def test_only_external_services_relax_staffing_and_research_roles_work(academy):
    data = academy.config.model_dump()
    data["external_services"] = False
    with pytest.raises(ValidationError, match="no occupation's workplace"):
        TownConfig.model_validate(data)
    for r in academy.residents.values():
        r.place = "workshop"
        assert set(RESEARCH_NAMES) <= offered(academy, r)
        assert not {"cook", "order", "examine", "treat", "grant"} & offered(academy, r)
        assert "seek_care" not in offered(academy, r)
        r.place = r.home
        assert not set(RESEARCH_NAMES) & offered(academy, r)


async def test_unlimited_external_purchase_food_and_no_negative_balance(academy):
    w, r = academy, academy.residents["Mei"]
    r.place = "store"
    before, shelves = money(w), dict(w.holders["shelves"].items)
    r.inventory.money = 500
    before = money(w)
    result = await w.call(r, "buy", {"item": "bread", "units": 25})
    assert "external service" in result.text
    assert money(w) == before - 100
    assert w.holders["shelves"].items == shelves  # no NPC stock or income
    assert "always open" in w.look(r)
    r.inventory.money = 0
    before = r.inventory.items.copy()
    assert "do not have" in (await w.call(r, "buy", {"item": "bread"})).text
    assert r.inventory.items == before and r.inventory.money == 0
    r.inventory.money = 100
    await w.call(r, "buy", {"item": "phone"})
    before = r.inventory.money
    assert "already" in (await w.call(r, "buy", {"item": "phone"})).text
    assert r.inventory.money == before
    r.place, r.living.satiety = "cafe", 0
    before = money(w)
    await w.call(r, "buy", {"item": "soup"})
    assert money(w) == before - 8
    assert r.living.satiety == 100 and r.living.eaten["soup"] == 1
    assert w.holders["portions"].items == {}


async def test_service_location_and_event_restrictions(academy):
    w, r = academy, academy.residents["Mei"]
    before = money(w)
    r.place = r.home
    assert "buy" not in offered(w, r) and "seek_care" not in offered(w, r)
    assert "not here" in (await w.call(r, "buy", {"item": "bread"})).text
    assert "Visit the Hospital" in (await w.call(r, "seek_care", {"service": "treatment"})).text
    r.place = "clinic"
    assert "seek_care" in offered(w, r)
    for event in (Sleep(0, True), Sleep(0), Movement("clinic", 1000)):
        r.base = event
        assert "seek_care" not in offered(w, r)
        await w.call(r, "seek_care", {"service": "treatment"})
    assert money(w) == before


async def test_care_restores_body_charges_outside_and_survives_checkpoint(academy, tmp_path):
    w, r = academy, academy.residents["Mei"]
    r.place, r.living.health, r.living.ill = "clinic", 40, 2
    before = money(w)
    result = await w.call(r, "seek_care", {"service": "treatment"})
    assert "external treatment" in result.text
    assert r.living.health == 65 and not r.living.ill
    assert money(w) == before - 30 and w.treasury.ledger == {}
    r.place, r.base = r.home, Bedridden()
    r.living.health, r.living.bedridden = 0, True
    r.inventory.money = 0
    assert "seek_care" in offered(w, r)
    assert "do not have" in (await w.call(r, "seek_care", {"service": "treatment"})).text
    assert r.living.health == 0 and r.living.bedridden
    r.inventory.money = 30
    await w.call(r, "seek_care", {"service": "treatment"})
    assert isinstance(r.base, Idle) and not r.living.bedridden and r.living.health == 25
    for resident in w.residents.values():
        resident.port.pending()
        resident.base = Sleep(w.clock.now() + 3600, suspended=True)
    state = json.loads(json.dumps(w.snapshot()))
    restored = World(w.config, tmp_path, NoTasks(), clock=ManualClock())
    restored.restore(state)
    assert restored.snapshot() == state
    patient = restored.residents[r.name]
    patient.place, patient.base = "clinic", Idle()
    assert "seek_care" in offered(restored, patient)
    assert restored.rules.help("hospital").startswith("At the clinic, use seek_care")


def test_academy_config_matches_the_four_town_researchers():
    root = Path(__file__).resolve().parents[2]
    academy = load_experiment(root / "experiments/configs/autoresearch-academy.yaml")
    town = load_experiment(root / "experiments/configs/autoresearch.yaml")
    office = {
        r.name: r for r in town.town.residents if r.occupation in {"programmer", "team-leader"}
    }
    assert {r.name for r in academy.town.residents} == set(office)
    assert [r.occupation for r in academy.town.residents].count("teacher") == 1
    assert [r.occupation for r in academy.town.residents].count("student") == 3
    for r in academy.town.residents:
        assert (r.home, r.purse) == (office[r.name].home, office[r.name].purse)
    assert academy.town.research == town.town.research
    assert academy.llm == town.llm
    assert all(r.background_path.is_file() for r in academy.residents)
