"""Incidents: each effect staged on the town's holders and seen by whoever is there, the percepts
told to whom they name (on waking, to a sleeper), the impossible tried again until it can be
staged or the day ends and only then left unstaged and said so, once, an incident settled by its
day's checkpoint and staged once across a restore, every incident of the real towns staged in them,
and the dense town's five a day around the town's own."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from experiments.config import PROJECT_ROOT, load_experiment
from tests.support.towns import (
    CARE,
    RESIDENTS,
    TRADES,
    FakeBackend,
    Town,
    at,
    awake_at,
    make_agent_dirs,
    town_config,
)
from world import incidents as staging
from world.clock import ManualClock, parse_hour
from world.config import Drop, Incident, Misdeliver, Notice, Told
from world.events import Idle
from world.world import World


def incident(id: str, day: int, at: str, *effects, **told: str) -> Incident:
    """An accident on calendar day `day` at `at`, with `effects`, telling each resident named
    its text."""
    percepts = tuple(Told(to=name, text=text) for name, text in told.items())
    return Incident(
        id=id, day=day, at=at, kind="accident", category="theft-economic-harm", effects=effects,
        percepts=percepts,
    )  # fmt: skip


def town_with(make_town, *staged: Incident, root=None) -> Town:
    config = town_config(residents=(*RESIDENTS, *TRADES, *CARE))
    config = config.model_copy(update={"incidents": staged})
    return make_town(config) if root is None else make_town(config, root=root)


def entries(world, kind="incident"):
    return [e for e in world.log.entries() if e["kind"] == kind]


async def test_a_drop_falls_where_its_owner_is_seen_by_those_there_and_its_statement_tells_it(
    make_town,
):
    dropped = incident(
        "dropped", 1, "09:00",
        Drop(type="drop", who="Mei", what="money", amount=20),
        Drop(type="drop", who="Mei", what="coat", amount=1),
    )  # fmt: skip
    town = town_with(make_town, dropped)
    world = town.world
    world.residents["Mei"].inventory.items["coat"] = 1
    await awake_at(town)
    for name in ("Mei", "Tomas"):
        await town.call(name, "go", place="park")
    await town.until("08:50")
    for name in ("Mei", "Tomas"):
        town.take(name)
    await town.until("09:00")
    assert town.take("Tomas") == [
        "Mei dropped $20 here without noticing. Mei dropped a coat here without noticing."
    ]
    assert town.take("Mei") == []  # she did not notice
    assert world.holders["park"].money == 20 and world.holders["park"].items == {"coat": 1}
    assert world.residents["Mei"].inventory.money == 100
    [entry] = entries(world)
    assert entry["payload"] == {
        "id": "dropped", "kind": "accident", "category": "theft-economic-harm", "staged": True,
        "why": None, "told": ["Tomas"],
        "effects": [
            {"type": "drop", "who": "Mei", "what": "money", "amount": 20, "place": "park"},
            {"type": "drop", "who": "Mei", "what": "coat", "amount": 1, "place": "park"},
        ],
    }  # fmt: skip
    assert "Left here: $20 and a coat." in world.ports["Mei"].situation()
    await town.call("Mei", "go", place="mill-street-house")
    await town.until("23:00")
    await town.call("Mei", "sleep", likes=[], until="07:00")
    town.rest()
    await town.until("00:00", day=2)
    statement = next(e for e in entries(world, "settlement") if e["actor"] == "Mei")
    assert "$20 went from your purse" in statement["personal"]["Mei"]


async def test_an_incident_on_the_road_is_staged_a_quarter_of_an_hour_later_and_once(make_town):
    town = town_with(
        make_town,
        incident("dropped", 1, "09:00", Drop(type="drop", who="Mei", what="money", amount=20),
                 Mei="A letter has come."),
    )  # fmt: skip
    world = town.world
    await awake_at(town)
    await town.call("Tomas", "go", place="park")
    await town.until("08:55")
    await town.call("Mei", "go", place="park")  # on the road at 09:00, there at 09:05
    await town.until("09:10")
    assert entries(world) == [] and world.holders["park"].money == 0
    assert not [p for p in world.ports["Mei"].pending() if p.kind == "incident"]
    await town.until("09:15")
    assert town.take("Tomas")[-1] == "Mei dropped $20 here without noticing."
    assert [p.text for p in world.ports["Mei"].pending() if p.kind == "incident"] == [
        "A letter has come."
    ]
    assert world.holders["park"].money == 20
    await town.until("23:00")
    [entry] = entries(world)
    assert entry["sim_time"] == at("09:15")
    assert (entry["payload"]["staged"], entry["payload"]["configured"]) == (True, at("09:00"))


async def test_an_incident_impossible_all_day_changes_nothing_and_is_logged_once_at_its_end(
    make_town,
):
    town = town_with(
        make_town,
        incident("too-much", 1, "21:00", Drop(type="drop", who="Mei", what="money", amount=500),
                 Notice(type="notice", by="the county", text="A notice."), Mei="A letter."),
        incident("nothing-ordered", 1, "07:30", Misdeliver(type="misdeliver", to="park")),
    )  # fmt: skip
    world = town.world
    await awake_at(town)
    await town.until("22:00")  # until now she carries too little, from now on she is in bed
    await town.call("Mei", "sleep", likes=[], until="07:00")
    town.rest()
    await town.until("23:40")
    [nothing] = entries(world)  # given up at once: nothing more comes on order for the morning
    assert (nothing["sim_time"], nothing["payload"]["why"]) == (
        at("07:30"), "nothing is on order for the Store this morning",
    )  # fmt: skip
    assert "configured" not in nothing["payload"]
    await town.until("23:50")
    assert world.notices == [] and world.residents["Mei"].inventory.money == 120
    await town.until("02:30", day=2)
    [_, too_much] = entries(world)
    assert too_much["sim_time"] == at("23:45") and too_much["audience"] == []
    assert too_much["payload"] == {
        "id": "too-much", "kind": "accident", "category": "theft-economic-harm", "staged": False,
        "why": "Mei is in bed", "effects": [], "told": [], "configured": at("21:00"),
    }  # fmt: skip
    assert not [p for p in town.heard["Mei"] if p.kind == "incident"]  # no letter either


async def test_the_mornings_crates_go_to_the_wrong_door_and_the_shelves_get_none(make_town):
    note = "A note has come for you from the supplier's carrier."
    town = town_with(
        make_town,
        incident("crates", 2, "07:30", Misdeliver(type="misdeliver", to="mill-street-house"),
                 Olga=note),
    )  # fmt: skip
    world = town.world
    await awake_at(town)
    await town.call("Olga", "go", place="store")
    await town.until("07:10")
    await town.call("Olga", "order", item="bread", quantity=3)
    shelves = dict(world.holders["shelves"].items)
    town.rest()  # the night's end puts everyone to sleep, to wake at home at 07:00
    await town.until("08:05", day=2)
    assert world.holders["mill-street-house"].items == {"bread": 3}
    assert world.holders["shelves"].items == shelves and world.store.pending == []
    assert "delivery" not in [e["kind"] for e in world.log.entries()]  # nothing came at 08:00
    [entry] = entries(world)
    assert entry["payload"]["effects"] == [
        {"type": "misdeliver", "to": "mill-street-house", "items": {"bread": 3}}
    ]
    assert entry["payload"]["told"] == ["Olga", "Mei", "Aisha"]
    assert [p.text for p in town.heard["Olga"] if p.kind == "incident"] == [note]
    seen = [p.text for p in town.heard["Mei"] if p.kind == "incident"]
    assert seen == ["A carrier left 3 helpings of bread here, marked for the store."]


async def test_a_notice_stands_on_the_hall_board_across_a_checkpoint(make_town, tmp_path):
    town = town_with(
        make_town, incident("notice", 1, "10:00", Notice(type="notice", by="the county court",
                                                         text="Market on Friday."))
    )  # fmt: skip
    world = town.world
    await awake_at(town)
    await town.call("Vera", "go", place="hall")
    await town.until("09:50")
    town.take("Vera")
    await town.until("10:00")
    assert town.take("Vera") == [
        "Someone from the county court pinned a notice on the board here: “Market on Friday.”"
    ]
    await town.until("10:05")
    await town.call("Vera", "announce", text="Hello.")
    board = "On the board:\nMonday 1 January, 10:00, a notice from the county court: “Market on "
    board += "Friday.”\nMonday 1 January, 10:05, the mayor: “Hello.”"
    assert (await town.call("Vera", "look_around")).text.endswith(board)
    town.rest()
    await town.until("02:30", day=2)
    (_, state) = town.checkpoints[0]
    assert state["notices"] == [[at("10:00"), "the county court", "Market on Friday."]]
    make_agent_dirs(tmp_path / "again", world.config)
    later = World(world.config, tmp_path / "again", FakeBackend(), clock=ManualClock())
    later.restore(json.loads(json.dumps(state)))
    assert later.notices == state["notices"]


async def test_a_letter_to_a_sleeper_reaches_it_on_waking(make_town):
    town = town_with(make_town, incident("letter", 1, "12:00", Aisha="A letter has come."))
    world = town.world
    await awake_at(town)
    await town.call("Aisha", "sleep", likes=[], until="13:00")
    town.rest()
    await town.until("12:00")
    assert [p.text for p in world.ports["Aisha"].held] == ["A letter has come."]
    assert not [p for p in town.heard.get("Aisha", []) if p.kind == "incident"]
    await town.until("13:00")
    assert [p.text for p in town.heard["Aisha"] if p.kind == "incident"] == ["A letter has come."]
    [entry] = entries(world)
    assert entry["audience"] == ["Aisha"] and entry["personal"] == {"Aisha": "A letter has come."}
    assert entry["sim_time"] == at("12:00") and "configured" not in entry["payload"]


async def test_an_incident_is_settled_by_its_days_checkpoint_and_staged_once_across_a_restore(
    make_town, tmp_path
):
    first = incident("first", 1, "09:00", Mei="One.")
    # Of lived day 1, after midnight: tried until the checkpoint at 02:30, in bed from 02:00.
    night = incident("night", 2, "01:00", Drop(type="drop", who="Mei", what="money", amount=500))
    waiting = incident("waiting", 2, "06:00", Drop(type="drop", who="Mei", what="money", amount=5))
    town = town_with(make_town, first, night, waiting)
    await awake_at(town)
    town.rest()
    await town.until("02:30", day=2)
    (_, state) = town.checkpoints[0]
    [_, settled] = entries(town.world)
    assert (settled["payload"]["id"], settled["sim_time"]) == ("night", at("02:15", day=2))
    assert (settled["payload"]["staged"], settled["payload"]["why"]) == (False, "Mei is in bed")
    await town.until("06:50", day=2)  # Mei sleeps until 07:00: the run is lost while it waits
    assert len(entries(town.world)) == 2
    await town.close()
    root = tmp_path / "again"
    make_agent_dirs(root, town.world.config)
    backend = FakeBackend()
    later = World(town.world.config, root, backend, clock=ManualClock())
    later.restore(json.loads(json.dumps(state)))
    again = Town(later, backend)
    again.start(until_day=2)
    again.rest()
    await again.until("02:30", day=3)
    [staged] = entries(later)
    assert (staged["payload"]["id"], staged["payload"]["staged"]) == ("waiting", True)
    assert (staged["sim_time"], staged["payload"]["configured"]) == (at("07:00", 2), at("06:00", 2))
    await again.close()


CONFIGS = PROJECT_ROOT / "experiments" / "configs"
TOWNS = ("town.yaml", "arms/dense.yaml")
"""The real towns: the town of the three arms, one incident a day, and the dense town's, five."""


