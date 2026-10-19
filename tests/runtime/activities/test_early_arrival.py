"""Closed destinations are reachable; outside arrival never grants indoor access."""

import pytest

from core.environment.rejection import Rejected
from core.interaction import Card
from runtime.activities.engine import ActivityEngine
from runtime.activities.model import at
from runtime.realtime.engine import RealtimeEngine
from tests.runtime.activities import test_engine as activity_tests

engine = activity_tests.engine
choose, complete, events = activity_tests.choose, activity_tests.complete, activity_tests.events


@pytest.fixture(params=[ActivityEngine, RealtimeEngine], ids=["activities", "realtime"])
def gate(engine, request):
    result = request.param(engine.sim)
    result.now, result.end = at(1, "07:30:17"), at(1, "22:00")
    return result


async def arrive(gate, who="Mei", destination="workshop"):
    gate.select(who, choose("select_move", target=destination))
    arrival = gate.activities[gate.current[who]].latest_end
    await complete(gate, arrival)
    return arrival


async def test_closed_destination_arrival_waits_outside_until_opening(gate):
    assert "workshop" in gate.menu("Mei")["moves"].values()
    arrival = await arrive(gate)
    assert gate.env.world.locations["Mei"] == "workshop"
    assert gate.outside["Mei"] == "workshop"
    waiting = gate.activities[gate.current["Mei"]]
    assert waiting.kind == "rest" and waiting.members["Mei"].end == at(1, "08:00")
    assert not gate.can_code("Mei")
    assert "OUTSIDE" in gate.observation("Mei").situation
    moved = next(e for e in events(gate) if e["kind"] == "move" and e["actor"] == "Mei")
    assert moved["payload"]["outside"] is True
    assert moved["payload"]["sim_seconds"] == arrival
    assert not any(e["kind"] == "action_rejected" for e in events(gate))
    gate.now = at(1, "07:59")
    gate.boundary()
    assert gate.env.world.locations["Mei"] == "workshop"  # not sent home while waiting
    gate.now = at(1, "08:00")
    gate.boundary()
    assert "Mei" not in gate.outside and "Mei" not in gate.current
    assert gate.can_code("Mei")
    assert waiting.status == "ended"
    gate.select("Mei", choose("select_work", seconds=60))
    assert gate.activities[gate.current["Mei"]].kind == "work"


async def test_outside_cannot_bypass_work_menu_or_see_indoor_occupants(gate):
    await arrive(gate)
    gate.env.world.locations["Tomas"] = "workshop"  # a previously started indoor operation
    observation = gate.observation("Mei")
    assert "People here: Mei." in observation.situation
    gate.leave("Mei", "An invitation woke this wait.")
    schema = Card(gate.observation("Mei").allowed).model.model_json_schema()
    assert '"const": "work"' not in __import__("json").dumps(schema)
    for operation in ("select_work", "resume_work", "select_conversation"):
        with pytest.raises(Rejected, match="outside"):
            gate.select("Mei", choose(operation, seconds=60, target="invalid"))


async def test_lunch_arrival_waits_for_afternoon_reopening(gate):
    gate.now = at(1, "12:30")
    await arrive(gate)
    assert gate.activities[gate.current["Mei"]].members["Mei"].end == at(1, "14:00")
    gate.now = at(1, "13:00")
    gate.boundary()
    assert "Mei" in gate.outside
    gate.now = at(1, "14:00")
    gate.boundary()
    assert "Mei" not in gate.outside and "Mei" not in gate.current


async def test_destination_closes_during_travel_and_state_keeps_outside(gate):
    gate.now = at(1, "11:59:59")
    await arrive(gate)
    assert gate.now > at(1, "12:00") and "Mei" in gate.outside
    restored = type(gate)(gate.sim, state=gate.state())
    assert restored.outside == gate.outside
    assert not gate.can_code("Mei")


async def test_waiting_does_not_bypass_private_homes_or_day_end(gate):
    other_home = gate.env.config.homes["Tomas"]
    assert other_home not in gate.menu("Mei")["moves"].values()
    with pytest.raises(Rejected, match="destination"):
        gate.select("Mei", choose("select_move", target=other_home))
    await arrive(gate)
    gate.now = gate.end
    gate.boundary()
    assert gate.env.world.locations["Mei"] == gate.env.config.homes["Mei"]
    assert "Mei" not in gate.outside and "Mei" not in gate.current


async def test_appointment_starts_after_doors_open_not_before(gate):
    await arrive(gate, "Mei")
    await arrive(gate, "Aisha")
    gate.invitation_action(
        "Mei",
        "invite",
        {
            "people": ["Aisha"],
            "place": gate.env.world.places["workshop"].name,
            "at": "08:00",
            "minutes": 30,
            "topic": "Meet at opening",
            "public": False,
        },
    )
    invitation = list(gate.invitations.values())[-1]
    gate.invitation_action("Aisha", "accept", {"invitation": invitation.id})
    gate.start_ready_conversations()
    assert invitation.status == "pending"
    gate.now = at(1, "08:00")
    gate.boundary()
    gate.start_ready_conversations()
    assert invitation.status == "started"
    assert gate.current["Mei"] == gate.current["Aisha"]


def test_legacy_environment_move_still_rejects_closed_venues(engine):
    result = engine.env.move("Mei", "workshop", time=7 * 60)
    assert result[0].kind == "action_rejected"
    assert engine.env.world.locations["Mei"] == engine.env.config.homes["Mei"]
