"""Overnight rest and failed selections must not spin without actionable feedback."""

import pytest

from core.environment.rejection import Rejected
from runtime.activities.engine import ActivityEngine
from runtime.activities.model import RestActivity, at
from tests.runtime.activities import test_engine as activity_tests

engine = activity_tests.engine
choose = activity_tests.choose


@pytest.mark.parametrize("now,until", [("18:08", "06:00"), ("19:00", "08:00"), ("21:59", "05:30")])
def test_overnight_rest_enters_and_ends_at_day_boundary(engine, now, until):
    engine.now = at(1, now)
    engine.select("Mei", choose("select_rest", arguments={"until": until, "wake": False}))
    activity = engine.activities[engine.current["Mei"]]
    assert isinstance(activity, RestActivity)
    assert activity.members["Mei"].end == engine.end
    assert activity.latest_end == engine.end


def test_future_same_day_rest_keeps_requested_end(engine):
    engine.now = at(1, "18:08")
    engine.select("Mei", choose("select_rest", arguments={"until": "21:00"}))
    assert engine.activities[engine.current["Mei"]].members["Mei"].end == at(1, "21:00")


def test_no_activity_feedback_survives_checkpoint_and_clears_on_success(engine):
    engine.now = at(1, "19:00")
    action = choose("select_rest", arguments={"until": "19:00"})
    with pytest.raises(Rejected, match="after the current time") as caught:
        engine.select("Mei", action)
    engine.feedback("Mei", str(caught.value))
    restored = ActivityEngine(engine.sim, engine.state())
    restored.now, restored.end = engine.now, engine.end
    assert "after the current time" in restored.observation("Mei").situation
    restored.select("Mei", choose("select_rest", arguments={"until": "06:00"}))
    assert "Mei" not in restored.selection_feedback


def test_legacy_selection_rejection_is_visible_on_next_choice(engine):
    engine.reject("Mei", choose("select_move", target="missing"), "Choose an available place.")
    assert "Choose an available place." in engine.observation("Mei").situation