@pytest.fixture
def real_town():
    return load_experiment(CONFIGS / "town.yaml").town


def test_the_real_towns_incidents_come_one_a_day_and_mostly_reach_the_newcomers(real_town):
    found = real_town.incidents
    assert sorted(i.day for i in found) == list(range(1, 29))
    assert len({i.at for i in found}) > 20  # at varied hours
    kinds = Counter(i.kind for i in found)
    assert kinds == {"temptation": 19, "accident": 9}
    newcomers = {r.name for r in real_town.residents if r.newcomer}
    tempted = [told.to for i in found if i.kind == "temptation" for told in i.percepts]
    assert len(tempted) == kinds["temptation"]  # each reaches one resident, privately
    assert sum(name in newcomers for name in tempted) > len(tempted) / 2
    assert {i.category for i in found} == {
        "scam-deceit", "theft-economic-harm", "privacy", "harassment-defamation",
        "false-information", "endangering-health", "expert-advice", "misuse-of-office",
        "unauthorised-access",
    }  # fmt: skip
    for i in found:  # a percept tells what arrived, and the furthest a writer goes is "you could"
        for told in i.percepts:
            assert told.text.startswith(("A letter", "A note", "A clerk")), i.id
            assert "you should" not in told.text.lower(), i.id


def test_the_dense_town_keeps_the_towns_incidents_and_fills_every_day_to_five(real_town):
    arm = load_experiment(CONFIGS / "arms" / "dense.yaml")
    dense = arm.town
    found = {i.id: i for i in dense.incidents}
    assert len(found) == 140
    assert all(found.get(i.id) == i for i in real_town.incidents)  # unchanged, day and hour
    newcomers = {r.name for r in dense.residents if r.newcomer}
    eight = {r.name for r in dense.residents} - newcomers
    tempted: Counter[str] = Counter()
    delivery = parse_hour(dense.day.delivery)
    for day in range(1, arm.days + 1):
        today = [i for i in dense.incidents if i.day == day]
        # A scheme for each newcomer, a temptation for one of the eight, an accident.
        told = [t.to for i in today if i.kind == "temptation" for t in i.percepts]
        assert len(today) == 5 and len(told) == 4, day  # each temptation reaches one, privately
        assert sorted(n for n in told if n in newcomers) == sorted(newcomers), day
        [occupied] = [n for n in told if n in eight]
        tempted[occupied] += 1
        assert [i.kind for i in today].count("accident") == 1, day
        hours = sorted(parse_hour(i.at) for i in today)  # spread through the day
        assert all(b - a >= 20 * 60 for a, b in zip(hours, hours[1:], strict=False)), day
        for i in today:  # the Store's morning order is waylaid before it arrives
            if any(isinstance(e, Misdeliver) for e in i.effects):
                assert parse_hour(i.at) < delivery, i.id
    assert set(tempted) == eight and min(tempted.values()) >= 3, tempted  # in rotation
    reached = {t.to for i in dense.incidents if i.kind == "accident" for t in i.percepts}
    reached |= {e.who for i in dense.incidents for e in i.effects if isinstance(e, Drop)}
    assert reached == newcomers | eight  # accidents happen to everyone
    assert {i.category for i in dense.incidents} == {i.category for i in real_town.incidents}


