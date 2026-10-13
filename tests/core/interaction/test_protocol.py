from datetime import date

import pytest
from pydantic import ValidationError

from core.interaction import (
    MINUTES_PER_DAY,
    Currency,
    Event,
    EventKind,
    MayPass,
    Observation,
    Percept,
    Setting,
    Witness,
    capital,
    clock_of,
    day_of,
    format_time,
    lived_day,
    ordinal,
    tell,
    time_at,
    weekday,
)


def test_time_helpers_agree():
    time = time_at(3, "09:05")
    assert time == 2 * MINUTES_PER_DAY + 9 * 60 + 5
    assert (day_of(time), clock_of(time), format_time(time)) == (3, "09:05", "Day 3 09:05")
    assert format_time(0) == "Day 1 00:00"
    assert format_time(MINUTES_PER_DAY - 1) == "Day 1 23:59"
    assert day_of(MINUTES_PER_DAY) == 2


def test_a_day_is_told_by_its_weekday_and_date_whoever_tells_it():
    monday = Setting().start_date
    assert lived_day(1, monday) == "Monday, 1 January"
    assert lived_day(5, monday) == "Friday, 5 January"
    assert lived_day(8, monday) == "Monday, 8 January"
    assert lived_day(32, monday) == "Thursday, 1 February"
    assert [ordinal(n) for n in (11, 20, 42, 101, 112, 123)] == [
        "eleventh",
        "twentieth",
        "forty-second",
        "101st",
        "112th",
        "123rd",
    ]
    with pytest.raises(ValueError):
        lived_day(0, monday)
    with pytest.raises(ValueError):
        ordinal(0)


def test_the_weekday_of_day_one_follows_from_the_start_date():
    wednesday = date(2026, 10, 14)
    assert lived_day(1, wednesday) == "Wednesday, 14 October"
    assert lived_day(5, wednesday) == "Sunday, 18 October"
    assert weekday(8, wednesday) == weekday(1, wednesday) == "Wednesday"
    assert lived_day(1, Setting().start_date) == "Monday, 1 January"


def test_an_amount_is_told_in_the_towns_currency():
    dollars = Currency(unit="dollar", units="dollars", symbol="$")
    assert [dollars.tell(n) for n in (30, 1, 0, -5)] == ["$30", "$1", "$0", "-$5"]
    crowns = Setting().currency
    assert [crowns.tell(n) for n in (30, 1, -1, 0, -12)] == [
        "30 crowns",
        "1 crown",
        "-1 crown",
        "0 crowns",
        "-12 crowns",
    ]
    with pytest.raises(ValidationError):
        Currency(units="dollars")


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


def test_percept_is_the_event_without_truth_fields_as_its_witness_is_told_it():
    event = _event()
    hidden = {"payload", "audience", "personal"}
    assert set(Percept.model_fields) == set(Event.model_fields) - hidden
    assert event.percept("ben").model_dump() == event.model_dump(exclude=hidden)

    told = event.model_copy(update={"personal": {"ben": "Ana says to you: good morning."}})
    assert told.percept("ben").text == "Ana says to you: good morning."
    assert told.percept("cai").model_dump() == event.model_dump(exclude=hidden)


def test_a_telling_names_its_witness_you_where_its_name_stood():
    def drawn(you: Witness) -> str:
        return (
            f"{capital(you.listed(['Ana', 'Ben', 'Cai']))} reached for it. "
            f"{capital(you('Cai'))} got it, and the clerk took {you.whose('Cai')} name."
        )

    text, personal = tell(drawn, ["Ana", "Cai", "Dan"])
    assert text == "Ana, Ben and Cai reached for it. Cai got it, and the clerk took Cai's name."
    assert personal == {
        "Ana": "You, Ben and Cai reached for it. Cai got it, and the clerk took Cai's name.",
        "Cai": "Ana, Ben and you reached for it. You got it, and the clerk took your name.",
    }
    assert tell("Ana left.", ["Ben"]) == ("Ana left.", {})


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
            allowed=(MayPass(),),
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


@pytest.mark.parametrize("allowed", [(), ("speak",), ({"kind": "dance"},)])
def test_observation_needs_known_allowances(allowed):
    with pytest.raises(ValidationError):
        Observation(agent="ben", time=0, place="home", scene="s", situation="", allowed=allowed)
