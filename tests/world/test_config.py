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


@pytest.mark.parametrize(
    ("change", "options", "message"),
    [
        (
            lambda d: d["places"].append(dict(d["places"][2], id="second")),
            {},
            "exactly one workplace",
        ),
        (lambda d: d["places"][2].update(opens="18:00", closes="09:00"), {}, "open before"),
        (
            lambda d: d["places"][3].update(opens="08:00", closes="20:00"),
            {},
            "only the workplace has opening hours",
        ),
        (lambda d: d["places"][2].update(opens="9am"), {}, "HH:MM"),
        (lambda d: d["residents"][0].update(home="cafe"), {}, "is not a home"),
        (lambda d: d["residents"][1].update(name="Mei"), {}, "duplicate resident name"),
        (lambda d: d["residents"][1].update(name="you"), {}, "pattern"),
        (
            lambda d: d["routes"].append({"between": ["cafe", "moon"], "minutes": 3}),
            {},
            "two different known places",
        ),
        (lambda d: d["day"].update(checkpoint="01:00"), {}, "forced_sleep < checkpoint"),
        (lambda d: d["day"].update(wake_earliest="09:30"), {}, "workplace opens"),
        (lambda d: d["social"].update(exchange=B_EXCHANGE), {}, "isolated mode"),
        (
            lambda d: d["social"]["exchange"].update(place="park", at="17:00"),
            {"mode": "isolated", "exchange": B_EXCHANGE},
            "after the workplace closes",
        ),
        (
            lambda d: d["social"]["exchange"].update(place="workshop"),
            {"mode": "isolated", "exchange": B_EXCHANGE},
            "not a social place",
        ),
        (lambda d: d["work"].update(payment=0), {}, "greater than or equal to 1"),
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