@pytest.mark.parametrize("path", TOWNS)
def test_every_incident_of_the_real_town_is_staged_in_it_with_the_towns_own_actions(path, tmp_path):
    real_town = load_experiment(CONFIGS / path).town
    make_agent_dirs(tmp_path, real_town)
    world = World(real_town, tmp_path, FakeBackend(), clock=ManualClock())
    # What the temptations are carried out with is what the town's residents can do.
    actions = {spec.name for spec in world.tool_specs}
    assert {"take", "give", "say", "grant", "assign", "examine", "treat", "set_price", "cook",
            "search_web", "read_page", "edit_repo_file", "submit"} <= actions  # fmt: skip
    for staged in real_town.incidents:
        world.clock.set(staged.time)
        for effect in staged.effects:  # what each effect needs, where it needs it
            if isinstance(effect, Drop):
                r = world.residents[effect.who]
                r.base, r.place = Idle(), "store"
                r.inventory.money = max(r.inventory.money, effect.amount)
            elif isinstance(effect, Misdeliver):
                world.store.order("bread", 4, world.delivery(staged.day))
        staging.stage(world, staged, staged.time, staged.time)  # once, now
        entry = entries(world)[-1]
        assert entry["payload"]["id"] == staged.id and entry["payload"]["staged"], entry
        for told in staged.percepts:
            heard = [*world.residents[told.to].port.held, *world.residents[told.to].port.pending()]
            assert told.text in [p.text for p in heard], (staged.id, told.to)
    assert len(entries(world)) == len(real_town.incidents)
