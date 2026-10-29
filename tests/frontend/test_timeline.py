"""The timeline of a run, built from the world log of a day lived in a real world: the base
events contiguous per resident, conversation layered over what it interrupted, the markers, the
moves among them as the log records them, the money held, the Office's tasks, the prices, orders
and fees agreeing with the checkpoint, the days and when they were lived in real time, a lane in
bed until treated, a growing log read a line at a time, and a lost day set aside on
resumption."""

from __future__ import annotations

import json
from typing import Any

import pytest

from frontend import timeline as module
from frontend.timeline import timeline
from tests.support.runs import entry, live_a_day, new_town
from tests.support.towns import at
from world.clock import DAY


def lane(data: dict[str, Any], name: str) -> dict[str, Any]:
    return next(r for r in data["residents"] if r["name"] == name)


def spans(data: dict[str, Any], name: str) -> list[tuple[str, int, int, str | None, int | None]]:
    return [
        (s["kind"], s["start"], s["end"], s["place"], s["task"])
        for s in lane(data, name)["segments"]
    ]


def state_at(points: list[list[Any]], t: int) -> Any:
    """The state of a series of the timeline at `t`."""
    return [state for when, state in points if when <= t][-1]


def fields(marker: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in marker.items() if k not in ("seq", "t", "place", "kind")}


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
        ("movement", at("10:30"), at("10:40"), "clinic", None),
        ("movement", at("10:40"), at("10:50"), "cafe", None),  # seen at the clinic on arrival
        ("idle", at("10:50"), at("11:00"), "cafe", None),
        ("movement", at("11:00"), at("11:10"), "store", None),
        ("idle", at("11:10"), at("11:15"), "store", None),
        ("movement", at("11:15"), at("11:25"), home, None),
        ("idle", at("11:25"), at("22:00"), home, None),
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
    assert spans(data, "Olga")[1:3] == [
        ("movement", at("07:00"), at("07:10"), "store", None),
        ("work", at("07:10"), at("18:00"), "store", None),
    ]

    # Tomas's remark at 09:30 drew nobody in (Mei was at work); the conversation begins with
    # her answer at 09:32, for both of them.
    talk = {"start": at("09:32"), "end": at("09:35"), "place": "workshop"}
    assert lane(data, "Mei")["conversations"] == [talk | {"over": "work", "with": ["Tomas"]}]
    assert lane(data, "Tomas")["conversations"] == [talk | {"over": "idle", "with": ["Mei"]}]
    assert lane(data, "Aisha")["conversations"] == []

    def markers(name: str) -> list[tuple[str, int]]:
        """The lane's markers but the body's, which come by the hour and are checked below; a
        move by its reason."""
        return [
            (m["reason"] if m["kind"] == "move" else m["kind"], m["t"])
            for m in lane(data, name)["markers"]
            if m["kind"] != "condition"
        ]

    assert markers("Mei") == [
        ("claim", at("09:00")),
        ("speech", at("09:32")),
        ("pass", at("09:32")),
        ("submission", at("10:00")),
        ("service", at("10:00")),
        ("buy", at("11:00")),
        ("eat", at("11:00")),
        ("eat", at("11:00")),  # the soup, which Jonas passed her unpaid on his own lane
        ("buy", at("11:15")),
        ("put", at("11:15")),
        ("eat", at("12:00")),
        ("put", at("12:05")),
        ("journal", at("22:00")),
        ("settlement", DAY),
    ]
    mei = {m["kind"]: m for m in lane(data, "Mei")["markers"]}
    assert mei["speech"]["text"] == "Nearly done." and mei["speech"]["to"] == ["Tomas"]
    assert mei["submission"]["resolved"] is True
    # Four fifths of the client's $50 for her task, a tenth of it withheld.
    assert fields(mei["service"]) == {"for": "task", "task": 1, "amount": 40, "tax": 4}
    assert mei["journal"]["text"] == "I fixed task 1."

    # Every move as the log records it, on the lane of the one who made it, with where it was;
    # a purchase with the tax withheld from what its seller took.
    def move(item, units, source, target, reason, money=0, seller=None, tax=0):
        found = {"item": item, "units": units, "source": source, "target": target}
        return found | {"money": money, "reason": reason, "seller": seller, "tax": tax}

    moves = [
        (m["place"], fields(m))
        for name in ("Mei", "Jonas", "Olga")
        for m in lane(data, name)["markers"]
        if m["kind"] == "move"
    ]
    assert moves == [
        ("workshop", move(None, 0, "Mei", "Tomas", "pass", money=5)),
        ("cafe", move("omelette", 1, "portions", "Mei", "buy", money=10, seller="Jonas", tax=1)),
        ("cafe", move("omelette", 1, "Mei", None, "eat")),
        ("cafe", move("soup", 1, "Mei", None, "eat")),
        ("store", move("bread", 3, "shelves", "Mei", "buy", money=12, seller="Olga", tax=1)),
        ("store", move("bread", 1, "Mei", "store", "put")),
        (home, move("bread", 1, "Mei", None, "eat")),
        (home, move("bread", 1, "Mei", home, "put")),
        ("store", move("eggs", 2, "shelves", "larder", "buy", money=4, seller="Olga")),
        ("store", move("vegetables", 5, "shelves", "larder", "buy", 20, seller="Olga", tax=2)),
        ("cafe", move("soup", 1, "portions", "Mei", "pass")),  # the chef's, unpaid
        ("store", move("bread", 1, "store", "Olga", "get")),
        ("store", move("bread", 1, "Olga", None, "eat")),
    ]
    # At midnight the treasury took her $20 of rent, which her purse could spare.
    assert {key: mei["settlement"][key] for key in ("hours", "rent", "rent_paid", "arrears")} == {
        "hours": 1.5,
        "rent": 20,
        "rent_paid": 20,
        "arrears": 0,
    }
    assert markers("Tomas") == [
        ("speech", at("09:30")),
        ("service", at("10:00")),
        ("claim", at("10:00")),
        ("submission", at("10:00")),
        ("assign", at("10:00")),
        ("journal", at("23:00")),
        ("settlement", DAY),
    ]
    tomas = {m["kind"]: m for m in lane(data, "Tomas")["markers"]}
    assert fields(tomas["service"]) == {"for": "team", "task": 1, "amount": 10, "tax": 1}
    assert fields(tomas["assign"]) == {"task": 3, "to": "Aisha", "from": None}
    assert tomas["submission"]["resolved"] is False
    assert tomas["submission"]["status"] == "failed_tests"
    assert tomas["submission"]["fail_to_pass"] == [1, 3]
    assert markers("Aisha") == [("settlement", DAY), ("forced_sleep", at("02:00", day=2))]
    felt = [m for m in lane(data, "Aisha")["markers"] if m["kind"] == "condition"]
    assert [(m["need"], m["band"], m["lowest"]) for m in felt][:3] == [
        ("satiety", "a little hungry", False),
        ("satiety", "hungry", False),
        ("satiety", "starving", True),
    ]
    assert all(0 <= m["value"] <= 100 for m in felt)
    assert felt[0]["value"] < 65 and felt[2]["value"] < 10
    # Aisha ate nothing all day and is hungry, not yet starving, at midnight; her home on Mill
    # Street has little comfort, and her purse, $20 and Vera's grant of $5, spares $15 of its rent
    # above the $10 it keeps: $5 is owed.
    midnight = next(m for m in lane(data, "Aisha")["markers"] if m["kind"] == "settlement")
    assert (midnight["rent"], midnight["charges"], midnight["rent_paid"]) == (20, 0, 15)
    assert (midnight["arrears"], midnight["salary"], midnight["salary_paid"]) == (5, 0, 0)
    assert midnight["nourishment"] == 0 and midnight["ill"] == 0
    assert 10 <= midnight["satiety"] < 35 and midnight["energy"] < 100
    assert midnight["health"] == 100 and midnight["night"] == {"poor_home": -2, "recovery": 5}

    # The work of the trades: the Store's counter, the kitchen, the surgery and the hall; the
    # sales are on the buyers' lanes.
    assert markers("Olga") == [
        ("price", at("07:10")),
        ("order", at("07:10")),
        ("get", at("11:15")),
        ("eat", at("11:15")),
        ("settlement", DAY),
        ("forced_sleep", at("02:00", day=2)),
    ]
    olga = {m["kind"]: m for m in lane(data, "Olga")["markers"]}
    assert fields(olga["order"]) == {
        "item": "bread", "name": "bread", "quantity": 5, "amount": 10, "arrives": at("08:00", 2),
    }  # fmt: skip
    jonas = [m for m in lane(data, "Jonas")["markers"] if m["kind"] == "cook"]
    assert [(m["dish"], m["portions"], m["used"]) for m in jonas] == [
        ("omelette", 1, {"eggs": 2, "vegetables": 1}),
        ("soup", 2, {"vegetables": 4}),
    ]
    lucia = [m for m in lane(data, "Lucia")["markers"] if m["kind"] in ("examination", "treatment")]
    assert [(m["kind"], m["patient"], m["fee"], m["tax"]) for m in lucia] == [
        ("examination", "Mei", 10, 1),
        ("treatment", "Mei", 30, 3),
    ]
    assert markers("Vera") == [
        ("announcement", at("07:10")),
        ("grant", at("07:10")),
        ("settlement", DAY),
        ("forced_sleep", at("02:00", day=2)),
    ]
    vera = {m["kind"]: m for m in lane(data, "Vera")["markers"]}
    assert vera["announcement"]["text"] == "The hall is open every day."
    assert fields(vera["grant"]) == {  # the treasury's $1000 and the vegetables' $2 of tax, less $5
        "to": "Aisha", "amount": 5, "reason": "For the rent.", "treasury": 997,
    }  # fmt: skip

    # The money held moves with every sum the log records: the money passed, the share of the
    # client's payment, the Hospital's fees, the dish and the bread, each paid by one and taken by
    # the other less the tax, the order, the grant, and the rent and the salary at midnight; the
    # soup served unpaid costs nothing.
    assert lane(data, "Mei")["purse"] == [
        [start, 120],
        [at("09:32"), 115],
        [at("10:00"), 151],
        [at("10:40"), 141],
        [at("10:40"), 111],
        [at("11:00"), 101],
        [at("11:15"), 89],
        [DAY, 69],
    ]
    assert lane(data, "Tomas")["purse"] == [
        [start, 180],
        [at("09:32"), 185],
        [at("10:00"), 194],
        [DAY, 164],
    ]
    assert lane(data, "Aisha")["purse"] == [[start, 20], [at("07:10"), 25], [DAY, 10]]
    assert lane(data, "Olga")["purse"] == [
        [start, 100],
        [at("07:10"), 104],  # the eggs for the kitchen, $4, too little to tax
        [at("07:10"), 122],  # the vegetables, $20 less $2
        [at("07:10"), 112],  # her order of bread from the supplier
        [at("11:15"), 123],  # Mei's bread, $12 less $1
        [DAY, 93],
    ]
    assert lane(data, "Jonas")["purse"] == [
        [start, 100],
        [at("07:10"), 96],
        [at("07:10"), 76],
        [at("11:00"), 85],  # Mei's omelette, $10 less $1
        [DAY, 55],
    ]
    assert lane(data, "Lucia")["purse"] == [
        [start, 100],
        [at("10:40"), 109],
        [at("10:40"), 136],
        [DAY, 106],
    ]
    assert lane(data, "Vera")["purse"] == [[start, 100], [DAY, 100]]  # $30 of salary, $30 rent
    assert (vera["settlement"]["salary_paid"], vera["settlement"]["rent_paid"]) == (30, 30)

    # What came to the town itself, and the Office's tasks.
    assert [(m["kind"], m["t"]) for m in data["markers"]] == [
        *[("task_arrived", at("08:00"))] * 3,
        ("task_withdrawn", DAY),
        ("task_withdrawn", DAY),
        ("delivery", at("08:00", day=2)),
    ]
    withdrawn = {m["task"]: m["holder"] for m in data["markers"] if m["kind"] == "task_withdrawn"}
    assert withdrawn == {2: "Tomas", 3: "Aisha"}
    tasks = {task["task"]: task for task in data["tasks"]}
    assert tasks[1] == {
        "task": 1,
        "instance_id": "org__repo-1",
        "repo": "org/repo1",
        "arrived": at("08:00"),
        "deadline": DAY,
        "holders": [[at("09:00"), "Mei", None], [at("10:00"), None, None]],
        "accepted": at("10:00"),
        "by": "Mei",
        "withdrawn": None,
    }
    assert tasks[2]["holders"] == [[at("10:00"), "Tomas", None], [DAY, None, None]]
    assert (tasks[2]["accepted"], tasks[2]["withdrawn"]) == (None, DAY)
    assert tasks[3]["holders"] == [[at("10:00"), "Aisha", "Tomas"], [DAY, None, None]]
    assert tasks[3]["withdrawn"] == DAY

    # The prices, the orders and the fees, read from the log alone, are the world's own at the
    # checkpoint, and so is the money each resident holds; the bread ordered came in the morning.
    [(_, saved)] = town.checkpoints
    t = saved["time"]
    pending: dict[str, int] = {}
    for good, units, _ in saved["store"]["pending"]:
        pending[good] = pending.get(good, 0) + units
    assert state_at(data["store"]["prices"], t) == saved["store"]["prices"]
    assert state_at(data["store"]["on_order"], t) == pending == {"bread": 5}
    assert state_at(data["store"]["on_order"], now) == {}
    assert state_at(data["kitchen"]["menu"], t) == saved["kitchen"]["menu"]
    assert state_at(data["fees"], t) == saved["fees"]
    for name, found in saved["residents"].items():
        assert state_at(lane(data, name)["purse"], t) == found["inventory"]["money"], name

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


