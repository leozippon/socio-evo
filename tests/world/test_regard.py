"""Regard: the number everyone carries of how many of the others like them, named going to bed,
changed once a night at the night's end, told each morning beside yesterday's, seen by all, and
kept across a checkpoint; the log gives every resident's number on every day."""

from __future__ import annotations

import json

from tests.support.towns import (
    RESIDENTS,
    FakeBackend,
    Town,
    at,
    awake_at,
    make_agent_dirs,
    town_config,
)
from world.clock import ManualClock
from world.world import World

LIKES = {"Mei": ["Tomas"], "Tomas": [], "Aisha": ["Mei", "Tomas"]}
"""Whom each resident of the small town likes at the start: Tomas is liked by two, Mei by one,
Aisha by nobody."""


def config():
    return town_config(residents=tuple(dict(r, likes=LIKES[r["name"]]) for r in RESIDENTS))


def numbers(entries, kind="regard") -> dict[str, list[tuple[int, int | None]]]:
    """Each resident's mornings in the log: (liked_by, yesterday)."""
    told: dict[str, list[tuple[int, int | None]]] = {}
    for e in entries:
        if e["kind"] == kind:
            payload = e["payload"]
            told.setdefault(e["actor"], []).append((payload["liked_by"], payload["yesterday"]))
    return told


async def test_the_numbers_follow_the_names_at_the_nights_end_and_are_told_each_morning(make_town):
    town = make_town(config())
    world = town.world
    assert world.liked_by() == {"Mei": 1, "Tomas": 2, "Aisha": 0}
    await awake_at(town)
    # The first morning tells the starting number, with no yesterday.
    assert [p.text for p in world.ports["Mei"].pending()] == []  # awake_at took the wake-up
    first = {"Mei": [(1, None)], "Tomas": [(2, None)], "Aisha": [(0, None)]}
    assert numbers(world.log.entries()) == first
    regard = next(e for e in world.log.entries() if e["kind"] == "regard" and e["actor"] == "Tomas")
    assert regard["personal"]["Tomas"] == "This morning 2 of the others like you."
    assert regard["audience"] == ["Tomas"]

    # Going to bed, each names whom it likes; refused names change nothing.
    await town.until("21:00")
    refused = await town.call("Mei", "sleep", likes=["Mei"], until="07:00", journal="x")
    assert refused.text == "You cannot name yourself among the people you like."
    refused = await town.call("Mei", "sleep", likes=["Tomas", "Zed"], until="07:00")
    assert refused.text == "There is nobody called Zed in the town."
    mei = world.residents["Mei"]
    assert mei.awake and not (mei.agent_dir / "memory" / "journal").exists()
    slept = await town.call("Mei", "sleep", likes=["Aisha", " Aisha "], until="07:00")
    assert slept.text == "You went to bed. You named Aisha as someone you like."
    slept = await town.call("Tomas", "sleep", likes=["Mei", "Aisha"], until="07:00")
    assert slept.text.endswith("You named Mei and Aisha as people you like.")
    # Aisha does not go to bed: the night's end puts her to sleep with the names she had.
    # The names now given make the numbers the night's end will show; until then none moves.
    assert world.liked_by() == {"Mei": 2, "Tomas": 1, "Aisha": 2}
    assert world.regard.shown == {"Mei": 1, "Tomas": 2, "Aisha": 0}
    own = "Your purse holds $30. None of the others likes you. You carry nothing but your money."
    assert world.ports["Aisha"].situation().endswith(own)
    town.rest()
    await town.until("02:00", day=2)
    assert world.regard.shown == {"Mei": 2, "Tomas": 1, "Aisha": 2}
    assert world.regard.yesterday == {"Mei": 1, "Tomas": 2, "Aisha": 0}
    await town.until("02:30", day=2)
    (day, state) = town.checkpoints[0]
    assert day == 1 and state["regard"]["likes"] == {
        "Mei": ["Aisha"], "Tomas": ["Mei", "Aisha"], "Aisha": ["Mei", "Tomas"]
    }  # fmt: skip

    # On waking each is told, once, its number beside yesterday's.
    await town.until("07:00", day=2)
    told = [p.text for p in town.heard["Aisha"] if p.kind == "regard"]
    assert told[-1] == "This morning 2 of the others like you; yesterday none did."
    assert [p.text for p in town.heard["Tomas"] if p.kind == "regard"][-1] == (
        "This morning 1 of the others likes you; yesterday 2 did."
    )
    assert numbers(world.log.entries())["Mei"] == [(1, None), (2, 1)]
    # A second waking the same day tells nothing more; the day's number does not move.
    await town.call("Aisha", "sleep", likes=[], until="09:00")
    await town.until("09:00", day=2)
    assert len(numbers(world.log.entries())["Aisha"]) == 2
    assert world.regard.shown["Mei"] == 2 and world.liked_by()["Mei"] == 1  # her name withdrawn

    # The log gives each naming, privately, and each morning's number.
    likes = [e for e in world.log.entries() if e["kind"] == "likes"]
    assert [(e["actor"], e["payload"]["names"]) for e in likes] == [
        ("Mei", ["Aisha"]), ("Tomas", ["Mei", "Aisha"]), ("Aisha", []),
    ]  # fmt: skip
    assert all(e["audience"] == [] for e in likes)


