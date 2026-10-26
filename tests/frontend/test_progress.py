"""The progress of a run, from a world log written by hand: the lived days and what each counts,
verdicts, purses at the end of the day, the day in progress, and the real hours of the days."""

from __future__ import annotations

from frontend.progress import progress
from frontend.timeline import timeline
from infrastructure.storage import RunDirectory
from tests.frontend.conftest import entry, new_town
from tests.world.conftest import at
from world.clock import DAY

HOUR = 3600.0
NOTHING = {
    "claims": 0,
    "submissions": 0,
    "accepted": 0,
    "rejected": 0,
    "payments": 0,
    "paid": 0,
    "speeches": 0,
    "messages": 0,
    "gifts": 0,
    "purchases": 0,
    "skills_shared": 0,
    "ratings": 0,
    "journals": 0,
    "forced_sleeps": 0,
}


def write(run: RunDirectory, lines: list[tuple]) -> None:
    with run.world_log_path.open("a") as log:
        for seq, (kind, t, actor, real_time, payload) in enumerate(lines, start=1):
            log.write(entry(seq, kind, t, actor, real_time=real_time, **payload) + "\n")


def verdict(task: int, resolved: bool) -> dict:
    return {
        "task": task,
        "resolved": resolved,
        "status": "resolved" if resolved else "failed_tests",
        "fail_to_pass": [1, 1],
        "pass_to_pass": [2, 2],
    }


async def test_each_lived_day_counts_its_markers_and_ends_with_the_purses_then(tmp_path):
    run, _ = new_town(tmp_path)  # Mei $120, Tomas $180, Aisha $30
    write(
        run,
        [
            ("wake", at("07:00"), "Mei", 1000.0, {}),
            ("claim", at("09:00"), "Mei", 1001.0, {"task": 1, "instance_id": "one"}),
            ("claim", at("09:10"), "Tomas", 1002.0, {"task": 2, "instance_id": "two"}),
            (
                "speech",
                at("09:30"),
                "Tomas",
                1003.0,
                {"text": "Hi", "to": ["Mei"], "private": False},
            ),
            (
                "speech",
                at("09:31"),
                "Mei",
                1004.0,
                {"text": "Hi", "to": ["Tomas"], "private": False},
            ),
            ("gift", at("09:32"), "Mei", 1005.0, {"to": "Tomas", "amount": 5}),
            ("skill_shared", at("09:33"), "Mei", 1006.0, {"to": "Tomas", "skill": "triage"}),
            ("submission", at("10:00"), "Mei", 1007.0, {"task": 1}),
            ("verdict", at("10:00"), "Mei", 1008.0, verdict(1, True)),
            ("payment", at("10:00"), "Mei", 1009.0, {"task": 1, "amount": 20, "purse": 135}),
            ("submission", at("11:00"), "Tomas", 1010.0, {"task": 2}),
            ("verdict", at("11:00"), "Tomas", 1011.0, verdict(2, False)),
            (
                "sleep",
                at("22:00"),
                "Mei",
                1012.0,
                {"journal": "j", "day": 1, "wake": 0, "ratings_read": []},
            ),
            ("rating", at("22:00"), "Mei", 1013.0, {"rated": "Tomas", "score": 4, "reason": "r"}),
            ("settlement", DAY, "Mei", 1014.0, {"purse": 105}),
            ("settlement", DAY, "Tomas", 1015.0, {"purse": 155}),
            ("settlement", DAY, "Aisha", 1016.0, {"purse": 0}),
            # Past midnight, but still the first lived day: it ends at its checkpoint.
            ("forced_sleep", at("02:00", day=2), "Aisha", 1017.0, {"wake": at("07:00", day=2)}),
            ("checkpoint", at("02:30", day=2), None, 1000.0 + 2.5 * HOUR, {"day": 1}),
            ("wake", at("07:00", day=2), "Mei", 9100.0, {}),
            ("claim", at("09:00", day=2), "Mei", 9101.0, {"task": 3, "instance_id": "three"}),
            ("submission", at("09:20", day=2), "Mei", 9102.0, {"task": 3}),  # awaiting the verdict
            ("gift", at("09:30", day=2), "Tomas", 9103.0, {"to": "Aisha", "amount": 10}),
        ],
    )
    assert progress(timeline(run.root)) == {
        "day": 2,
        "now": at("09:30", day=2),
        "clock": "09:30",
        "hours_per_day": 2.5,
        "currency": "$",
        "daily": [
            {"day": 1, "date": "2001-01-01", "in_progress": False, "hours": 2.5}
            | NOTHING
            | {"claims": 2, "submissions": 2, "accepted": 1, "rejected": 1}
            | {"payments": 1, "paid": 20, "speeches": 2, "gifts": 1, "skills_shared": 1}
            | {"ratings": 1, "journals": 1, "forced_sleeps": 1}
            | {"purse": {"min": 0, "median": 105, "max": 155}},
            {"day": 2, "date": "2001-01-02", "in_progress": True, "hours": None}
            | NOTHING
            | {"claims": 1, "submissions": 1, "gifts": 1}
            | {"purse": {"min": 10, "median": 105, "max": 145}},
        ],
    }


async def test_a_day_lived_again_is_timed_from_the_resumption(tmp_path):
    run, _ = new_town(tmp_path)
    before = progress(timeline(run.root))
    assert (before["day"], before["hours_per_day"]) == (1, None)
    assert before["daily"] == [
        {"day": 1, "date": "2001-01-01", "in_progress": True, "hours": None}
        | NOTHING
        | {"purse": {"min": 30, "median": 120, "max": 180}}
    ]

    write(
        run,
        [
            ("wake", at("07:00"), "Mei", 0.0, {}),
            ("checkpoint", at("02:30", day=2), None, 2 * HOUR, {"day": 1}),
            ("claim", at("09:00", day=2), "Mei", 2 * HOUR + 60, {"task": 1, "instance_id": "a"}),
            ("resume", at("02:30", day=2), None, 5 * HOUR, {"day": 1, "time": at("02:30", day=2)}),
            ("wake", at("07:00", day=2), "Mei", 5 * HOUR + 60, {}),
            ("checkpoint", at("02:30", day=3), None, 8 * HOUR, {"day": 2}),
        ],
    )
    after = progress(timeline(run.root))
    assert (after["day"], after["clock"], after["hours_per_day"]) == (2, "02:30", 2.5)
    assert [(d["day"], d["in_progress"], d["hours"], d["claims"]) for d in after["daily"]] == [
        (1, False, 2.0, 0),
        (2, False, 3.0, 0),  # the claim of the lost day is set aside, and its hours too
    ]
