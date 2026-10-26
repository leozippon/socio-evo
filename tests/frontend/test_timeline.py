"""The timeline of a run, built from the world log of a day lived in a real world: the base
events contiguous per resident, conversation layered over what it interrupted, the markers, the
purse, the days and when they were lived in real time, a growing log read a line at a time, and
a lost day set aside on resumption."""

from __future__ import annotations

import json
from typing import Any

import pytest

from frontend import timeline as module
from frontend.timeline import timeline
from tests.frontend.conftest import entry, live_a_day, new_town
from tests.world.conftest import at
from world.clock import DAY


def lane(data: dict[str, Any], name: str) -> dict[str, Any]:
    return next(r for r in data["residents"] if r["name"] == name)


def spans(data: dict[str, Any], name: str) -> list[tuple[str, int, int, str | None, int | None]]:
    return [
        (s["kind"], s["start"], s["end"], s["place"], s["task"])
        for s in lane(data, name)["segments"]
    ]


async def test_a_day_becomes_contiguous_lanes_with_conversation_layered_over_work(tmp_path):
    run, town = new_town(tmp_path)
    middle: list[dict[str, Any]] = []
    await live_a_day(town, lambda: middle.append(json.loads(json.dumps(timeline(run.root)))))
    await town.close()
    data = timeline(run.root)
    assert json.loads(json.dumps(data)) == data
    start, now = at("02:30"), list(town.world.log.entries())[-1]["sim_time"]
    assert data["start"] == start and data["now"] == now >= at("18:00", day=2)
    assert data["start_date"] == "2001-01-01" and data["places"]["workshop"] == "the workshop"

    for resident in data["residents"]:  # contiguous from the start to now, each distinct
        segments = resident["segments"]
        assert segments[0]["start"] == start and segments[-1]["end"] == now
        for a, b in zip(segments, segments[1:], strict=False):
            assert a["end"] == b["start"] and a["start"] < a["end"]
            assert (a["kind"], a["place"], a["task"]) != (b["kind"], b["place"], b["task"])

    home, flat = "mill-street-house", "college-flat"
    assert spans(data, "Mei") == [
        ("sleep", start, at("07:00"), home, None),
        ("movement", at("07:00"), at("07:10"), "workshop", None),
        ("idle", at("07:10"), at("09:00"), "workshop", None),
        ("work", at("09:00"), at("10:00"), "workshop", 1),
        ("work", at("10:00"), at("10:30"), "workshop", None),
        ("movement", at("10:30"), at("10:40"), home, None),
        ("idle", at("10:40"), at("22:00"), home, None),
        ("sleep", at("22:00"), at("07:00", day=2), home, None),
        ("idle", at("07:00", day=2), now, home, None),
    ]
    assert spans(data, "Tomas")[3:7] == [
        ("work", at("10:00"), at("18:00"), "workshop", 2),
        ("idle", at("18:00"), at("22:00"), "workshop", None),  # after leaving work
        ("movement", at("22:00"), at("22:10"), flat, None),
        ("idle", at("22:10"), at("23:00"), flat, None),
    ]
    assert spans(data, "Aisha") == [
        ("sleep", start, at("07:00"), home, None),
        ("idle", at("07:00"), at("02:00", day=2), home, None),
        ("sleep", at("02:00", day=2), at("07:00", day=2), home, None),
        ("idle", at("07:00", day=2), now, home, None),
    ]

    # Tomas's remark at 09:30 drew nobody in (Mei was at work); the conversation begins with
    # her answer at 09:32, for both of them.
    talk = {"start": at("09:32"), "end": at("09:35"), "place": "workshop"}
    assert lane(data, "Mei")["conversations"] == [talk | {"over": "work", "with": ["Tomas"]}]
    assert lane(data, "Tomas")["conversations"] == [talk | {"over": "idle", "with": ["Mei"]}]
    assert lane(data, "Aisha")["conversations"] == []

    def markers(name: str) -> list[tuple[str, int]]:
        return [(m["kind"], m["t"]) for m in lane(data, name)["markers"]]

    assert markers("Mei") == [
        ("claim", at("09:00")),
        ("speech", at("09:32")),
        ("gift", at("09:32")),
        ("skill_shared", at("09:32")),
        ("submission", at("10:00")),
        ("payment", at("10:00")),
        ("journal", at("22:00")),
        ("rating", at("22:00")),
    ]
    mei = {m["kind"]: m for m in lane(data, "Mei")["markers"]}
    assert mei["speech"]["text"] == "Nearly done." and mei["speech"]["to"] == ["Tomas"]
    assert mei["submission"]["resolved"] is True and mei["payment"]["amount"] == 20
    assert mei["journal"]["text"] == "I fixed task 1." and mei["rating"]["score"] == 4
    tomas = {m["kind"]: m for m in lane(data, "Tomas")["markers"]}
    assert tomas["submission"]["resolved"] is False
    assert tomas["submission"]["status"] == "failed_tests"
    assert tomas["submission"]["fail_to_pass"] == [1, 3]
    assert tomas["expiry"]["t"] == DAY and tomas["expiry"]["task"] == 2  # the first midnight
    assert markers("Aisha") == [("forced_sleep", at("02:00", day=2))]

    assert lane(data, "Mei")["purse"] == [
        [start, 120],
        [at("09:32"), 115],
        [at("10:00"), 135],
        [DAY, 115],  # rent on Mill Street is $20
    ]
    assert lane(data, "Tomas")["purse"] == [[start, 180], [at("09:32"), 185], [DAY, 155]]
    assert lane(data, "Aisha")["purse"] == [[start, 30], [DAY, 10]]
    entries = list(town.world.log.entries())
    first = next(e for e in entries if e["kind"] in module._FOLDED)["real_time"]  # the viewer's
    (closed,) = [e["real_time"] for e in entries if e["kind"] == "checkpoint"]
    assert data["days"] == [
        {
            "day": 1,
            "start": start,
            "end": at("02:30", day=2),
            "real_start": first,
            "real_end": closed,
        },
        {
            "day": 2,
            "start": at("02:30", day=2),
            "end": None,
            "real_start": closed,
            "real_end": None,
        },
    ]

    # Read while the day was lived: the open segment and conversation ended at that moment.
    (early,) = middle
    assert early["now"] == at("09:35") and early["days"] == [
        {"day": 1, "start": start, "end": None, "real_start": first, "real_end": None}
    ]
    assert spans(early, "Mei")[-1] == ("work", at("09:00"), at("09:35"), "workshop", 1)
    module._caches.clear()
    assert timeline(run.root) == data  # the incremental reading equals a reading from scratch


