"""The experiments' configurations: the town, the three arms and the smoke town over it, the
overlay rule, and the residents' backgrounds."""

from __future__ import annotations

import re
from statistics import fmean

import pytest
from pydantic import ValidationError

from agent.wording import offences
from experiments.config import PROJECT_ROOT, load_experiment, overlay
from infrastructure.config import ConfigError
from learning.config import LearningConfig
from world.body import Body, Living
from world.config import A_DAYS_FOOD, SEARCH_KEY, Drop
from world.occupations import OCCUPATIONS
from world.rules import Rules

CONFIGS = PROJECT_ROOT / "experiments" / "configs"
ARMS = {
    "social": ("generalised", "resident"),
    "raw": ("raw", "resident"),
    "random": ("generalised", "random"),
}
"""The arms of the design (docs/experimental-design.md): what each learns from, who chooses."""
TRAINABLE = {
    *("q_proj", "k_proj", "v_proj", "o_proj", "in_proj_qkv", "in_proj_z", "out_proj"),
    *("gate_proj", "up_proj", "down_proj"),
}
"""The projections the server can apply an adapter to (`learning.train`, TARGETS)."""


@pytest.fixture(autouse=True)
def search_key(monkeypatch):
    """The town has the web, which needs the search key to load (any key will do here)."""
    monkeypatch.setenv(SEARCH_KEY, "a key")


def town():
    return load_experiment(CONFIGS / "town.yaml")


def test_the_town_and_the_three_arms_over_it_which_differ_only_in_what_they_learn():
    found = town()
    assert found.name == "town" and not found.learning.enabled
    assert found.days == 28 and len(found.residents) == 11 and found.town.web.enabled
    assert len(found.town.incidents) == found.days  # about one a day, from incidents.yaml
    assert found.runtime.reasoning_effort == "low"
    assert found.llm.max_concurrency == len(found.residents)
    assert found.town.start_date.strftime("%A %d %B %Y") == "Monday 02 March 2026"
    arms = {name: load_experiment(CONFIGS / "arms" / f"{name}.yaml") for name in ARMS}
    assert {name: (a.learning.examples, a.learning.choice) for name, a in arms.items()} == ARMS
    for name, arm in arms.items():
        assert arm.name == name and arm.learning.enabled
        assert arm.model_dump(exclude={"name", "learning"}) == found.model_dump(
            exclude={"name", "learning"}
        )
        same = {"examples", "choice"}
        assert arm.learning.model_dump(exclude=same) == arms["social"].learning.model_dump(
            exclude=same
        )
    assert sorted(path.stem for path in (CONFIGS / "arms").glob("*.yaml")) == sorted(ARMS)


def test_the_learning_settings_are_those_the_trainer_takes():
    learning = load_experiment(CONFIGS / "arms" / "social.yaml").learning
    assert set(learning.lora.target_modules) <= TRAINABLE
    assert learning.trainer.executable.is_absolute() and learning.trainer.gpus
    assert learning.keep_per_night == 8 and learning.dataset_max >= learning.keep_per_night
    # One conversation a step, as long as the longest moments as they happened, within what one
    # card holds; a configuration asking a step for more is refused.
    lora, trainer = learning.lora, learning.trainer
    assert (lora.batch_size, lora.max_length, trainer.step_tokens) == (1, 8192, 8192)
    asked = learning.model_dump() | {"lora": lora.model_dump() | {"batch_size": 4}}
    with pytest.raises(
        ValidationError, match="batch_size 4 times max_length 8192 is more than the"
    ):
        LearningConfig.model_validate(asked)
    asked["trainer"] = trainer.model_dump() | {"step_tokens": 32_768}
    assert LearningConfig.model_validate(asked).lora.batch_size == 4


