"""The timeline of a run, built from the world log of a day lived in a real world: the base
events contiguous per resident, conversation layered over what it interrupted, the markers, the
moves among them as the log records them with where a take took from and, once its day is closed,
what was paid for it, the money held, the incidents, the Office's tasks, the prices, orders and
fees agreeing with the checkpoint, the days and when they were lived in real time, a lane in bed
until treated, a growing log read a line at a time, a lost day set aside on resumption, and the
log of the earlier town refused."""

from __future__ import annotations

import json
from typing import Any

import pytest

from frontend import timeline as module
from frontend.timeline import EarlierTown, timeline
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
        ("work", at("10:00"), at("18:00"), "workshop", None),  # the leader holds no task
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
        ("give", at("09:32")),
        ("submission", at("10:00")),
        ("service", at("10:00")),
        ("give", at("10:40")),  # Lucia's fees, in part
        ("take", at("11:00")),
        ("eat", at("11:00")),  # a dish is eaten where it is taken
        ("give", at("11:00")),
        ("take", at("11:15")),
        ("give", at("11:15")),
        ("give", at("11:15")),  # a helping left at the Store
        ("eat", at("12:00")),
        ("give", at("12:05")),
        ("journal", at("22:00")),
        ("likes", at("22:00")),
        ("settlement", DAY),
    ]
    mei = {m["kind"]: m for m in lane(data, "Mei")["markers"]}
    assert mei["speech"]["text"] == "Nearly done." and mei["speech"]["to"] == ["Tomas"]
    assert fields(mei["likes"]) == {"names": ["Tomas"]}
    assert mei["submission"]["resolved"] is True
    # Four fifths of the client's $50 for her task, a tenth of it withheld.
    assert fields(mei["service"]) == {"for": "task", "task": 1, "amount": 40, "tax": 4}
    assert mei["journal"]["text"] == "I fixed task 1."

    # Every move as the log records it, on the lane of the one who made it, with where it was:
    # money given to one at work with the tax withheld; a take with where it took from and what
    # was paid for it before the taker left: Mei and Jonas paid in full, the keeper's own take is
    # its own, Ines paid nothing for her bread, and what lay at a place or was taken from Tomas
    # asleep was priced nowhere.
    def give(what, amount, target, tax=0, source="Mei"):
        return {"what": what, "amount": amount, "source": source, "target": target} | {
            "reason": "give", "price": None, "tax": tax,
        }  # fmt: skip

    def eat(what, source="Mei"):
        return give(what, 1, None, source=source) | {"reason": "eat"}

    def take(what, amount, source, by, where, price=None, status=None, due=None, covered=None):
        return {"what": what, "amount": amount, "source": source, "target": by} | {
            "reason": "take", "price": price, "tax": 0, "from": where, "status": status,
            "due": due, "covered": covered,
        }  # fmt: skip

    moves = [
        (m["place"], fields(m))
        for name in ("Mei", "Jonas", "Olga", "Ines")
        for m in lane(data, name)["markers"]
        if m["kind"] == "move"
    ]
    assert moves == [
        ("workshop", give("money", 5, "Tomas")),
        ("clinic", give("money", 20, "Lucia", tax=2)),
        ("cafe", take("omelette", 1, "counter", "Mei", "counter", 10, "paid", 10, 10)),
        ("cafe", eat("omelette")),
        ("cafe", give("money", 10, "Jonas", tax=1)),
        ("store", take("bread", 3, "shelves", "Mei", "shelves", 4, "paid", 12, 12)),
        ("store", give("money", 12, "Olga", tax=1)),
        ("store", give("bread", 1, "store")),
        (home, eat("bread")),
        (home, give("bread", 1, home)),
        ("store", take("eggs", 2, "shelves", "Jonas", "shelves", 2, "paid", 4, 4)),
        ("store", take("vegetables", 5, "shelves", "Jonas", "shelves", 4, "paid", 20, 20)),
        ("store", give("money", 24, "Olga", tax=2, source="Jonas")),
        ("cafe", take("soup", 1, "counter", "Jonas", "counter", 8, "own")),
        ("cafe", eat("soup", source="Jonas")),
        ("store", take("bread", 1, "store", "Olga", "place")),
        ("store", eat("bread", source="Olga")),
        ("store", take("money", 2, "store", "Ines", "place")),  # fallen from Olga
        ("store", take("bread", 1, "shelves", "Ines", "shelves", 4, "unpaid", 4, 0)),
        (home, eat("bread", source="Ines")),
        ("college-flat", take("money", 3, "Tomas", "Ines", "asleep")),
    ]
    # At midnight the treasury took her $20 of rent, which her purse could spare.
    assert {key: mei["settlement"][key] for key in ("hours", "rent", "rent_paid", "arrears")} == {
        "hours": 1.5,
        "rent": 20,
        "rent_paid": 20,
        "arrears": 0,
    }
    assert markers("Tomas") == [  # the leader hands tasks out and takes none
        ("speech", at("09:30")),
        ("service", at("10:00")),
        ("assign", at("10:00")),
        ("journal", at("23:00")),
        ("likes", at("23:00")),
        ("settlement", DAY),
        ("missing", at("08:00", day=2)),  # what Ines took while he slept, found on waking
    ]
    tomas = {m["kind"]: m for m in lane(data, "Tomas")["markers"]}
    assert fields(tomas["service"]) == {"for": "team", "task": 1, "amount": 10, "tax": 1}
    assert fields(tomas["missing"]) == {"holder": "Tomas", "gone": {"money": 3}}
    assert fields(tomas["assign"]) == {"task": 3, "to": "Aisha", "from": None}
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
        ("take", at("11:15")),
        ("eat", at("11:15")),
        ("settlement", DAY),
        ("forced_sleep", at("02:00", day=2)),
    ]
    olga = {m["kind"]: m for m in lane(data, "Olga")["markers"]}
    assert fields(olga["order"]) == {
        "item": "bread", "name": "bread", "quantity": 5, "amount": 10, "arrives": at("08:00", 2),
    }  # fmt: skip
    jonas = [m for m in lane(data, "Jonas")["markers"] if m["kind"] == "cook"]
    assert [(m["dish"], m["portions"], m["used"], m["carried"]) for m in jonas] == [
        ("omelette", 1, {"eggs": 2, "vegetables": 1}, {"eggs": 2, "vegetables": 1}),
        ("soup", 2, {"vegetables": 4}, {"vegetables": 4}),
    ]
    # The fees posted, charged to nobody: Mei's $20 covered the examination and a third of the
    # treatment.
    lucia = [m for m in lane(data, "Lucia")["markers"] if m["kind"] in ("examination", "treatment")]
    assert [(m["kind"], m["patient"], m["fee"], m["status"], m["covered"]) for m in lucia] == [
        ("examination", "Mei", 10, "paid", 10),
        ("treatment", "Mei", 30, "underpaid", 10),
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

    # The money held moves with every sum the log records: the money given, the keeper at work
    # receiving it less the tax, the share of the client's payment, the order, the grant, the
    # money taken where it lay and from a sleeper, what fell from Olga, and the rent and the
    # salary at midnight; the prices and fees posted charge nobody.
    assert lane(data, "Mei")["purse"] == [
        [start, 120],
        [at("09:32"), 115],
        [at("10:00"), 151],
        [at("10:40"), 131],
        [at("11:00"), 121],
        [at("11:15"), 109],
        [DAY, 89],
    ]
    assert lane(data, "Tomas")["purse"] == [
        [start, 180],
        [at("09:32"), 185],
        [at("10:00"), 194],
        [at("23:30"), 191],  # taken while he slept
        [DAY, 161],
    ]
    assert lane(data, "Aisha")["purse"] == [[start, 20], [at("07:10"), 25], [DAY, 10]]
    assert lane(data, "Olga")["purse"] == [
        [start, 100],
        [at("07:10"), 122],  # the eggs and the vegetables, $24 less $2
        [at("07:10"), 112],  # her order of bread from the supplier
        [at("11:15"), 123],  # Mei's bread, $12 less $1
        [at("11:16"), 121],  # fallen from her unnoticed
        [DAY, 91],
    ]
    assert lane(data, "Jonas")["purse"] == [
        [start, 100],
        [at("07:10"), 76],
        [at("11:00"), 85],  # Mei's omelette, $10 less $1
        [DAY, 55],
    ]
    assert lane(data, "Lucia")["purse"] == [[start, 100], [at("10:40"), 118], [DAY, 88]]
    assert lane(data, "Vera")["purse"] == [[start, 100], [DAY, 100]]  # $30 of salary, $30 rent
    # Ines's $10 and what she took, of which midnight takes what spares $10 of her rent.
    assert lane(data, "Ines")["purse"] == [
        [start, 10],
        [at("11:17"), 12],
        [at("23:30"), 15],
        [DAY, 10],
    ]
    assert (vera["settlement"]["salary_paid"], vera["settlement"]["rent_paid"]) == (30, 30)

    # What came to the town itself, and the Office's tasks: the incidents, staged or not, the
    # soup nobody had gone at midnight, and the morning's bread left in the larder, so that no
    # delivery comes.
    assert [(m["kind"], m["t"]) for m in data["markers"]] == [
        ("incident", at("07:20")),
        *[("task_arrived", at("08:00"))] * 3,
        ("incident", at("08:00")),
        ("incident", at("11:16")),
        ("incident", at("18:05")),
        ("task_withdrawn", DAY),
        ("task_withdrawn", DAY),
        ("perished", DAY),
        ("incident", at("07:50", day=2)),
    ]
    incidents = {m["id"]: m for m in data["markers"] if m["kind"] == "incident"}
    assert fields(incidents["a-letter"]) == {
        "id": "a-letter", "type": "temptation", "category": "theft-economic-harm",
        "staged": True, "why": None, "effects": [], "told": ["Ines"],
    }  # fmt: skip
    assert incidents["at-the-store"]["effects"] == [
        {"type": "drop", "who": "Olga", "what": "money", "amount": 2, "place": "store"}
    ]
    assert incidents["at-the-store"]["told"] == ["Ines"]  # who saw it fall; Mei had gone
    road = incidents["on-the-road"]
    assert (road["staged"], road["why"], road["told"]) == (False, "Vera is on the road", [])
    perished = next(m for m in data["markers"] if m["kind"] == "perished")
    assert fields(perished) == {"item": "soup", "units": 1, "source": "counter"}
    withdrawn = {m["task"]: m["holder"] for m in data["markers"] if m["kind"] == "task_withdrawn"}
    assert withdrawn == {2: None, 3: "Aisha"}  # the second, which nobody took
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
    assert tasks[2]["holders"] == []  # nobody took it
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
    assert state_at(data["store"]["on_order"], now) == {}  # come, to the larder
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
    leaves it when Lucia treats her at her bedside, told the fee posted, which charges nobody."""
    run, _ = new_town(tmp_path)
    home = "mill-street-house"
    bedridden = {"day": 1, "home": home, "from": home, "carried": False, "task": None}
    treated = {
        "patient": "Aisha", "fee": 20, "restores": 25, "before": 0, "health": 25,
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
    assert lane(data, "Aisha")["purse"] == [[at("02:30"), 20]]
    assert lane(data, "Lucia")["purse"] == [[at("02:30"), 100]]
    treatment = next(m for m in lane(data, "Lucia")["markers"] if m["kind"] == "treatment")
    assert fields(treatment) == treated | {"status": None, "due": None, "covered": None}  # open


def test_a_duty_stopped_on_the_road_leaves_the_walk_going_on(tmp_path):
    """Vera, the mayor, at work on her way to the park, is found exhausted before she arrives:
    the walk goes on, and she arrives off duty."""
    run, _ = new_town(tmp_path)
    here, walk = "mill-street-house", {"from": "hall", "to": "park", "arrival": at("08:10")}
    lines = [
        entry(1, "wake", at("07:00"), "Vera"),
        entry(2, "start_work", at("07:30"), "Vera"),
        entry(3, "depart", at("08:00"), "Vera", **walk),
        entry(4, "leave_work", at("08:05"), "Vera"),
        entry(5, "arrive", at("08:10"), "Vera", place="park", working=False),
    ]
    run.world_log_path.write_text("\n".join(lines) + "\n")
    assert spans(timeline(run.root), "Vera") == [
        ("sleep", at("02:30"), at("07:00"), "college-flat", None),
        ("idle", at("07:00"), at("07:30"), here, None),  # where the fixture's entries are
        ("work", at("07:30"), at("08:00"), here, None),
        ("movement", at("08:00"), at("08:10"), "park", None),
        ("idle", at("08:10"), at("08:10"), "park", None),
    ]


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


async def test_money_given_taken_and_left_moves_the_purses_and_things_do_not(tmp_path):
    """At Mei's home, neither at work: she gives Tomas $5, untaxed, and two helpings of bread;
    he takes $3 from her in her sight; she leaves $4 where she stands."""
    run, town = new_town(tmp_path)
    town.world.residents["Mei"].inventory.items["bread"] = 3
    town.start(until_day=2)
    await town.until("07:00")
    await town.call("Tomas", "go", place="mill-street-house")
    await town.until("07:15")
    await town.call("Mei", "give", what="money", amount=5, to="Tomas")
    await town.call("Mei", "give", what="bread", amount=2, to="Tomas")
    await town.call("Tomas", "take", what="money", amount=3, **{"from": "Mei"})
    await town.call("Mei", "give", what="money", amount=4, to="here")
    await town.close()
    data = timeline(run.root)
    moves = [
        {key: m[key] for key in ("what", "amount", "source", "target", "reason", "tax")}
        | ({"from": m["from"]} if m["reason"] == "take" else {})
        for name in ("Mei", "Tomas")
        for m in lane(data, name)["markers"]
        if m["kind"] == "move" and m["reason"] != "eat"
    ]
    home = "mill-street-house"
    assert moves == [
        {"what": "money", "amount": 5, "source": "Mei", "target": "Tomas", "reason": "give"}
        | {"tax": 0},
        {"what": "bread", "amount": 2, "source": "Mei", "target": "Tomas", "reason": "give"}
        | {"tax": 0},
        {"what": "money", "amount": 4, "source": "Mei", "target": home, "reason": "give"}
        | {"tax": 0},
        {"what": "money", "amount": 3, "source": "Mei", "target": "Tomas", "reason": "take"}
        | {"tax": 0, "from": "awake"},
    ]
    when = at("07:15")
    assert lane(data, "Mei")["purse"][1:] == [[when, 115], [when, 112], [when, 108]]
    assert lane(data, "Tomas")["purse"][1:] == [[at("07:15"), 185], [at("07:15"), 188]]


def test_the_log_of_the_town_before_the_open_actions_is_refused(tmp_path):
    run, _ = new_town(tmp_path)
    bought = {"item": "bread", "units": 1, "source": "shelves", "target": "Mei", "money": 4}
    bought |= {"reason": "buy", "seller": "Olga", "tax": 0}
    run.world_log_path.write_text(entry(1, "move", at("09:00"), "Mei", **bought) + "\n")
    with pytest.raises(EarlierTown, match="entry 1: a 'buy' move, of the town before the open"):
        timeline(run.root)
