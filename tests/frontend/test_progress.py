"""The progress of a run, from a world log written by hand: the lived days and what each counts,
the residents' markers and the town's, verdicts, the money held at the end of the day, the day
in progress, and the real hours of the days."""

from __future__ import annotations

from frontend.progress import progress
from frontend.timeline import timeline
from infrastructure.storage import RunDirectory
from tests.support.runs import entry, new_town
from tests.support.towns import at
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
    "took_from_shelves": 0,
    "took_from_counter": 0,
    "took_from_people": 0,
    "gifts": 0,
    "examinations": 0,
    "treatments": 0,
    "announcements": 0,
    "speeches": 0,
    "messages": 0,
    "incidents": 0,
    "journals": 0,
    "illnesses": 0,
    "bedridden": 0,
    "forced_sleeps": 0,
}


def write(run: RunDirectory, lines: list[tuple]) -> None:
    with run.world_log_path.open("a") as log:
        for seq, (kind, t, actor, real_time, payload) in enumerate(lines, start=1):
            log.write(entry(seq, kind, t, actor, real_time=real_time, **payload) + "\n")


def settlement(money: int) -> dict:
    """The midnight statement: no time at work and no salary, the rent owed, the purse as it
    stood, nothing eaten and the body as it stood."""
    return {
        "hours": 0.0,
        "salary": 0,
        "owed_before": 0,
        "salary_paid": 0,
        "owed": 0,
        "rent": 20,
        "charges": 0,
        "arrears_before": 0,
        "rent_paid": 0,
        "arrears": 20,
        "money": money,
        "nourishment": 0,
        "satiety": 20.0,
        "energy": 70.0,
        "health": 100.0,
        "night": {"poor_home": -2.0, "recovery": 5.0},
        "ill": 0,
    }


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


def move(reason: str, what: str, amount: int, source: str, target: str | None, **fields) -> dict:
    """A move's payload: `amount` of `what`, an item or money, from `source` to `target`."""
    found = {"what": what, "amount": amount, "source": source, "target": target}
    return found | {"reason": reason, "price": None, "tax": 0} | fields


def take(by: str, what: str, amount: int, source: str, price: int | None = None) -> dict:
    return move("take", what, amount, source, by, price=price)


EXAMINATION = {
    "patient": "Mei", "fee": 10, "satiety": 50.0, "energy": 60.0, "health": 100.0, "ill": 0,
    "night": {},
}  # fmt: skip
TREATMENT = {
    "patient": "Mei", "fee": 30, "restores": 25.0, "before": 100.0, "health": 100.0, "ill": 0,
    "bedridden": False,
}  # fmt: skip
LETTER = {"id": "a-letter", "kind": "temptation", "category": "scam-deceit", "staged": True}
LETTER |= {"why": None, "effects": [], "told": ["Aisha"]}
ROAD = LETTER | {"id": "on-the-road", "kind": "accident", "staged": False, "why": "on the road"}
ROAD |= {"told": []}
ORDER = {"item": "bread", "name": "bread", "quantity": 5, "amount": 10, "arrives": at("08:00", 2)}
GRANT = {"to": "Aisha", "amount": 5, "reason": "For the rent.", "treasury": 995}
BEDRIDDEN = {"day": 2, "home": "mill-street-house", "from": None, "carried": False, "task": None}