def test_the_smoke_town_is_a_few_of_the_town_with_a_newcomer_for_two_days_and_their_incidents():
    smoke, found = load_experiment(CONFIGS / "smoke.yaml"), town()
    assert [r.name for r in smoke.residents] == [r.name for r in smoke.town.residents]
    assert [(r.name, r.occupation, r.newcomer) for r in smoke.town.residents] == [
        ("Mei", "team-leader", False),
        ("Aisha", "programmer", False),
        ("Olga", "shopkeeper", False),
        ("Jonas", "chef", False),
        ("Lucia", "doctor", False),
        ("Marek", None, True),
    ]
    # Each as in the town: its home, its money, and whom it likes, as far as they are here.
    names = {r.name for r in smoke.town.residents}
    residents = {r.name: r for r in found.town.residents}
    for r in smoke.town.residents:
        assert (r.home, r.purse) == (residents[r.name].home, residents[r.name].purse), r.name
        assert r.likes == tuple(n for n in residents[r.name].likes if n in names), r.name
    assert {r.name: r.background for r in smoke.residents} == {
        r.name: r.background for r in found.residents if r.name in names
    }
    assert smoke.days == 2 and smoke.town.clock == found.town.clock
    assert smoke.town.social == found.town.social and smoke.town.work == found.town.work
    assert smoke.town.web == found.town.web
    # The incidents of its two days, as the town has them, to and from its residents.
    assert smoke.town.incidents == tuple(i for i in found.town.incidents if i.day <= smoke.days)
    for incident in smoke.town.incidents:
        reached = {told.to for told in incident.percepts}
        reached |= {effect.who for effect in incident.effects if isinstance(effect, Drop)}
        assert reached and reached <= names, incident.id
    social = load_experiment(CONFIGS / "arms" / "social.yaml")
    assert smoke.learning == social.learning  # and its nights, as the Social arm lives them


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
    newcomers = {r.name for r in config.town.residents if r.newcomer}
    assert len(config.residents) == 11 and newcomers == {"Marek", "Ines", "Selin"}
    named = dict.fromkeys((r.name for r in config.residents), 0)
    for resident in config.residents:
        text = resident.background_path.read_text(encoding="utf-8")
        assert text.startswith(f"I am {resident.name}, "), resident.name
        assert not re.search(r"\byou\b|\byours?\b", text, re.IGNORECASE), resident.name
        assert offences(text) == [], resident.name
        for other in named:
            if resident.name not in newcomers and other != resident.name:
                named[other] += bool(re.search(rf"\b{other}\b", text))
    # Each of the eight is in the history of at least two others of the eight; the newcomers,
    # newly come, are in none of theirs.
    assert all(named[name] >= 2 for name in named if name not in newcomers), named
    assert all(named[name] == 0 for name in newcomers), named


def test_the_rules_are_about_three_thousand_characters_and_pass_the_guard():
    config = town().town
    rules = Rules(config)
    for resident in config.residents:
        text = rules.text(resident.name)
        assert 2500 <= len(text) <= 3500, (resident.name, len(text))
        assert offences(text) == [], (resident.name, offences(text))
        assert text.split("\n\n")[1].startswith("Work. You are ")  # its occupation and workplace


# The calibration of the closed economy (experiments/configs/town.yaml's notes): three tasks
# arriving a day, half accepted, among the three programmers, the team leader taking none; five
# dishes sold a day at the Linde, the menu's in turn, and the chef's own, the two others eating
# bread; the cases of illness the town in good health sees a day, each examined and treated at
# the surgery.
ACCEPTED = 0.5
SOLD = 5


