"""The daily schedule: group B's evening, which wakes whoever sleeps, waiting, the checkpoint
hand-off, snapshot and restore, and the completeness of the world log."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.world.conftest import (
    B_EXCHANGE,
    RESIDENTS,
    FakeBackend,
    Town,
    at,
    awake_at,
    make_agent_dirs,
    stocked,
    town_config,
)
from world.clock import ManualClock, settle
from world.events import Movement, Sleep, Work
from world.log import KINDS
from world.world import World

FOUR = RESIDENTS + ({"name": "Jonas", "home": "college-flat", "purse": 60},)
EIGHT = FOUR + tuple(
    {"name": name, "home": "college-flat", "purse": 60}
    for name in ("Lucia", "Ravi", "Olga", "Kofi")
)


async def test_group_b_pairs_by_lot_and_meets_at_the_cafe_on_work_alone(make_town):
    town = make_town(town_config("isolated", exchange=B_EXCHANGE, residents=FOUR))
    await awake_at(town)
    world = town.world
    await town.until("18:55")
    await town.call("Tomas", "go", place="park")
    for name in world.residents:
        town.take(name)
    await town.until("19:00")

    pairings = [e for e in world.log.entries() if e["kind"] == "exchange_pairing"]
    pairs = [tuple(e["payload"]["pair"]) for e in pairings]
    assert sorted(len(pair) for pair in pairs) == [2, 2]
    assert sorted(sum(pairs, ())) == sorted(world.residents)  # Jonas among them
    (a, b), (c, d) = pairs
    assert town.take(a) == [
        f"It is 19:00: by lot, you are to meet {b} at the café on the square "
        "and talk about your work."
    ]
    tomas = world.residents["Tomas"]
    assert isinstance(tomas.base, Movement) and tomas.base.destination == "cafe"
    assert tomas.base.arrival == at("19:15")  # the park first, then on to the café
    rerun = World(world.config, world.log.path.parent, FakeBackend(), clock=ManualClock())
    assert [tuple(e["payload"]["pair"]) for e in pairings] == pairs  # the lot is the seed's
    del rerun

    await town.until("19:15")
    for x, y in pairs:
        assert world.residents[x].conversation is world.residents[y].conversation is not None
        conversation = world.residents[x].conversation
        assert conversation.budget == {x: 3, y: 3}
    told = town.take(a)[-1]
    assert (
        told == f"You met {b} at the café on the square. You each have 3 turns to speak; speak "
        "of your work alone."
    )
    assert "speak of your work alone" in world.ports[a].situation()

    town.take(c)
    for _ in range(3):
        await town.call(a, "say", text="I used git bisect today.")
    assert world.ports[b].interrupt.is_set()
    assert [p.kind for p in world.ports[c].pending()] == []  # the other pair hears nothing
    assert (await town.call(a, "say", text="One more thing.")).text == (
        "You have no turns left to speak at this meeting."
    )
    assert (await town.call(b, "say", text="Hi", to=[c])).text == f"{c} is not here."
    await town.call(b, "leave_conversation")
    assert world.residents[a].partner is None and world.residents[a].conversation is None
    assert (await town.call(a, "say", text="Still here?")).text == (
        "There is nobody here to hear you."
    )
    await town.call(a, "go", place=world.residents[a].home)
    await town.until("21:00")
    await town.call(a, "sleep", until="07:00", journal="Met someone.")
    assert f"spoke with today ({b})" in town.take(a)[-1]
    refused = await town.call(a, "rate", resident=c, score=3, reason="x")
    assert refused.text == f"You did not speak with {c} today."


async def test_group_b_wakes_whoever_sleeps_and_pairs_all_eight(make_town):
    town = make_town(town_config("isolated", exchange=B_EXCHANGE, residents=EIGHT))
    await awake_at(town)
    world = town.world
    await town.call("Kofi", "go", place="workshop")
    await town.until("07:10")
    await town.call("Kofi", "start_work")
    await town.until("18:00")
    for name in ("Jonas", "Lucia"):
        await town.call(name, "sleep", until="06:00", journal="An early night.")
    town.rest("Jonas")  # Jonas falls asleep; Lucia is still in bed
    await settle()
    assert world.residents["Jonas"].suspended and not world.residents["Lucia"].suspended
    for name in world.residents:
        town.take(name)
    await town.until("19:00")

    pairs = [
        tuple(e["payload"]["pair"]) for e in world.log.entries() if e["kind"] == "exchange_pairing"
    ]
    assert sorted(len(pair) for pair in pairs) == [2, 2, 2, 2]
    assert sorted(sum(pairs, ())) == sorted(world.residents)
    partner = {a: b for pair in pairs for a, b in (pair, pair[::-1])}
    woken = [
        e["actor"]
        for e in world.log.entries()
        if e["kind"] == "wake" and e["sim_time"] == at("19:00")
    ]
    assert sorted(woken) == ["Jonas", "Lucia"]

    def woken_and_paired(name: str) -> list[str]:
        return [
            "It is 19:00: you were woken at home for the evening meeting. You are a little "
            "hungry. You are fresh. You are in good health.",
            f"It is 19:00: by lot, you are to meet {partner[name]} at the café on the square "
            "and talk about your work.",
        ]

    assert town.take("Lucia") == woken_and_paired("Lucia")  # from bed, before falling asleep
    heard = [p.text for p in town.heard["Jonas"] if p.kind in ("wake", "exchange_pairing")]
    assert heard == woken_and_paired("Jonas")  # from sleep
    kofi = [e["kind"] for e in world.log.entries() if e["actor"] == "Kofi"]
    assert kofi[-2:] == ["leave_work", "depart"]  # taken from work to the café

    await town.until("19:10")
    assert all(not isinstance(r.base, (Sleep, Movement)) for r in world.residents.values())
    for a, b in pairs:
        conversation = world.residents[a].conversation
        assert conversation is not None and conversation is world.residents[b].conversation
        assert conversation.place == "cafe" and conversation.budget == {a: 3, b: 3}
    meetings = [e for e in world.log.entries() if e["kind"] == "meeting"]
    assert sorted(sorted(e["payload"]["pair"]) for e in meetings) == sorted(map(sorted, pairs))


async def test_a_pair_that_never_meets_meets_nowhere_else_and_parts_at_the_forced_sleep(
    make_town,
):
    town = make_town(town_config("isolated", exchange=B_EXCHANGE, residents=FOUR))
    town.start(until_day=2)
    town.rest()
    world = town.world
    mei = world.residents["Mei"]
    await town.until("18:40")
    await town.call("Mei", "go", place="cafe")
    await town.until("19:00")
    other = world.residents[mei.partner]
    assert mei.place == "cafe" and isinstance(other.base, Movement)
    await town.call("Mei", "go", place="workshop")  # gone before her partner comes
    await town.until("19:30")
    await town.call(other.name, "go", place="workshop")
    await town.until("20:00")
    assert mei.place == other.place == "workshop"
    assert mei.conversation is other.conversation is None  # they meet only at the café
    meetings = [e["payload"]["pair"] for e in world.log.entries() if e["kind"] == "meeting"]
    assert not [pair for pair in meetings if "Mei" in pair]
    await town.call("Mei", "go", place=mei.home)
    await town.until("20:30")
    await town.call("Mei", "sleep", until="08:00", journal="A walk across town.")
    await town.until("03:00", day=2)  # her partner is still up at the forced sleep
    assert mei.partner is other.partner is None
    assert [day for day, _ in town.checkpoints] == [1]


async def test_an_odd_one_out_is_told_nobody_is_free(make_town):
    town = make_town(town_config("isolated", exchange=B_EXCHANGE))
    await awake_at(town)
    await town.until("19:00")
    alone = [e for e in town.world.log.entries() if e["kind"] == "exchange_pairing"][-1]
    (name,) = alone["payload"]["pair"]
    assert town.take(name)[-1] == "It is 19:00: nobody is free to meet you this evening."
    assert town.world.residents[name].partner is None


async def test_waiting_brings_a_percept_within_the_idle_interval(make_town):
    town = make_town()
    await awake_at(town)
    port = town.world.ports["Tomas"]
    waiting = asyncio.create_task(port.wait())
    await town.until("07:29")
    assert not waiting.done()
    await town.until("07:30")
    assert [p.text for p in waiting.result()] == ["It is now 07:30."]

    assert (await town.call("Tomas", "wait", minutes=45)).ends_turn
    waiting = asyncio.create_task(port.wait())
    await town.until("08:14")
    assert not waiting.done()
    await town.until("08:15")
    assert [p.text for p in waiting.result()] == ["You waited 45 minutes; it is now 08:15."]

    waiting = asyncio.create_task(port.wait())
    await town.until("08:20")
    await town.call("Mei", "go", place="college-flat")
    await town.until("08:30")
    assert [p.text for p in waiting.result()] == ["Mei arrived at the flat by the college gates."]
    assert town.world.residents["Tomas"].tick is None

    # A wait for minutes asked that something ends sooner says so, after what ended it.
    await town.call("Tomas", "wait", minutes=60)
    waiting = asyncio.create_task(port.wait())
    await town.until("08:35")
    await town.call("Mei", "say", text="Morning, Tomas.")
    assert [p.text for p in waiting.result()] == [
        "Mei said: “Morning, Tomas.”",
        "That ended the wait you began at 08:30; it is now 08:35.",
    ]
    ended = [e for e in town.world.log.entries() if e["kind"] == "time"][-1]
    assert ended["payload"] == {"waited_minutes": 5, "cut_short": True}
    waiting = asyncio.create_task(port.wait())  # an idle wait has no minutes to cut short
    await town.until("08:45")
    assert [p.text for p in waiting.result()] == [
        "Nobody spoke for 10 minutes; at 08:45 the conversation ended."
    ]


async def test_one_can_wait_at_work_for_the_board(make_town):
    town = make_town()
    await awake_at(town)
    port = town.world.ports["Tomas"]
    await town.call("Tomas", "go", place="workshop")
    await town.until("07:30")
    await town.call("Tomas", "start_work")
    town.take("Tomas")
    assert (await town.call("Tomas", "wait", minutes=60)).ends_turn
    waiting = asyncio.create_task(port.wait())
    await town.until("08:00")
    assert [p.text for p in waiting.result()] == [
        "It is 08:00: the day's board is posted at the workshop.",
        "That ended the wait you began at 07:30; it is now 08:00.",
    ]
    assert isinstance(town.world.residents["Tomas"].base, Work)


async def test_a_sleeping_resident_hears_nothing_until_it_wakes(make_town):
    town = make_town()
    await awake_at(town)
    await town.until("21:00")
    await town.call("Mei", "sleep", until="09:00", journal="Early.")
    town.take("Mei")
    waiting = asyncio.create_task(town.world.ports["Mei"].wait())
    await town.until("23:00")
    assert not waiting.done()
    await town.call("Aisha", "go", place="park")
    town.rest("Tomas", "Aisha")
    await town.until("08:59", day=2)
    assert not waiting.done()
    await town.until("09:00", day=2)
    assert [p.kind for p in waiting.result()] == ["settlement", "wake"]


async def test_the_checkpoint_waits_for_every_runtime_to_rest_and_holds_the_clock(make_town):
    town = make_town()
    runner = town.start(until_day=1)
    await town.until("07:00")
    town.rest("Mei", "Tomas")
    await town.until("02:40", day=2)
    assert town.checkpoints == [] and not runner.done()
    town.rest("Aisha")
    await settle()
    await runner
    ((day, state),) = town.checkpoints
    assert day == 1 and state["time"] == at("02:40", day=2)
    assert town.kinds()[-1] == "checkpoint"
    assert all(r.suspended for r in town.world.residents.values())


async def test_snapshot_and_restore_round_trip_exactly(make_town, tmp_path):
    backend = FakeBackend()
    town = make_town(backend=backend)
    await awake_at(town)
    await town.call("Aisha", "say", text="Busy day?", to=["Mei"])
    await town.call("Mei", "go", place="store")
    await town.until("07:10")
    await town.call("Mei", "buy", item="groceries")
    await town.call("Mei", "buy", item="coat")
    await town.call("Mei", "go", place="workshop")
    await town.until("09:00")
    await town.call("Mei", "start_work")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "write_repo_file", path="a.py", content="FIX\n")
    await town.call("Mei", "submit")
    await town.call("Mei", "claim_task", task=2)
    await town.call("Mei", "write_repo_file", path="b.py", content="half\n")
    await town.call("Mei", "leave_work")
    await town.until("22:00")
    await town.call("Aisha", "sleep", until="10:00", journal="Lazy morning.")
    await town.call("Aisha", "rate", resident="Mei", score=3, reason="Busy all day.")
    town.rest()
    await town.until("00:30", day=2)
    await town.call("Mei", "go", place="mill-street-house")
    await town.until("00:40", day=2)
    await town.call("Mei", "say", text="Still up?", to=["Tomas"])  # refused: not here
    await town.until("03:00", day=2)
    ((day, state),) = town.checkpoints
    assert day == 1
    assert state["residents"]["Mei"]["claim"] == {
        "task": 2,
        "day": 1,
        "diff": json.dumps({"b.py": "half\n"}),
    }
    assert state["residents"]["Mei"]["done"] == [1]
    assert state["residents"]["Mei"]["unread_ratings"] == [[3, "Busy all day."]]
    assert state["residents"]["Mei"]["home"] == "mill-street-house"
    mei_living = state["residents"]["Mei"]["living"]
    # Away from home all day 1, Mei ate none of her groceries until she came home after
    # midnight, hungry, and ate two helpings in her kitchen.
    assert mei_living["things"] == {"groceries": 7, "coat": 1}
    assert mei_living["eaten"] == {"groceries": 2}
    assert set(mei_living) == {"things", "eaten", "satiety", "energy", "health", "night"}
    assert mei_living["health"] == 100 and mei_living["night"] == {
        "poor_home": -2,
        "recovery": 5,
    }
    aisha_living = state["residents"]["Aisha"]["living"]
    assert aisha_living["satiety"] == 10 and aisha_living["health"] == 100  # hungry, not starving
    assert [p["kind"] for p in state["residents"]["Aisha"]["held"]] == ["settlement"]
    assert state["residents"]["Aisha"]["wake"] == at("10:00", day=2)
    saved = json.loads(json.dumps(state))
    last_seq = list(town.world.log.entries())[-1]["seq"]

    root = tmp_path
    restored = World(town.world.config, root, FakeBackend(), clock=ManualClock())
    restored.restore(saved)
    assert restored.snapshot() == state
    resume = list(restored.log.entries())[-1]
    assert resume["kind"] == "resume" and resume["seq"] == last_seq + 1
    assert restored.clock.now() == state["time"]


async def test_a_restored_world_carries_on_from_its_checkpoint(make_town, tmp_path):
    town = make_town()
    await awake_at(town)
    stocked(town)
    await town.call("Mei", "go", place="workshop")
    await town.until("09:00")
    await town.call("Mei", "start_work")
    await town.call("Mei", "claim_task", task=2)
    await town.call("Mei", "write_repo_file", path="b.py", content="half\n")
    await town.until("22:00")
    await town.call("Aisha", "sleep", until="10:00", journal="Lazy.")
    town.rest()
    await town.until("03:00", day=2)
    (_, state) = town.checkpoints[0]
    await town.close()

    backend = FakeBackend()
    later = World(town.world.config, tmp_path, backend, clock=ManualClock())
    later.restore(json.loads(json.dumps(state)))
    again = Town(later, backend)
    again.start(until_day=2)
    await again.until("10:00", day=2)
    aisha = again.take("Aisha")
    assert aisha[0].startswith("Your statement for Monday 1 January")
    assert aisha[-1] == (
        "You woke up at home. It is Tuesday 2 January, 10:00. You are well fed. You are fresh. "
        "You are in good health."
    )
    await again.call("Mei", "go", place="workshop")
    await again.until("10:10", day=2)
    assert later.residents["Mei"].living.things == {"groceries": 6}  # the stock came back
    await again.call("Mei", "start_work")
    assert (await again.call("Mei", "read_repo_file", path="b.py")).text == "half\n"
    await again.close()


async def test_snapshots_are_taken_and_restored_only_at_checkpoints(make_town, tmp_path):
    town = make_town()
    state = town.world.snapshot()  # a new world stands at the checkpoint hour of day 1
    assert state["time"] == at("02:30") and state["residents"]["Mei"]["wake"] == at("07:00")
    await awake_at(town)
    with pytest.raises(RuntimeError):
        town.world.snapshot()
    with pytest.raises(RuntimeError):
        town.world.restore(state)  # it has started
    fewer = make_town(town_config(residents=RESIDENTS[:2]), root=tmp_path / "fewer")
    with pytest.raises(ValueError):
        fewer.world.restore(state)


async def test_the_world_log_records_every_kind_of_event(make_town, tmp_path):
    town = make_town()
    await awake_at(town)
    skill = tmp_path / "agents" / "Mei" / "skills" / "triage.md"
    skill.write_text("Read the traceback first.\n")
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="workshop")
    await town.until("08:00")
    town.take("Aisha")
    tick = asyncio.create_task(town.world.ports["Aisha"].wait())
    await town.until("09:00")
    await tick
    for name in ("Mei", "Tomas"):
        await town.call(name, "start_work")
    await town.call("Mei", "claim_task", task=1)
    await town.call("Mei", "shell", command="pytest")
    await town.call("Mei", "read_repo_file", path="README")
    await town.call("Mei", "write_repo_file", path="fix.py", content="FIX\n")
    await town.call("Mei", "submit")
    await town.call("Mei", "claim_task", task=2)
    await town.call("Mei", "abandon_task")
    await town.call("Tomas", "claim_task", task=3)
    await town.call("Tomas", "say", text="Lunch?", to=["Mei"])
    await town.call("Mei", "give_money", to="Tomas", amount=5)
    await town.call("Mei", "share_skill", to="Tomas", skill="triage")
    await town.call("Mei", "leave_conversation")
    await town.call("Mei", "leave_work")
    await town.call("Tomas", "leave_work")
    await town.until("18:00")
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="store")
    await town.until("18:10")
    for name in ("Mei", "Tomas"):
        await town.call(name, "buy", item="phone")
    await town.call("Mei", "buy", item="groceries")
    await town.call("Mei", "message", to="Tomas", text="Supper later?")
    await town.call("Mei", "go", place="college-flat")
    await town.until("18:20")
    await town.call("Mei", "move_in")
    await town.until("20:00")
    await town.call("Mei", "sleep", until="07:00", journal="A full day.")
    await town.call("Mei", "rate", resident="Tomas", score=4, reason="Good company.")
    town.rest()
    town.world.residents["Aisha"].living.health = 1  # her last night
    await town.until("00:00", day=3)  # Tomas's claim runs out; Aisha dies

    b_town = make_town(
        town_config("isolated", exchange=B_EXCHANGE, residents=RESIDENTS[:2]), root=tmp_path / "b"
    )
    await awake_at(b_town)
    await b_town.until("19:30")
    make_agent_dirs(tmp_path / "r", town.world.config)
    restored = World(town.world.config, tmp_path / "r", FakeBackend(), clock=ManualClock())
    restored.restore(town.checkpoints[0][1])

    entries = [*town.world.log.entries(), *b_town.world.log.entries(), *restored.log.entries()]
    assert {entry["kind"] for entry in entries} == set(KINDS)
    for log in (town.world.log, b_town.world.log):
        seqs = [entry["seq"] for entry in log.entries()]
        assert seqs == list(range(1, len(seqs) + 1))
    for entry in entries:
        assert set(entry) == {
            "seq",
            "kind",
            "sim_time",
            "real_time",
            "actor",
            "place",
            "audience",
            "text",
            "personal",
            "payload",
        }
    speech = next(e for e in entries if e["kind"] == "speech")
    assert speech["payload"]["text"] == "Lunch?" and speech["audience"] == ["Mei"]
    assert speech["personal"] == {
        "Tomas": "You said to Mei: “Lunch?”",
        "Mei": "Tomas said to you: “Lunch?”",
    }
    assert speech["payload"]["members"] == ["Mei", "Tomas"]
    journal = next(e for e in entries if e["kind"] == "sleep")
    assert journal["payload"]["journal"] == "A full day."
