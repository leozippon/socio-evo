"""A town's configuration fails fast, and so does a world that cannot be built: before anything
is written."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.world.conftest import FakeBackend, make_agent_dirs, town_config
from world.clock import ManualClock
from world.world import World


def broken(change, **options) -> str:
    """The validation message of a configuration changed by `change`."""
    data = town_config(**options).model_dump(mode="json")
    change(data)
    with pytest.raises(ValidationError) as error:
        type(town_config()).model_validate(data)
    return str(error.value)


def test_a_town_validates():
    config = town_config()
    assert config.workplace("office").id == "workshop" and config.workplace("store").id == "store"
    assert config.travel("workshop", "cafe") == config.travel("cafe", "workshop") == 5
    assert config.travel("park", "cafe") == 10 and config.travel("park", "park") == 0
    assert config.item("bread").ready and not config.item("eggs").ready
    assert config.item("soup").ingredients == {"vegetables": 2} and config.item("soup").dish
    assert [item.id for item in config.dishes] == ["omelette", "soup"]
    assert "soup" not in [item.id for item in config.supplied]
    assert config.place("college-flat").comfort == 1.0
    assert config.needs.satiety.lowest.name == "starving"
    data = config.model_dump(mode="json")
    data["day"]["sleep_at_most"] = "05:00"  # as long as the forced sleep, 02:00 to 07:00
    assert type(config).model_validate(data).day.sleep_at_most == "05:00"
    data["day"]["delivery"] = data["work"]["arrive_from"] = "07:00"  # as the residents wake
    assert type(config).model_validate(data).day.delivery == "07:00"


@pytest.mark.parametrize(
    ("change", "options", "message"),
    [
        (
            lambda d: d["places"].append(dict(d["places"][2], id="second")),
            {},
            "a town has at most one office, not 2",
        ),
        (lambda d: d["places"].pop(5), {}, "the town has no store"),
        (lambda d: d["places"].pop(7), {}, "the town has no hall"),
        (lambda d: d["occupations"].pop(5), {}, "the hall hall is no occupation's workplace"),
        (lambda d: d["places"][2].update(kind="shop"), {}, "Input should be 'home', 'office'"),
        (lambda d: d["places"][2].update(opens="09:00"), {}, "Extra inputs are not permitted"),
        (lambda d: d["day"].update(forced_wake="7am"), {}, "HH:MM"),
        (lambda d: d["residents"][0].update(home="cafe"), {}, "is not a home"),
        (lambda d: d["residents"][1].update(name="Mei"), {}, "duplicate resident name"),
        (lambda d: d["residents"][1].update(name="you"), {}, "pattern"),
        (
            lambda d: d["routes"].append({"between": ["cafe", "moon"], "minutes": 3}),
            {},
            "two different known places",
        ),
        (lambda d: d["day"].update(checkpoint="01:00"), {}, "forced_sleep < checkpoint"),
        (lambda d: d["day"].update(forced_wake="02:15"), {}, "checkpoint < forced_wake"),
        (lambda d: d["work"].update(arrive_from="06:59"), {}, "no earlier than forced_wake"),
        (lambda d: d["work"].update(arrive_until="08:00"), {}, "a later arrive_until"),
        (lambda d: d["work"].update(tasks_a_day=-1), {}, "greater than or equal to 0"),
        (lambda d: d["day"].update(delivery="06:59"), {}, "forced_wake <= delivery"),
        (lambda d: d["day"].pop("forced_wake"), {}, "Field required"),
        (
            lambda d: d["day"].update(sleep_at_most="04:59"),
            {},
            "sleep_at_most must last at least from forced_sleep to forced_wake",
        ),
        (lambda d: d["day"].update(sleep_at_most="24:00"), {}, "HH:MM"),
        (lambda d: d["residents"][0].update(ties={"Tomas": "x"}), {}, "Extra inputs"),
        (lambda d: d["work"].update(payment=0), {}, "greater than or equal to 1"),
        (lambda d: d["residents"][0].pop("occupation"), {}, "occupation\n  Field required"),
        (lambda d: d["residents"][0].update(occupation="baker"), {}, "baker is not known"),
        (lambda d: d["occupations"][0].update(id="baker"), {}, "Input should be 'programmer'"),
        (lambda d: d["residents"][0].update(purse=-1), {}, "greater than or equal to 0"),
        (
            lambda d: d["occupations"][0].update(workplace="store"),
            {},
            "the occupation programmer works at an office, and store is not one",
        ),
        (
            lambda d: d["occupations"].pop(0),
            {},
            "the team leader leads programmers, and the town has none",
        ),
        (
            lambda d: d["occupations"].append(dict(d["occupations"][0])),
            {},
            "duplicate occupation id",
        ),
        (lambda d: d["occupations"][0].update(wage_per_hour=0), {}, "greater than or equal to 1"),
        (lambda d: d["occupations"][0].update(duty="home"), {}, "Input should be 'workplace'"),
        (lambda d: d.pop("fund"), {}, "fund\n  Field required"),
        (lambda d: d["fund"].update(start=-1), {}, "greater than or equal to 0"),
        (lambda d: d["places"][0].pop("rent"), {}, "needs rent, rooms and comfort"),
        (lambda d: d["places"][2].update(rent=5), {}, "is not a home and has no rent"),
        (lambda d: d["places"][0].update(rooms=1), {}, "has 1 rooms for 2 residents"),
        (lambda d: d["items"].append(dict(d["items"][0])), {}, "duplicate item id"),
        (lambda d: d["items"][0].pop("wholesale"), {}, "either bought from the supplier or cooked"),
        (
            lambda d: d["items"][6].update(wholesale=3),
            {},
            "either bought from the supplier or cooked",
        ),
        (lambda d: d["items"][0].update(sold_at=["store"]), {}, "Extra inputs are not permitted"),
        (
            lambda d: [
                d.update(items=d["items"][1:6]),
                d["store"]["stock"].pop("bread"),
            ],
            {},
            "the town sells nothing to eat",
        ),
        (lambda d: d["items"][0].update(kind="durable"), {}, "food is consumable"),
        (lambda d: d["items"][3].update(kind="consumable"), {}, "food is consumable"),
        (lambda d: d["items"][0].update(kind="immediate"), {}, "Input should be 'consumable'"),
        (lambda d: d["items"][0].update(fee_per_day=1), {}, "is not durable and carries no fee"),
        (lambda d: d["items"][0].pop("nourishment"), {}, "nourishment belongs to the effect food"),
        (lambda d: d["items"][0].update(nourishment=101), {}, "less than or equal to 100"),
        (lambda d: d["items"][3].update(phrase="x"), {}, "phrase belongs to the effect appearance"),
        (lambda d: d["items"][5].update(phrase=" "), {}, "has an empty phrase"),
        (lambda d: d["items"][5].update(phrase="in an honest coat"), {}, "the town does not use"),
        (lambda d: d["items"][4].update(effect="treatment"), {}, "Input should be 'food'"),
        (lambda d: d["items"][3].update(perishes=True), {}, "is not consumable and does not"),
        (
            lambda d: d["items"][6]["ingredients"].update(coat=1),
            {},
            "the dish omelette is cooked from coat, which is no food the supplier sells",
        ),
        (
            lambda d: d["items"][6]["ingredients"].update(soup=1),
            {},
            "the dish omelette is cooked from soup, which is no food the supplier sells",
        ),
        (lambda d: d["items"][7].update(nourishment=0), {}, "is a dish, which is food that is"),
        (lambda d: d["places"][3].update(id="larder"), {}, "larder names a holder of items"),
        (
            lambda d: d["store"]["stock"].update(wine=3),
            {},
            "the Store's stock has wine, which the supplier lacks",
        ),
        (
            lambda d: d["store"]["stock"].update(soup=3),
            {},
            "the Store's stock has soup, which the supplier lacks",
        ),
        (lambda d: d["store"]["stock"].update(bread=-1), {}, "greater than or equal to 0"),
        (lambda d: d.pop("needs"), {}, "needs\n  Field required"),
        (lambda d: d["needs"]["satiety"].update(per_hour=0), {}, "greater than 0"),
        (lambda d: d["needs"]["energy"].pop("sleep_per_hour"), {}, "Field required"),
        (
            lambda d: d["needs"]["energy"].update(rested_at_least=14),
            {},
            "out of its lowest band at any health",
        ),
        (lambda d: d["needs"]["health"].update(starving=-1), {}, "greater than or equal to 0"),
        (
            lambda d: d["needs"]["health"]["illness"].update(chance=1.5),
            {},
            "less than or equal to 1",
        ),
        (lambda d: d["needs"]["health"]["illness"].update(nights=0), {}, "greater than or equal"),
        (lambda d: d.pop("hospital"), {}, "hospital\n  Field required"),
        (lambda d: d["hospital"].update(treatment=0), {}, "greater than or equal to 1"),
        (lambda d: d["needs"]["satiety"]["bands"][1].update(floor=70), {}, "from the top down"),
        (lambda d: d["needs"]["satiety"]["bands"][1].update(floor=65), {}, "from the top down"),
        (
            lambda d: d["needs"]["satiety"]["bands"][3].update(floor=1),
            {},
            "lowest band begins at 0",
        ),
        (lambda d: d["needs"]["satiety"]["bands"].pop(), {}, "lowest band begins at 0"),
        (lambda d: d["needs"]["satiety"].update(bands=[]), {}, "at least 2 items"),
        (lambda d: d["needs"]["satiety"]["bands"][0].update(name="hungry"), {}, "different names"),
        (
            lambda d: d["needs"]["energy"]["bands"][0].update(name="lazy"),
            {},
            "the town does not use",
        ),
        (lambda d: d["needs"]["health"]["bands"][2].update(seen=" "), {}, "blank wording"),
        (lambda d: d["needs"]["health"]["bands"][0].update(floor=100), {}, "less than 100"),
        (lambda d: d.update(colour="red"), {}, "Extra inputs are not permitted"),
    ],
)
def test_a_bad_town_fails_with_a_clear_message(change, options, message):
    assert message in broken(change, **options)


def test_a_world_that_cannot_be_built_writes_nothing(tmp_path):
    config = town_config()
    with pytest.raises(FileNotFoundError, match="missing agent directories"):
        World(config, tmp_path, FakeBackend(), clock=ManualClock())
    make_agent_dirs(tmp_path, config)
    with pytest.raises(KeyError, match="no split"):
        World(
            config.model_copy(update={"work": config.work.model_copy(update={"split": "x"})}),
            tmp_path,
            FakeBackend(),
            clock=ManualClock(),
        )
    with pytest.raises(RuntimeError, match="not pulled"):
        World(config, tmp_path, FakeBackend(images=False), clock=ManualClock())
    with pytest.raises(ValueError, match="no tasks"):
        World(config, tmp_path, FakeBackend(tasks=0), clock=ManualClock())
    assert not (tmp_path / "world.jsonl").exists()
    World(config, tmp_path, FakeBackend(), clock=ManualClock())
    assert not (tmp_path / "world.jsonl").exists()
