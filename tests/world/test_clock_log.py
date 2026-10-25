"""The clock's speeds and how a moment is told; the world log's sequence across a resumption."""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import world.clock
from world.clock import Clock, ManualClock, parse_hour, tell_moment
from world.config import ClockSettings
from world.log import WorldLog

EIGHT = "ABCDEFGH"


def eight_residents() -> Clock:
    """A clock of eight residents whose busy speed falls by 4 with every resident busy."""
    return Clock(1000, len(EIGHT), speed_idle=100, speed_busy_one=36, speed_busy_all=8)


def make_busy(clock: Clock, names: str) -> None:
    """Tell `clock` that exactly the residents `names` are busy."""
    for name in EIGHT:
        clock.set_busy(name, name in names)


def test_a_moment_is_told_by_weekday_date_and_hour():
    start = date(2026, 3, 2)  # a Monday
    assert tell_moment(4 * 86_400 + parse_hour("14:05"), start) == "Friday 6 March, 14:05"
    assert tell_moment(0, start) == "Monday 2 March, 00:00"
    with pytest.raises(ValueError):
        parse_hour("24:00")


def test_the_speed_falls_linearly_from_one_busy_resident_to_all():
    clock = eight_residents()
    speeds = []
    for k in range(len(EIGHT) + 1):
        make_busy(clock, EIGHT[:k])
        assert clock.busy_count == k
        speeds.append(clock.speed)
    assert speeds == [100, 36, 32, 28, 24, 20, 16, 12, 8]
    with clock.hold():
        assert clock.speed == 0
    alone = Clock(0, 1, speed_idle=100, speed_busy_one=36, speed_busy_all=8)
    alone.set_busy("Mei", True)
    assert alone.speed == 36


def test_simulated_time_is_exact_across_every_change_of_speed(monkeypatch):
    real = 0.0
    monkeypatch.setattr(world.clock, "time", SimpleNamespace(monotonic=lambda: real))
    clock = eight_residents()
    expected = 1000.0
    for busy, speed, seconds in [
        ("", 100, 10),
        ("A", 36, 5),
        ("ABCD", 24, 2.5),
        ("ABCDEFGH", 8, 1),
        ("H", 36, 3),
        ("", 100, 4),
    ]:
        make_busy(clock, busy)
        assert clock.speed == speed
        real += seconds
        expected += speed * seconds
        assert clock.now() == expected
    make_busy(clock, "AB")
    with clock.hold():
        real += 50
        assert clock.now() == expected
    real += 2
    assert clock.speed == 32 and clock.now() == expected + 64


def test_telling_the_clock_twice_changes_nothing():
    clock = eight_residents()
    clock.set_busy("A", True)
    clock.set_busy("A", True)
    clock.set_busy("B", False)
    assert clock.busy_count == 1 and clock.speed == 36
    clock.set_busy("A", False)
    assert clock.busy_count == 0 and clock.speed == 100


async def test_a_sleeper_reconsiders_its_wait_when_the_speed_changes():
    clock = Clock(0, 2, speed_idle=1000, speed_busy_one=1, speed_busy_all=1)
    clock.set_busy("Mei", True)  # at speed 1, 50 seconds away
    sleeper = asyncio.create_task(clock.sleep_until(50))
    await asyncio.sleep(0.01)
    assert not sleeper.done()
    clock.set_busy("Mei", False)  # at speed 1000, 0.05 s away
    await asyncio.wait_for(sleeper, 1)
    assert clock.now() >= 50


def test_the_clock_speeds_may_not_rise_with_load_nor_fall_below_real_time():
    def settings(idle: float, one: float, all_: float) -> ClockSettings:
        return ClockSettings(
            speed_idle=idle, speed_busy_one=one, speed_busy_all=all_, idle_minutes=30
        )

    assert settings(1, 1, 1).speed_busy_all == 1  # equal speeds, and real time, are allowed
    for speeds in [(30, 32, 8), (240, 8, 32), (240, 32, 0.5)]:
        with pytest.raises(ValidationError, match="speed_idle >= speed_busy_one >= speed_busy_all"):
            settings(*speeds)


async def test_a_manual_clock_wakes_its_sleepers_in_order():
    clock = ManualClock(0)
    woke: list[int] = []

    async def sleep(t: int) -> None:
        await clock.sleep_until(t)
        woke.append(clock.now())

    tasks = [asyncio.create_task(sleep(t)) for t in (30, 10, 20)]
    await clock.advance_to(25)
    assert woke == [10, 20] and clock.now() == 25
    await clock.advance(5)
    assert woke == [10, 20, 30]
    await asyncio.gather(*tasks)


def test_the_log_continues_its_sequence_when_reopened(tmp_path):
    log = WorldLog(tmp_path / "world.jsonl")
    assert not log.path.exists()
    first = log.append(
        "wake",
        25_200,
        "Mei woke up.",
        actor="Mei",
        audience=["Mei"],
        personal={"Mei": "You woke up."},
    )
    log.append("depart", 25_300, "Mei left.", actor="Mei", place="home")
    assert first.seq == 1
    reopened = WorldLog(tmp_path / "world.jsonl")
    assert reopened.append("resume", 9_000, "Back.").seq == 3
    entries = list(reopened.entries())
    assert [e["seq"] for e in entries] == [1, 2, 3]
    assert entries[0]["personal"] == {"Mei": "You woke up."} and entries[0]["real_time"] > 0
    with pytest.raises(ValueError, match="unknown world event kind"):
        reopened.append("teleport", 0, "x")
