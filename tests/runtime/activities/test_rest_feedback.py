"""Rest deadlines use the current day; failed selections retain actionable feedback."""

import pytest

from core.environment.rejection import Rejected
from runtime.activities.engine import ActivityEngine
from runtime.activities.model import at
from tests.runtime.activities import test_engine as activity_tests

engine = activity_tests.engine
choose = activity_tests.choose


@pytest.mark.parametrize("until", ["06:00", "19:00"])
def test_expired_same_day_rest_leaves_resident_ready_to_choose(engine, until):
    engine.now = at(1, "19:00")
    engine.feedback("Mei", "Previous selection failed.")
    engine.select("Mei", choose("select_rest", arguments={"until": until, "wake": False}))
    assert "Mei" not in engine.current
    assert "Mei" not in engine.selection_feedback
    assert not engine.activities
    assert not engine.queue.events


def test_future_same_day_rest_keeps_requested_end(engine):
    engine.now = at(1, "18:08")
    engine.select("Mei", choose("select_rest", arguments={"until": "21:00"}))
    assert engine.activities[engine.current["Mei"]].members["Mei"].end == at(1, "21:00")


def test_no_activity_feedback_survives_checkpoint_and_clears_on_success(engine):
    engine.now = at(1, "19:00")
    action = choose("select_move", target="missing")
    with pytest.raises(Rejected, match="destination is unavailable") as caught:
        engine.select("Mei", action)
    engine.feedback("Mei", str(caught.value))
    restored = ActivityEngine(engine.sim, engine.state())
    restored.now, restored.end = engine.now, engine.end
    assert "destination is unavailable" in restored.observation("Mei").situation
    restored.select("Mei", choose("select_rest", arguments={"until": "20:00"}))
    assert "Mei" not in restored.selection_feedback


def test_legacy_selection_rejection_is_visible_on_next_choice(engine):
    engine.reject("Mei", choose("select_move", target="missing"), "Choose an available place.")
    assert "Choose an available place." in engine.observation("Mei").situation
