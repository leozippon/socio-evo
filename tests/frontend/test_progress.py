"""The progress of a run, from a world log written by hand: the lived days and what each counts,
the residents' markers and the town's, verdicts, the money held at the end of the day, the day
in progress, and the real hours of the days."""

from __future__ import annotations

from frontend.progress import progress
from frontend.timeline import timeline
from infrastructure.storage import RunDirectory
from tests.frontend.conftest import entry, new_town
from tests.world.conftest import at
from world.clock import DAY

HOUR = 3600.0
NOTHING = {
    "arrived": 0,
    "claims": 0,
    "assigned": 0,
    "submissions": 0,
    "accepted": 0,
    "rejected": 0,
    "withdrawn": 0,
    "sales": 0,
    "dishes": 0,
    "examinations": 0,
    "treatments": 0,
    "announcements": 0,
    "speeches": 0,
    "messages": 0,
    "gifts": 0,
    "journals": 0,
    "illnesses": 0,
    "bedridden": 0,
    "forced_sleeps": 0,
}


def write(run: RunDirectory, lines: list[tuple]) -> None:
    with run.world_log_path.open("a") as log:
        for seq, (kind, t, actor, real_time, payload) in enumerate(lines, start=1):
            log.write(entry(seq, kind, t, actor, real_time=real_time, **payload) + "\n")


def wage(money: int) -> dict:
    """The midnight's wages: no time at work and no tax, the rent owed, the money held as it
    stood."""
    return {
        "hours": 0.0,
        "wages": 0,
        "tax": 0,
        "tax_from_purse": 0,
        "owed_before": 0,
        "rent": 20,
        "charges": 0,
        "arrears_before": 0,
        "remainder": -20,
        "paid": 0,
        "owed": 0,
        "arrears": 20,
        "money": money,
    }


SETTLEMENT = {
    "nourishment": 0,
    "satiety": 20.0,
    "energy": 70.0,
    "health": 100.0,
    "night": {"poor_home": -2.0, "recovery": 5.0},
    "ill": 0,
}
"""The midnight statement's payload: nothing eaten, the body as it stood."""


def verdict(task: int, resolved: bool) -> dict:
    return {
        "task": task,
        "resolved": resolved,
        "status": "resolved" if resolved else "failed_tests",
        "fail_to_pass": [1, 1],
        "pass_to_pass": [2, 2],
        "held": True,
    }


def arrived(task: int) -> dict:
    return {"task": task, "instance_id": f"t{task}", "repo": "org/repo"}


def speech(text: str, to: list[str], members: list[str]) -> dict:
    return {"text": text, "to": to, "private": False, "members": members}


def move(reason: str, source: str, target: str, **fields) -> dict:
    """A move's payload: units of an item, or money alone, from `source` to `target`."""
    found = {"item": None, "units": 0, "source": source, "target": target, "money": 0}
    return found | {"reason": reason, "seller": None} | fields


def sale(item: str, units: int, price: int, buyer: str, kitchen: bool) -> dict:
    target, money = "larder" if kitchen else buyer, units * price
    return move("buy", "shelves", target, item=item, units=units, money=money, seller="Olga")


EXAMINATION = {
    "patient": "Mei", "fee": 10, "satiety": 50.0, "energy": 60.0, "health": 100.0, "ill": 0,
    "night": {},
}  # fmt: skip
TREATMENT = {
    "patient": "Mei", "fee": 30, "restores": 25.0, "before": 100.0, "health": 100.0, "ill": 0,
    "bedridden": False,
}  # fmt: skip
BEDRIDDEN = {"day": 2, "home": "mill-street-house", "from": None, "carried": False, "task": None}


