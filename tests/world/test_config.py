"""A town's configuration fails fast, and so does a world that cannot be built: before anything
is written."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.world.conftest import B_EXCHANGE, FakeBackend, make_agent_dirs, town_config
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
    config = town_config("isolated", exchange=B_EXCHANGE)
    assert config.workplace.id == "workshop"
    assert config.travel("workshop", "cafe") == config.travel("cafe", "workshop") == 5
    assert config.travel("park", "cafe") == 10 and config.travel("park", "park") == 0
    assert config.good("groceries").days == 3 and config.place("college-flat").comfort == 1.0
    alone = ["groceries", "meal", "bicycle", "coat", "examination", "treatment"]
    assert [g.id for g in config.for_sale()] == alone  # nothing to write with
    everything = ["groceries", "meal", "bicycle", "phone", "coat", "examination", "treatment"]
    assert [g.id for g in town_config().for_sale()] == everything
    assert config.needs.satiety.lowest.name == "starving"
    data = config.model_dump(mode="json")
    data["social"]["exchange"]["at"] = "01:00"  # after midnight, before the forced sleep
    assert type(config).model_validate(data).social.exchange.at == "01:00"
    data["day"]["sleep_at_most"] = "05:00"  # as long as the forced sleep, 02:00 to 07:00
    assert type(config).model_validate(data).day.sleep_at_most == "05:00"
    data["day"]["board_posted"] = "07:00"  # as the residents wake
    assert type(config).model_validate(data).day.board_posted == "07:00"


@pytest.mark.parametrize(
    ("change", "options", "message"),
    [
        (
            lambda d: d["places"].append(dict(d["places"][2], id="second")),
            {},
            "exactly one workplace",
        ),
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
        (lambda d: d["day"].update(board_posted="06:59"), {}, "forced_wake <= board_posted"),
        (lambda d: d["day"].pop("forced_wake"), {}, "Field required"),
        (
            lambda d: d["day"].update(sleep_at_most="04:59"),
            {},
            "sleep_at_most must last at least from forced_sleep to forced_wake",
        ),
        (lambda d: d["day"].update(sleep_at_most="24:00"), {}, "HH:MM"),
        (lambda d: d["social"].update(exchange=B_EXCHANGE), {}, "isolated mode"),
        (
            lambda d: d["social"]["exchange"].update(at="02:15"),
            {"mode": "isolated", "exchange": B_EXCHANGE},
            "must come before the forced sleep",
        ),
        (
            lambda d: d["social"]["exchange"].update(place="workshop"),
            {"mode": "isolated", "exchange": B_EXCHANGE},
            "not a social place",
        ),
        (
            lambda d: d["residents"][0].update(ties={"Tomas": "Tomas lives up the hill."}),
            {},
            "Mei's tie to Tomas is not mutual",
        ),
        (lambda d: d["residents"][0].update(ties={"Zoe": "Zoe."}), {}, "no other resident"),
        (lambda d: d["residents"][0].update(ties={"Mei": "Me."}), {}, "no other resident"),
        (
            lambda d: [
                d["residents"][0].update(ties={"Tomas": " "}),
                d["residents"][1].update(ties={"Mei": "Mei."}),
            ],
            {},
            "Mei's tie to Tomas says nothing",
        ),
        (lambda d: d["work"].update(payment=0), {}, "greater than or equal to 1"),
        (lambda d: d["places"][0].pop("rent"), {}, "needs rent, rooms and comfort"),
        (lambda d: d["places"][2].update(rent=5), {}, "is not a home and has no rent"),
        (lambda d: d["places"][0].update(rooms=1), {}, "has 1 rooms for 2 residents"),
        (lambda d: d["goods"].append(dict(d["goods"][0])), {}, "duplicate good id"),
        (lambda d: d["goods"][0].update(sold_at=["workshop"]), {}, "not a shop or social place"),
        (lambda d: d["goods"][0].update(sold_at=[]), {}, "at least 1 item"),
        (lambda d: d.update(goods=[d["goods"][2]]), {}, "sells nothing to eat"),
        (lambda d: d["goods"][0].pop("uses"), {}, "needs uses and per_day"),
        (lambda d: d["goods"][0].update(per_day=10), {}, "uses more a day than one purchase holds"),
        (lambda d: d["goods"][1].update(uses=2), {}, "is not consumable and has no uses"),
        (lambda d: d["goods"][1].update(fee_per_day=1), {}, "is not durable and carries no fee"),
        (lambda d: d["goods"][2].update(effect="food"), {}, "is food and so is consumable"),
        (lambda d: d["goods"][1].update(effect="travel"), {}, "which only a durable has"),
        (lambda d: d["goods"][0].pop("nourishment"), {}, "nourishment belongs to the effect food"),
        (lambda d: d["goods"][2].update(phrase="x"), {}, "phrase belongs to the effect appearance"),
        (lambda d: d["goods"][4].update(phrase=" "), {}, "has an empty phrase"),
        (lambda d: d["goods"][4].update(phrase="in an honest coat"), {}, "the town does not use"),
        (lambda d: d["goods"][5].update(kind="durable"), {}, "which only an immediate has"),
        (
            lambda d: d["goods"][5].update(restores=5),
            {},
            "restores belongs to the effect treatment",
        ),
        (lambda d: d["goods"][6].pop("restores"), {}, "restores belongs to the effect treatment"),
        (lambda d: d.pop("needs"), {}, "needs\n  Field required"),
        (lambda d: d["needs"]["satiety"].update(per_hour=0), {}, "greater than 0"),
        (lambda d: d["needs"]["energy"].pop("sleep_per_hour"), {}, "Field required"),
        (lambda d: d["needs"]["health"].update(starving=-1), {}, "greater than or equal to 0"),
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