async def test_a_line_being_written_waits_and_an_unchanged_log_is_not_read_again(tmp_path):
    run, town = new_town(tmp_path)
    await live_a_day(town)
    await town.close()
    before = timeline(run.root)
    assert timeline(run.root) is before
    last = list(town.world.log.entries())[-1]
    line = json.dumps(
        last | {"seq": last["seq"] + 1, "kind": "time", "sim_time": last["sim_time"] + 60}
    )
    with run.world_log_path.open("a") as log:
        log.write(line[:20])
    assert timeline(run.root)["now"] == last["sim_time"]
    with run.world_log_path.open("a") as log:
        log.write(line[20:] + "\n")
    after = timeline(run.root)
    assert after["now"] == last["sim_time"] + 60
    assert all(r["segments"][-1]["end"] == after["now"] for r in after["residents"])


async def test_a_run_without_entries_is_everyone_asleep_at_the_start(tmp_path):
    run, _ = new_town(tmp_path)
    data = timeline(run.root)
    assert data["now"] == data["start"] == at("02:30")
    assert data["days"] == [
        {"day": 1, "start": at("02:30"), "end": None, "real_start": None, "real_end": None}
    ]
    assert [r["segments"] for r in data["residents"]][0] == [
        {
            "kind": "sleep",
            "start": at("02:30"),
            "end": at("02:30"),
            "place": "mill-street-house",
            "task": None,
        }
    ]


async def test_the_entries_of_a_lost_day_are_set_aside_on_resumption(tmp_path):
    run, town = new_town(tmp_path)
    town.start(until_day=2)
    town.rest()
    await town.until("07:00", day=2)
    state = town.checkpoints[0][1]
    await town.call("Mei", "go", place="workshop")  # the day is lost after this
    await town.until("08:00", day=2)
    await town.close()
    assert "movement" in [s["kind"] for s in lane(timeline(run.root), "Mei")["segments"]]

    _, again = new_town(tmp_path)
    again.world.restore(json.loads(json.dumps(state)))
    again.start(until_day=2)
    again.rest()
    await again.until("07:05", day=2)
    await again.close()
    data = timeline(run.root)
    assert data["now"] == at("07:00", day=2)
    assert [s["kind"] for s in lane(data, "Mei")["segments"]] == ["sleep", "idle", "sleep", "idle"]
    entries = list(again.world.log.entries())
    real = {e["kind"]: e["real_time"] for e in entries if e["kind"] in ("checkpoint", "resume")}
    assert data["days"] == [  # the day lived again was begun at the resumption
        {
            "day": 1,
            "start": at("02:30"),
            "end": at("02:30", day=2),
            "real_start": next(e for e in entries if e["kind"] in module._FOLDED)["real_time"],
            "real_end": real["checkpoint"],
        },
        {
            "day": 2,
            "start": at("02:30", day=2),
            "end": None,
            "real_start": real["resume"],
            "real_end": None,
        },
    ]


def test_resuming_the_start_sets_aside_all_before_and_a_checkpoint_never_logged_fails(tmp_path):
    run, _ = new_town(tmp_path)
    lost = [entry(1, "wake", at("07:00"), "Mei"), entry(2, "resume", at("02:30"), day=0, time=0)]
    run.world_log_path.write_text("\n".join(lost) + "\n")
    data = timeline(run.root)
    assert data["now"] == at("02:30")
    assert [s["kind"] for s in lane(data, "Mei")["segments"]] == ["sleep"]

    with run.world_log_path.open("a") as log:
        log.write(entry(3, "resume", at("02:30", day=2), day=1, time=0) + "\n")
    for _ in range(2):  # a log that cannot be read fails every time, never half-read
        with pytest.raises(ValueError, match="resumes day 1, which has no checkpoint"):
            timeline(run.root)