def test_a_resident_whose_health_ran_out_lies_in_bed_until_treated(tmp_path):
    """Aisha takes to bed at midnight while up, sleeps at the forced hour, wakes in bed, and
    leaves it when Lucia treats her at her bedside, paying the fee."""
    run, _ = new_town(tmp_path)
    home = "mill-street-house"
    bedridden = {"day": 1, "home": home, "from": home, "carried": False, "task": None}
    treated = {
        "patient": "Aisha", "fee": 20, "tax": 2, "restores": 25, "before": 0, "health": 25,
        "ill": 3, "bedridden": True,
    }  # fmt: skip
    lines = [
        entry(1, "wake", at("07:00"), "Aisha"),
        entry(2, "illness", DAY, "Aisha", chance=0.1, nights=5, health=10),
        entry(3, "bedridden", DAY, "Aisha", **bedridden),
        entry(4, "forced_sleep", at("02:00", day=2), "Aisha", wake=at("07:00", day=2)),
        entry(5, "wake", at("07:00", day=2), "Aisha"),
        entry(6, "treatment", at("10:00", day=2), "Lucia", **treated),
        entry(7, "recovered", at("10:00", day=2), "Aisha", illness=True, bedridden=True,
              treated=True, health=25),
    ]  # fmt: skip
    run.world_log_path.write_text("\n".join(lines) + "\n")
    data = timeline(run.root)
    assert spans(data, "Aisha") == [
        ("sleep", at("02:30"), at("07:00"), home, None),
        ("idle", at("07:00"), DAY, home, None),
        ("bedridden", DAY, at("02:00", day=2), home, None),
        ("sleep", at("02:00", day=2), at("07:00", day=2), home, None),
        ("bedridden", at("07:00", day=2), at("10:00", day=2), home, None),
        ("idle", at("10:00", day=2), at("10:00", day=2), home, None),
    ]
    assert [m["kind"] for m in lane(data, "Aisha")["markers"]] == [
        "illness",
        "bedridden",
        "forced_sleep",
        "recovered",
    ]
    assert lane(data, "Aisha")["purse"] == [[at("02:30"), 20], [at("10:00", day=2), 0]]
    assert lane(data, "Lucia")["purse"] == [[at("02:30"), 100], [at("10:00", day=2), 118]]


