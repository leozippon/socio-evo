import pytest
from pydantic import ValidationError

from core.interaction import (
    MINUTES_PER_DAY,
    Event,
    EventKind,
    Observation,
    Percept,
    clock_of,
    day_of,
    format_time,
    lived_day,
    ordinal,
    time_at,
)


def test_time_helpers_agree():
    time = time_at(3, "09:05")
    assert time == 2 * MINUTES_PER_DAY + 9 * 60 + 5
    assert (day_of(time), clock_of(time), format_time(time)) == (3, "09:05", "Day 3 09:05")
    assert format_time(0) == "Day 1 00:00"
    assert format_time(MINUTES_PER_DAY - 1) == "Day 1 23:59"
    assert day_of(MINUTES_PER_DAY) == 2


def test_a_resident_tells_a_day_by_its_weekday_and_its_count_since_arriving():
    assert lived_day(1) == "Monday, your first day in town"
    assert lived_day(5) == "Friday, your fifth day in town"
    assert lived_day(8) == "Monday, your eighth day in town"
    assert lived_day(28) == "Sunday, your twenty-eighth day in town"
    assert [ordinal(n) for n in (11, 20, 42, 101, 112, 123)] == [
        "eleventh",
        "twentieth",
        "forty-second",
        "101st",
        "112th",
        "123rd",
    ]
    for bad in (lived_day, ordinal):
        with pytest.raises(ValueError):
            bad(0)


@pytest.mark.parametrize(
    ("day", "clock"), [(0, "09:00"), (1, "24:00"), (1, "9:00"), (1, "09:60"), (1, " 09:00")]
)
def test_time_at_rejects_invalid_input(day, clock):
    with pytest.raises(ValueError):
        time_at(day, clock)


def test_negative_time_is_rejected():
    with pytest.raises(ValueError):
        day_of(-1)
    with pytest.raises(ValidationError):
        Event(seq=0, time=-1, kind=EventKind.DAY_STARTED, text="")


def _event() -> Event:
    return Event(
        seq=7,
        time=time_at(1, "10:00"),
        kind=EventKind.SPEECH,
        actor="ana",
        place="cafe",
        scene="cafe-1",
        audience=("ben",),
        text="Ana says: good morning.",
        payload={"sincere": False},
    )


def test_percept_is_the_event_without_truth_fields():
    event = _event()
    assert set(Percept.model_fields) == set(Event.model_fields) - {"payload", "audience"}
    assert event.percept().model_dump() == event.model_dump(exclude={"payload", "audience"})


def test_truth_cannot_reach_an_observation():
    event = _event()
    with pytest.raises(ValidationError):
        Percept(**event.model_dump())
    with pytest.raises(ValidationError):
        Observation(
            agent="ben",
            time=event.time,
            place="cafe",
            scene="cafe-1",
            situation="You are at the cafe.",
            percepts=(event,),
            allowed=("speak",),
        )


def test_records_are_immutable_closed_and_json_round_trip():
    event = _event()
    assert Event.model_validate_json(event.model_dump_json()) == event
    with pytest.raises(ValidationError):
        event.text = "rewritten"
    with pytest.raises(ValidationError):
        Event(**event.model_dump(), mood="tense")
    with pytest.raises(ValidationError):
        Event(**{**event.model_dump(), "payload": {"handle": object()}})


@pytest.mark.parametrize("allowed", [(), ("dance",)])
def test_observation_needs_known_allowed_actions(allowed):
    with pytest.raises(ValidationError):
        Observation(agent="ben", time=0, place="home", scene="s", situation="", allowed=allowed)
