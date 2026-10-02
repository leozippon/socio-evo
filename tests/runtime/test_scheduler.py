import json

import pytest
from pydantic import ValidationError

from core.agent.evolution import Trigger as Cadence
from core.interaction import time_at
from runtime.scenes import SceneConfig
from runtime.scheduler import Calendar, Trigger, TriggerKind, TriggerQueue
from runtime.simulation import Intervention, SimulationConfig

DAILY, WEEKLY, MONTHLY = Cadence.DAILY, Cadence.WEEKLY, Cadence.MONTHLY


def calendar(**changes) -> Calendar:
    settings = {
        "day_start": "07:00",
        "slots": [{"name": "morning", "start": "09:00"}, {"name": "evening", "start": "18:00"}],
        "day_end": "22:00",
        "weekly_days": 2,
        "monthly_days": 3,
    }
    return Calendar.model_validate(settings | changes)


def test_queue_orders_by_time_then_kind_then_push_and_its_state_round_trips():
    noon = time_at(1, "12:00")
    pushed = [
        Trigger(time=noon, kind=TriggerKind.DAY_END),
        Trigger(time=noon, kind=TriggerKind.SLOT, payload={"slot": "b"}),
        Trigger(time=time_at(1, "07:00"), kind=TriggerKind.DAY_START),
        Trigger(time=noon, kind=TriggerKind.SLOT, payload={"slot": "a"}),
        Trigger(time=noon, kind=TriggerKind.INTERVENTION, payload={"announcement": "Hello."}),
    ]
    queue = TriggerQueue(pushed)
    state = queue.state()
    assert state == [pushed[2], pushed[4], pushed[1], pushed[3], pushed[0]]

    stored = json.loads(json.dumps([trigger.model_dump(mode="json") for trigger in state]))
    restored = TriggerQueue(Trigger.model_validate(trigger) for trigger in stored)
    later = Trigger(time=noon, kind=TriggerKind.SLOT, payload={"slot": "c"})
    for each in (queue, restored):
        each.push(later)
    popped = [queue.pop() for _ in range(len(queue))]
    assert popped == [restored.pop() for _ in range(len(restored))]
    assert popped == [*state[:4], later, state[4]]
    with pytest.raises(IndexError):
        queue.pop()


def test_calendar_expands_days_and_schedules_cadences():
    days = calendar()
    assert (days.start(2), days.end(2)) == (time_at(2, "07:00"), time_at(2, "22:00"))
    assert days.slot_times(2) == [
        ("morning", time_at(2, "09:00")),
        ("evening", time_at(2, "18:00")),
    ]
    assert days.shortest_slot() == 4 * 60
    assert [days.cadences(day) for day in range(1, 7)] == [
        (DAILY,),
        (DAILY, WEEKLY),
        (DAILY, MONTHLY),
        (DAILY, WEEKLY),
        (DAILY,),
        (DAILY, WEEKLY, MONTHLY),
    ]
    assert calendar(weekly_days=7, monthly_days=28).cadences(28) == (DAILY, WEEKLY, MONTHLY)


@pytest.mark.parametrize(
    "changes",
    [
        {"slots": []},
        {"slots": [{"name": "evening", "start": "18:00"}, {"name": "morning", "start": "09:00"}]},
        {"slots": [{"name": "early", "start": "06:00"}]},
        {"slots": [{"name": "late", "start": "22:00"}]},
        {"slots": [{"name": "a", "start": "09:00"}, {"name": "a", "start": "12:00"}]},
        {"day_end": "24:00"},
        {"day_start": "7:00"},
        {"weekly_days": 0},
    ],
)
def test_calendar_is_strict(changes):
    with pytest.raises(ValidationError):
        calendar(**changes)


def test_interventions_and_scenes_must_fit_the_calendar():
    days = calendar()
    timely = [
        Intervention(day=day, at=at, announcement="Hello.")
        for day, at in ((1, None), (1, "07:00"), (2, "18:00"), (2, "22:00"))
    ]
    SimulationConfig(
        days=2, calendar=days, scenes=SceneConfig(turn_minutes=20), interventions=timely
    )
    for interventions in (
        [{"day": 3, "announcement": "Hello."}],
        [{"day": 1, "at": "23:00", "announcement": "Hello."}],
        [{"day": 1}],
    ):
        with pytest.raises(ValidationError):
            SimulationConfig(days=2, calendar=days, interventions=interventions)
    within_a_slot = [{"day": 1, "at": "13:33", "announcement": "Hello."}]
    with pytest.raises(ValidationError, match="only at the day start, a slot start or the day"):
        SimulationConfig(days=2, calendar=days, interventions=within_a_slot)
    with pytest.raises(ValidationError, match="shortest slot"):
        SimulationConfig(
            days=2, calendar=days, scenes=SceneConfig(conversation_turns=49, turn_minutes=5)
        )