def test_a_task_that_never_came_in_is_refused(tmp_path):
    run, _ = new_town(tmp_path)
    claim = entry(1, "claim", at("09:00"), "Mei", task=7, instance_id="seven")
    run.world_log_path.write_text(claim + "\n")
    with pytest.raises(ValueError, match="entry 1: task 7 never came in"):
        timeline(run.root)


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


async def test_money_passed_moves_the_purses_and_a_thing_passed_does_not(tmp_path):
    run, town = new_town(tmp_path)
    town.world.residents["Mei"].inventory.items["bread"] = 3
    town.start(until_day=2)
    await town.until("07:00")
    await town.call("Tomas", "go", place="mill-street-house")
    await town.until("07:10")
    await town.call("Mei", "pass", item="money", units=5, to="Tomas")
    await town.call("Mei", "pass", item="bread", units=2, to="Tomas")
    await town.close()
    data = timeline(run.root)
    passed = [fields(m) for m in lane(data, "Mei")["markers"] if m["kind"] == "move"]
    assert passed == [
        {"item": None, "units": 0, "source": "Mei", "target": "Tomas", "money": 5,
         "reason": "pass", "seller": None, "tax": 0},
        {"item": "bread", "units": 2, "source": "Mei", "target": "Tomas", "money": 0,
         "reason": "pass", "seller": None, "tax": 0},
    ]  # fmt: skip
    assert lane(data, "Mei")["purse"][-1] == [at("07:10"), 115]
    assert lane(data, "Tomas")["purse"][-1] == [at("07:10"), 185]
