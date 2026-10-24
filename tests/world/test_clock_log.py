"""The clock's speeds and how a moment is told; the world log's sequence across a resumption."""

from __future__ import annotations

import asyncio
import time
from datetime import date

import pytest

from world.clock import Clock, ManualClock, parse_hour, tell_moment
from world.log import WorldLog


def test_a_moment_is_told_by_weekday_date_and_hour():
    start = date(2026, 3, 2)  # a Monday
    assert tell_moment(4 * 86_400 + parse_hour("14:05"), start) == "Friday 6 March, 14:05"
    assert tell_moment(0, start) == "Monday 2 March, 00:00"
    with pytest.raises(ValueError):
        parse_hour("24:00")


async def test_the_clock_runs_fast_while_idle_and_slow_while_someone_is_busy():
    clock = Clock(1000, speed_active=10, speed_idle=1000)
    began = time.monotonic()
    await asyncio.sleep(0.05)
    idle = clock.now() - 1000
    assert 40 <= idle <= 1000 * (time.monotonic() - began) + 1
    clock.set_busy("Mei", True)
    mark, began = clock.now(), time.monotonic()
    await asyncio.sleep(0.05)
    busy = clock.now() - mark
    assert busy <= 10 * (time.monotonic() - began) + 1 and busy < idle
    clock.set_busy("Mei", False)
    with clock.hold():
        held = clock.now()
        await asyncio.sleep(0.02)
        assert clock.now() == held


async def test_a_sleeper_reconsiders_its_wait_when_the_speed_changes():
    clock = Clock(0, speed_active=1, speed_idle=1000)
    clock.set_busy("Mei", True)  # at speed 1, 50 seconds away
    sleeper = asyncio.create_task(clock.sleep_until(50))
    await asyncio.sleep(0.01)
    assert not sleeper.done()
    clock.set_busy("Mei", False)  # at speed 1000, 0.05 s away
    await asyncio.wait_for(sleeper, 1)
    assert clock.now() >= 50


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