async def test_everyone_sees_the_numbers_of_those_present_and_its_own(make_town):
    town = make_town(config())
    world = town.world
    await awake_at(town)
    assert world.ports["Mei"].situation() == (
        "Monday 1 January, 07:00. You are at the shared house on Mill Street. Also here: Aisha "
        "(liked by 0). Your purse holds $120. 1 of the others likes you. You carry nothing but "
        "your money."
    )
    await town.call("Tomas", "go", place="mill-street-house")
    await town.until("07:10")
    assert town.take("Mei") == ["Tomas arrived at the shared house on Mill Street, liked by 2."]
    looked = await town.call("Aisha", "look_around")
    assert looked.text.endswith("Also here: Mei (liked by 1) and Tomas (liked by 2).")
    await town.call("Aisha", "say", text="Morning.", to=["Tomas"])
    assert "in a conversation with Tomas (liked by 2)." in world.ports["Aisha"].situation()
    await town.call("Mei", "sleep", likes=[], until="12:00")
    town.rest("Mei")
    await town.until("07:15")
    assert "Mei (asleep, liked by 1)" in (await town.call("Tomas", "look_around")).text


async def test_the_names_and_numbers_survive_a_checkpoint_and_the_next_morning_is_told(
    make_town, tmp_path
):
    town = make_town(config())
    await awake_at(town)
    await town.until("21:00")
    for name, likes in (("Mei", ["Aisha"]), ("Tomas", ["Aisha"]), ("Aisha", [])):
        await town.call(name, "sleep", likes=likes, until="08:00")
    town.rest()
    await town.until("02:30", day=2)
    (_, state) = town.checkpoints[0]
    await town.close()

    make_agent_dirs(tmp_path / "again", town.world.config)
    backend = FakeBackend()
    later = World(town.world.config, tmp_path / "again", backend, clock=ManualClock())
    later.restore(json.loads(json.dumps(state)))
    assert later.liked_by() == {"Mei": 0, "Tomas": 0, "Aisha": 2}
    assert later.regard.shown == later.liked_by() and later.regard.yesterday == {
        "Mei": 1, "Tomas": 2, "Aisha": 0
    }  # fmt: skip
    again = Town(later, backend)
    again.start(until_day=2)
    await again.until("08:00", day=2)
    assert again.take("Aisha")[-1] == "This morning 2 of the others like you; yesterday none did."
    assert later.clock.now() == at("08:00", day=2)
    await again.close()


async def test_sleep_needs_the_names_and_the_rules_say_what_the_number_is(make_town):
    town = make_town(config())
    world = town.world
    spec = next(spec for spec in world.tool_specs if spec.name == "sleep")
    assert spec.parameters["required"] == ["until", "likes"]
    await awake_at(town)
    await town.until("21:00")
    assert (await town.call("Mei", "sleep", until="07:00")).text == "sleep needs likes."
    people = world.rules.sections("Mei")["people"]
    assert people.endswith(
        "Everyone carries a number that everyone sees: how many of the others like them. Going "
        "to bed, each names the people they like, and at 02:00 the numbers change to follow the "
        "names last given."
    )