async def test_each_lived_day_counts_its_markers_and_ends_with_the_money_then(tmp_path):
    run, _ = new_town(tmp_path)  # Mei $120, Tomas $180, Aisha $30, the four trades $100 each
    served = move("buy", "portions", "Mei", item="soup", units=1, money=8, seller="Jonas")
    cook = {"dish": "soup", "name": "vegetable soup", "portions": 1, "used": {"vegetables": 2}}
    write(
        run,
        [
            ("wake", at("07:00"), "Mei", 1000.0, {}),
            ("task_arrived", at("08:00"), None, 1000.1, arrived(1)),
            ("task_arrived", at("08:00"), None, 1000.2, arrived(2)),
            ("claim", at("09:00"), "Mei", 1001.0, {"task": 1, "instance_id": "t1"}),
            ("assign", at("09:10"), "Tomas", 1002.0, {"task": 2, "to": "Aisha", "from": None}),
            ("speech", at("09:30"), "Tomas", 1003.0, speech("Hi", ["Mei"], [])),
            ("speech", at("09:31"), "Mei", 1004.0, speech("Hi", ["Tomas"], ["Mei", "Tomas"])),
            ("move", at("09:32"), "Mei", 1005.0, move("pass", "Mei", "Tomas", money=5)),
            ("submission", at("10:00"), "Mei", 1007.0, {"task": 1}),
            ("verdict", at("10:00"), "Mei", 1008.0, verdict(1, True)),
            (
                "service",
                at("10:00"),
                "Mei",
                1009.0,
                {"for": "task", "task": 1, "amount": 20, "paid": 20, "owed": 0, "money": 135},
            ),
            ("submission", at("11:00"), "Aisha", 1010.0, {"task": 2}),
            ("verdict", at("11:00"), "Aisha", 1011.0, verdict(2, False)),
            ("move", at("11:30"), "Jonas", 1011.1, sale("vegetables", 2, 3, "Jonas", kitchen=True)),
            ("cook", at("11:40"), "Jonas", 1011.2, cook),
            ("move", at("12:00"), "Mei", 1011.3, served),
            ("move", at("12:10"), "Mei", 1011.4, sale("bread", 1, 4, "Mei", kitchen=False)),
            ("examination", at("13:00"), "Lucia", 1011.5, EXAMINATION),
            ("treatment", at("13:01"), "Lucia", 1011.6, TREATMENT),
            ("announcement", at("14:00"), "Vera", 1011.7, {"text": "Hello"}),
            ("sleep", at("22:00"), "Mei", 1012.0, {"journal": "j", "day": 1, "wake": 0}),
            (  # to bed without a journal entry: no journal counted
                "sleep",
                at("22:10"),
                "Tomas",
                1013.5,
                {"journal": None, "day": 1, "wake": 0},
            ),
            ("wage", DAY, "Mei", 1014.0, wage(83)),
            ("settlement", DAY, "Mei", 1014.1, SETTLEMENT),
            ("wage", DAY, "Tomas", 1015.0, wage(185)),
            ("settlement", DAY, "Tomas", 1015.1, SETTLEMENT),
            ("illness", DAY, "Aisha", 1015.5, {"chance": 0.05, "nights": 5, "health": 100.0}),
            ("wage", DAY, "Aisha", 1016.0, wage(30)),
            ("settlement", DAY, "Aisha", 1016.1, SETTLEMENT),
            ("task_withdrawn", DAY, None, 1016.2, {"task": 2, "holder": "Aisha"}),
            # Past midnight, but still the first lived day: it ends at its checkpoint.
            ("forced_sleep", at("02:00", day=2), "Aisha", 1017.0, {"wake": at("07:00", day=2)}),
            ("checkpoint", at("02:30", day=2), None, 1000.0 + 2.5 * HOUR, {"day": 1}),
            ("wake", at("07:00", day=2), "Mei", 9100.0, {}),
            ("task_arrived", at("08:00", day=2), None, 9100.5, arrived(3)),
            ("claim", at("09:00", day=2), "Mei", 9101.0, {"task": 3, "instance_id": "t3"}),
            ("submission", at("09:20", day=2), "Mei", 9102.0, {"task": 3}),  # awaiting the verdict
            ("move", at("09:30", day=2), "Tomas", 9103.0, move("pass", "Tomas", "Aisha", money=10)),
            ("bedridden", 2 * DAY, "Aisha", 9104.0, BEDRIDDEN),
        ],
    )
    assert progress(timeline(run.root)) == {
        "day": 2,
        "now": 2 * DAY,
        "clock": "00:00",
        "hours_per_day": 2.5,
        "currency": "$",
        "daily": [
            {"day": 1, "date": "2001-01-01", "in_progress": False, "hours": 2.5}
            | NOTHING
            | {"arrived": 2, "claims": 1, "assigned": 1, "submissions": 2, "accepted": 1}
            | {"rejected": 1, "withdrawn": 1, "sales": 2, "dishes": 1, "examinations": 1}
            | {"treatments": 1, "announcements": 1, "speeches": 2, "gifts": 1}
            | {"journals": 1, "illnesses": 1, "forced_sleeps": 1}
            | {"purse": {"min": 30, "median": 100, "max": 185}},
            {"day": 2, "date": "2001-01-02", "in_progress": True, "hours": None}
            | NOTHING
            | {"arrived": 1, "claims": 1, "submissions": 1, "gifts": 1, "bedridden": 1}
            | {"purse": {"min": 40, "median": 100, "max": 175}},
        ],
    }


async def test_a_day_lived_again_is_timed_from_the_resumption(tmp_path):
    run, _ = new_town(tmp_path)
    before = progress(timeline(run.root))
    assert (before["day"], before["hours_per_day"]) == (1, None)
    assert before["daily"] == [
        {"day": 1, "date": "2001-01-01", "in_progress": True, "hours": None}
        | NOTHING
        | {"purse": {"min": 30, "median": 100, "max": 180}}
    ]

    write(
        run,
        [
            ("wake", at("07:00"), "Mei", 0.0, {}),
            ("checkpoint", at("02:30", day=2), None, 2 * HOUR, {"day": 1}),
            ("task_arrived", at("08:00", day=2), None, 2 * HOUR + 30, arrived(1)),
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
