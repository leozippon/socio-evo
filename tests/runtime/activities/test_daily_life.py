from runtime.activities.engine import ActivityEngine
from runtime.activities.model import MoveActivity, RestActivity, at
from tests.runtime.activities import test_engine as activity_tests
from tests.runtime.activities.test_engine import choose

engine = activity_tests.engine


def enable(engine):
    engine.env.world.places["restaurant"] = engine.env.world.places["cafe"].model_copy(
        update={"id": "restaurant", "name": "Restaurant", "hours": ("07:00-22:00",)}
    )
    engine.sim.config = engine.sim.config.model_copy(update={"lunch_place": "restaurant"})


def test_lunch_wakes_long_rest_and_checkpoint_prevents_repeat(engine):
    enable(engine)
    who = next(iter(engine.sim.agents))
    engine.select(who, choose("select_rest", arguments={"until": "22:00", "wake": False}))
    engine.now = at(1, "12:00")
    engine.daily_choices()
    moving = engine.activities[engine.current[who]]
    assert isinstance(moving, MoveActivity)
    assert engine.env.world.locations[who] == moving.origin
    engine.now = moving.latest_end
    engine.arrive(who, moving.destination)
    engine.daily_choices()
    assert who in engine.daily_life["1"]["lunched"]
    restored = ActivityEngine(engine.sim, engine.state())
    restored.now, restored.end = engine.now, engine.end
    restored.daily_choices()
    assert who not in restored.current


def test_started_move_finishes_before_lunch_and_evening_rest_wakes(engine):
    enable(engine)
    who = next(iter(engine.sim.agents))
    engine.select(who, choose("select_move", target="cafe"))
    original = engine.current[who]
    engine.now = at(1, "12:00")
    engine.daily_choices()
    assert engine.current[who] == original
    engine.arrive(who, "cafe")
    engine.daily_choices()
    assert engine.activities[engine.current[who]].destination == "restaurant"
    engine.now = at(1, "18:00")
    engine.arrive(who, "restaurant")
    engine.daily_choices()
    engine.select(who, choose("select_rest", arguments={"until": "22:00"}))
    engine.daily_choices()
    assert isinstance(engine.activities[engine.current[who]], RestActivity)
    assert engine.daily_life["1"]["evening"].count(who) == 1


def test_appointment_reminder_only_confirmed_and_cancelled_is_inert(engine):
    enable(engine)
    engine.daily_life["1"] = {"lunched": list(engine.sim.agents), "evening": [], "reminded": []}
    engine.invitation_action(
        "Mei",
        "invite",
        {
            "people": ["Tomas"],
            "place": engine.env.world.places["cafe"].name,
            "at": "11:00",
            "topic": "coffee",
            "minutes": 20,
        },
    )
    invitation = next(iter(engine.invitations.values()))
    departure = invitation.start - engine.travel_seconds(engine.env.world.locations["Mei"], "cafe")
    engine.select("Mei", choose("select_rest", arguments={"until": "22:00", "wake": True}))
    engine.select("Tomas", choose("select_rest", arguments={"until": "22:00", "wake": False}))
    engine.now = departure
    engine.daily_choices()
    assert "Mei" not in engine.current
    assert "Tomas" in engine.current
    invitation.status = "cancelled"
    engine.select("Mei", choose("select_rest", arguments={"until": "22:00"}))
    engine.daily_choices()
    assert "Mei" in engine.current


async def test_enabled_full_day_moves_to_lunch_and_offers_evening(engine):
    from tests.runtime.activities.test_engine import ScriptedResident

    enable(engine)
    engine.sim.agents = {
        who: ScriptedResident(
            lambda obs: choose("select_rest", arguments={"until": "22:00", "wake": False})
        )
        for who in engine.sim.agents
    }
    await engine.run(7 * 60)
    assert set(engine.daily_life["1"]["lunched"]) == set(engine.sim.agents)
    assert set(engine.daily_life["1"]["evening"]) == set(engine.sim.agents)
    for resident in engine.sim.agents.values():
        assert len(resident.selections) == 3