async def test_each_lived_day_counts_its_markers_and_ends_with_the_money_then(tmp_path):
    """Mei $120, Tomas $180, Aisha $20, the four trades $100 each and Ines $10 at the start. The
    takes are counted by where they took from: Jonas's from the shelves for the kitchen, Mei's
    from them and from the counter, whether or not anything was given for them; Ines's from
    Tomas, asleep; taking what lay at a place, or eating, is not counted. Money or a thing given
    to another resident is a gift, a payment among them; money left on the shelves is not. Of
    the incidents, the one staged is counted."""
    run, _ = new_town(tmp_path)
    cook = {"dish": "soup", "name": "vegetable soup", "portions": 1, "used": {"vegetables": 2}}
    cook |= {"carried": {"vegetables": 2}}
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
            ("move", at("09:32"), "Mei", 1005.0, move("give", "money", 5, "Mei", "Tomas")),
            ("submission", at("10:00"), "Mei", 1007.0, {"task": 1}),
            ("verdict", at("10:00"), "Mei", 1008.0, verdict(1, True)),
            (
                "service",
                at("10:00"),
                "Mei",
                1009.0,
                {"for": "task", "task": 1, "amount": 20, "tax": 2, "money": 133},
            ),
            ("submission", at("11:00"), "Aisha", 1010.0, {"task": 2}),
            ("verdict", at("11:00"), "Aisha", 1011.0, verdict(2, False)),
            ("move", at("11:30"), "Jonas", 1011.1, take("Jonas", "vegetables", 2, "shelves", 3)),
            (
                "move",
                at("11:31"),
                "Jonas",
                1011.12,
                move("give", "money", 6, "Jonas", "Olga", tax=1),
            ),
            ("order", at("11:35"), "Olga", 1011.15, ORDER),
            ("cook", at("11:40"), "Jonas", 1011.2, cook),
            ("move", at("12:00"), "Mei", 1011.3, take("Mei", "soup", 1, "counter", 8)),
            ("move", at("12:00"), "Mei", 1011.31, move("eat", "soup", 1, "Mei", None)),
            ("move", at("12:10"), "Mei", 1011.4, take("Mei", "bread", 1, "shelves", 4)),
            ("move", at("12:11"), "Mei", 1011.41, move("give", "money", 4, "Mei", "shelves")),
            ("move", at("12:20"), "Mei", 1011.45, take("Mei", "bread", 1, "store")),  # left there
            ("incident", at("12:30"), None, 1011.47, LETTER),
            ("incident", at("12:31"), None, 1011.48, ROAD),
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
            ("settlement", DAY, "Mei", 1014.1, settlement(81)),
            ("settlement", DAY, "Tomas", 1015.1, settlement(185)),
            ("illness", DAY, "Aisha", 1015.5, {"chance": 0.05, "nights": 5, "health": 100.0}),
            ("settlement", DAY, "Aisha", 1016.1, settlement(20)),
            ("task_withdrawn", DAY, None, 1016.2, {"task": 2, "holder": "Aisha"}),
            # Past midnight, but still the first lived day: it ends at its checkpoint.
            ("forced_sleep", at("02:00", day=2), "Aisha", 1017.0, {"wake": at("07:00", day=2)}),
            ("checkpoint", at("02:30", day=2), None, 1000.0 + 2.5 * HOUR, {"day": 1}),
            ("wake", at("07:00", day=2), "Mei", 9100.0, {}),
            ("task_arrived", at("08:00", day=2), None, 9100.5, arrived(3)),
            ("claim", at("09:00", day=2), "Mei", 9101.0, {"task": 3, "instance_id": "t3"}),
            ("submission", at("09:20", day=2), "Mei", 9102.0, {"task": 3}),  # awaiting the verdict
            (
                "move",
                at("09:30", day=2),
                "Tomas",
                9103.0,
                move("give", "money", 10, "Tomas", "Aisha"),
            ),
            ("move", at("09:40", day=2), "Ines", 9103.2, take("Ines", "money", 4, "Tomas")),
            ("grant", at("10:00", day=2), "Vera", 9103.5, GRANT),
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
            | {"rejected": 1, "withdrawn": 1, "took_from_shelves": 2, "took_from_counter": 1}
            | {"gifts": 2, "examinations": 1, "treatments": 1, "announcements": 1}
            | {"speeches": 2, "incidents": 1, "journals": 1, "illnesses": 1, "forced_sleeps": 1}
            # Mei $81, Tomas $185, Aisha $20, Olga $95 (Jonas's $6 less the tax, less her
            # order), Jonas $94, Lucia and Vera $100, Ines $10; the fees charged nobody.
            | {"purse": {"min": 10, "median": 94.5, "max": 185}},
            {"day": 2, "date": "2001-01-02", "in_progress": True, "hours": None}
            | NOTHING
            | {"arrived": 1, "claims": 1, "submissions": 1, "took_from_people": 1, "gifts": 1}
            | {"bedridden": 1}
            # Aisha $35, with Tomas's $10 and Vera's grant of $5 from the treasury; Ines $14,
            # with $4 taken from Tomas, asleep.
            | {"purse": {"min": 14, "median": 94.5, "max": 171}},
        ],
    }


async def test_a_day_lived_again_is_timed_from_the_resumption(tmp_path):
    run, _ = new_town(tmp_path)
    before = progress(timeline(run.root))
    assert (before["day"], before["hours_per_day"]) == (1, None)
    assert before["daily"] == [
        {"day": 1, "date": "2001-01-01", "in_progress": True, "hours": None}
        | NOTHING
        | {"purse": {"min": 10, "median": 100, "max": 180}}
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