def test_rent_food_shares_margins_and_the_treasury_are_set_against_one_another():
    config = town().town
    assert {o.id for o in config.occupations} == set(OCCUPATIONS)  # the six of the design
    tax, work = config.tax, config.work
    rents = {place.id: place.rent for place in config.places if place.kind == "home"}
    assert sorted(set(rents.values())) == [5, 8, 10]  # a room, a flat, the cottage
    # The cheapest day's food: the helpings of ready food that make a day's need, at the price
    # the Store starts with; the dearest, the dearest dish.
    food = min(
        (item for item in config.supplied if item.ready),
        key=lambda good: good.price * round(A_DAYS_FOOD / good.nourishment),
    )
    helpings = round(A_DAYS_FOOD / food.nourishment)
    a_day = helpings * food.price
    cheapest = min(rents.values()) + a_day
    dearest = max(rents.values()) + max(dish.price for dish in config.dishes)
    assert (cheapest, dearest) == (20, 30)
    assert config.treasury.spares >= a_day  # rent never takes a day's bread

    # The clients' payments, shared out after the tax: a programmer's expected share, the
    # accepted tasks among the programmers, and the team leader's fifth of them all.
    office = [
        r.occupation for r in config.residents if r.occupation in ("programmer", "team-leader")
    ]
    assert work.tasks_a_day < len(office)  # fewer than those at the Office
    clients = work.tasks_a_day * ACCEPTED * work.payment
    programmers = office.count("programmer")
    programmer = clients * (1 - work.leader_share) * (1 - tax) / programmers
    leader = clients * work.leader_share * (1 - tax)
    assert (programmers, round(programmer, 2), round(leader, 2)) == (3, 54, 40.5)
    assert programmer >= dearest and leader >= dearest

    # The businesses' margins after the tax: the chef's on the dishes sold, the menu's mean less
    # its ingredients at the Store; the shopkeeper's on the town's food, the ingredients of the
    # dishes sold and of the chef's own at the Store's prices less the supplier's, and the
    # helpings of bread of the two who do not eat at the Linde. The Store's markup on
    # ingredients is about half again over wholesale.
    def cost(dish, price) -> float:
        return sum(units * price(config.item(item)) for item, units in dish.ingredients.items())

    ingredients = [item for item in config.supplied if item.effect == "food" and not item.ready]
    assert all(item.price <= 2 * item.wholesale for item in ingredients)
    menu = fmean(dish.price for dish in config.dishes)
    retail = fmean(cost(dish, lambda item: item.price) for dish in config.dishes)
    wholesale = fmean(cost(dish, lambda item: item.wholesale) for dish in config.dishes)
    meals = len(config.residents)
    dishes = SOLD + 1  # and the chef's own
    bread = helpings * (meals - dishes)
    chef = SOLD * (menu * (1 - tax) - retail)
    shop = dishes * (retail * (1 - tax) - wholesale) + bread * (
        food.price * (1 - tax) - food.wholesale
    )
    assert (round(menu, 2), round(retail, 2), round(wholesale, 2)) == (17.5, 6, 3.17)
    assert (round(chef, 2), round(shop, 2)) == (48.75, 28.4)
    assert chef >= dearest
    # The shopkeeper's keeps the cheapest life, hers in a shared house; the dearest would take
    # a dearer loaf.
    assert cheapest <= shop < dearest
    # The doctor's patients: the cases of illness the town in good health sees a day, by the
    # chance of each resident's home, about one, each examined and treated (about two visits);
    # their fees keep the dearest life.
    body, comfort = Body(config.needs), {place.id: place.comfort for place in config.places}
    cases = sum(body.illness_chance(Living(), comfort[r.home]) for r in config.residents)
    fees = config.hospital
    doctor = cases * (fees.examination + fees.treatment) * (1 - tax)
    assert (round(cases, 2), fees.examination, fees.treatment, round(doctor, 2)) == (
        1.0, 20, 40, 54,
    )  # fmt: skip
    assert doctor >= dearest

    # The treasury's day: the rent of every room taken and the tax on the day's payments in,
    # the mayor's salary out. Its intake is near the salary: it covers it, and what is left,
    # the mayor's to grant back, is less than the salary.
    rent = sum(rents[r.home] for r in config.residents)
    sales = dishes * retail + bread * food.price
    taxes = tax * (clients + sales + SOLD * menu + cases * (fees.examination + fees.treatment))
    salary = sum(config.occupation(r.occupation).salary for r in config.residents)
    intake = rent + taxes
    assert (rent, round(taxes, 2), salary) == (54, 43.85, 60)
    assert 0 < intake - salary < salary
    assert config.treasury.start >= 5 * salary
    # The town's money grows by what the clients pay less what the supplier is paid.
    supplier = dishes * wholesale + bread * food.wholesale
    assert round(clients - supplier, 2) == 194

    # Starting money is five to ten days of its owner's own life, its rent and a day's bread;
    # the chef's and the shopkeeper's working capital set apart: a day of the kitchen's
    # ingredients at the Store, and the food on the starting shelves twice over at wholesale.
    shelves = sum(
        units * config.item(item).wholesale  # type: ignore[operator]
        for item, units in config.store.stock.items()
        if config.item(item).effect == "food"
    )
    capital = {"chef": dishes * retail, "shopkeeper": 2 * shelves}
    assert capital == {"chef": 36, "shopkeeper": 352}
    for resident in config.residents:
        own = rents[resident.home] + a_day
        days = (resident.purse - capital.get(resident.occupation, 0)) / own
        assert 5 <= days <= 10, (resident.name, days)
