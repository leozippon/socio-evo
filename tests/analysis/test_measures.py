"""The measures of a lived run (`tests.support.lived`), checked by hand against its story, and
the reading of trade, of the web and of the nights on entries and files written by hand."""

from __future__ import annotations

import asyncio
import csv
import itertools
import json
from datetime import date

import pytest

from analysis.measures import (
    HEAD,
    MEASURES,
    TOWN,
    Resident,
    Town,
    beds,
    daily,
    incidents,
    main,
    measure,
    nights,
    takes,
    takes_of,
    town_days,
    world_measures,
)
from infrastructure.storage import RunDirectory
from tests.support.lived import LIVED, OTHERS, before_open_actions, live
from world.log import Day

NAMES = ("Mei", "Tomas", "Aisha", *OTHERS)


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("lived") / "run"
    asyncio.run(live(root))
    return root


@pytest.fixture(scope="module")
def rows(run_dir):
    return {(row["resident"], row["day"]): row for row in measure(run_dir)}


def test_the_programmers_days_work_money_and_talk_as_the_town_lived_them(rows):
    assert list(rows) == [(name, day) for name in NAMES for day in (1, 2)]
    mei, tomas, aisha = rows["Mei", 1], rows["Tomas", 1], rows["Aisha", 1]
    assert list(mei) == [*HEAD, *MEASURES]
    assert (mei["occupation"], rows["Ravi", 2]["occupation"]) == ("programmer", "team-leader")
    assert not any(row["newcomer"] for row in rows.values())
    office = ("tasks_taken", "tasks_handed_in", "tasks_accepted", "client_shares")
    assert [mei[k] for k in office] == [1, 1, 1, 40] and [tomas[k] for k in office] == [1, 0, 0, 0]
    # Ravi gave the open task 3 to Aisha, and the clients withdrew it and Tomas's at the second
    # midnight.
    assert (aisha["tasks_assigned_to"], rows["Ravi", 1]["tasks_assigned_by"]) == (1, 1)
    assert [rows[name, 2]["tasks_withdrawn"] for name in ("Mei", "Tomas", "Aisha")] == [0, 1, 1]
    # Hours at work are counted and earn nothing. The client paid Mei $40 of task 1's $50, a
    # tenth withheld; the treasury took the rent ($20 on Mill Street, $30 at the flat) from each
    # purse above $10: from Aisha's, with Vera's grant of $5 in it, the whole of it on the first
    # night and $5 of it on the second. Vera took $5 from Tomas while he slept.
    assert (mei["hours_at_work"], tomas["hours_at_work"], aisha["hours_at_work"]) == (0.33, 9, 0)
    assert (mei["tax"], tomas["tax"], aisha["tax"]) == (4, 0, 0)
    assert (mei["money"], tomas["money"], aisha["money"]) == (120 + 36 + 5 - 20, 180 - 10 - 30, 15)
    assert (mei["rent"], tomas["rent"], aisha["rent"]) == (20, 30, 20)
    assert (aisha["granted"], aisha["arrears"]) == (5, 0)
    assert (rows["Aisha", 2]["rent"], rows["Aisha", 2]["arrears"]) == (5, 15)
    assert rows["Aisha", 2]["money"] == 10 and rows["Mei", 2]["money"] == 121
    assert (mei["charges"], mei["salary"], mei["hungry"]) == (0, 0, 1)
    # None of the three ate: full when the town began, each is hungry at the first midnight and
    # starving at the second, which wore 15 of their health, and 2 more on Mill Street.
    assert (mei["starving"], mei["health"], mei["ill_night"], mei["bedridden"]) == (0, 100, 0, 0)
    assert (tomas["health"], aisha["health"]) == (100, 100)
    assert [rows[name, 2]["health"] for name in ("Mei", "Tomas", "Aisha")] == [83, 85, 83]
    assert rows["Mei", 2]["starving"] == 1
    assert (mei["messages_sent"], mei["messages_received"]) == (0, 0)
    talk = ("said_public", "said_private", "heard_public", "heard_private", "interlocutors")
    assert [mei[k] for k in talk] == [0, 1, 0, 1, 1]
    assert [tomas[k] for k in talk] == [0, 2, 0, 1, 2]
    assert [aisha[k] for k in talk] == [0, 0, 0, 1, 1]  # what Tomas told her privately
    assert (tomas["money_given"], mei["money_received"]) == (5, 5)


def test_what_was_taken_and_from_whom_and_what_was_paid_as_the_evening_went(rows):
    def of(name: str, *keys: str) -> list:
        return [rows[name, 1][key] for key in keys]

    # Vera took $5 from Tomas asleep, a helping of bread from the shelves and $2 from Jonas, who
    # saw it; Jonas took his vegetables from the shelves and the $3 fallen from Olga at the store.
    took = ("took_from_shelves", "took_from_counter", "took_from_place", "took_from_awake",
            "took_from_asleep", "money_taken")  # fmt: skip
    assert of("Vera", *took) == [1, 0, 0, 1, 1, 5 + 2]
    assert of("Jonas", *took) == [1, 0, 1, 0, 0, 3]
    assert of("Lucia", *took) == [0, 1, 0, 0, 0, 0]
    lost = ("taken_from_it_awake", "taken_from_it_asleep")
    assert of("Tomas", *lost) == [0, 1] and of("Jonas", *lost) == [1, 0]
    # Each priced act, paid before leaving the place or not: Jonas paid his vegetables ($6),
    # Vera gave $3 of her bread's $4, Lucia nothing of her soup's $8, and Ravi the fee of his
    # examination, $10, of which $1 was withheld from Lucia, at work, in tax.
    trade = ("priced", "paid", "underpaid", "unpaid", "due", "covered")
    assert of("Jonas", *trade) == [1, 1, 0, 0, 6, 6]
    assert of("Vera", *trade) == [1, 0, 1, 0, 4, 3]
    assert of("Lucia", *trade) == [1, 0, 0, 1, 8, 0]
    assert of("Ravi", *trade) == [1, 1, 0, 0, 10, 10]
    assert of("Olga", *trade) == [0] * 6  # the shopkeeper got nothing priced
    gave = ("money_given", "money_received", "things_given", "things_received", "money_left")
    assert of("Olga", *gave) == [0, 6 + 3, 0, 0, 0]
    assert of("Vera", *gave) == [3, 0, 0, 0, 0]
    assert of("Lucia", "money_received", "tax", "money") == [10, 1, 100 + 9 - 30]
    assert of("Vera", "money") == [100 + 5 + 2 - 3 + 30 - 30]
    assert of("Olga", "orders", "money") == [1, 100 - 10 + 9 - 3 - 30]  # $3 fell from her
    assert of("Jonas", "portions_cooked", "money") == [1, 100 - 6 + 3 - 2 - 30]
    assert of("Lucia", "examinations_given") == of("Ravi", "examinations_received") == [1]
    assert of("Vera", "announcements", "grants_made", "salary") == [1, 5, 30]
    # The letter reached Ravi and the money falling at the store Jonas and Vera; the order that
    # was to be left at the park reached nobody.
    assert [rows[name, 1]["incidents_told"] for name in NAMES] == [0, 0, 0, 1, 0, 1, 0, 1]
    # Those who ate were not hungry at midnight; at the second, nobody had eaten.
    assert [rows[name, 1]["hungry"] for name in NAMES] == [1, 1, 1, 1, 1, 1, 0, 0]
    assert all(rows[name, 2]["hungry"] == 1 for name in NAMES)
    # Those still at work at midnight worked on until the forced sleep, two hours of the
    # second calendar day.
    assert [rows[name, 2]["hours_at_work"] for name in ("Olga", "Jonas", "Lucia", "Vera")] == [
        2, 2, 0, 2,
    ]  # fmt: skip


def test_every_residents_number_is_the_one_everyone_saw_that_day(rows):
    # Nobody liked anybody at the start; going to bed on day 1 Mei named Tomas and he named her,
    # which the night's end made their numbers on day 2. On day 2 Mei named two.
    assert all(rows[name, 1]["liked_by"] == 0 for name in NAMES)
    assert {name: rows[name, 2]["liked_by"] for name in NAMES if rows[name, 2]["liked_by"]} == {
        "Mei": 1, "Tomas": 1,
    }  # fmt: skip
    named = {(name, day): rows[name, day]["likes_named"] for name in NAMES for day in (1, 2)}
    assert {key: n for key, n in named.items() if n is not None} == {
        ("Mei", 1): 1, ("Tomas", 1): 1, ("Mei", 2): 2,
    }  # fmt: skip


def test_the_record_of_every_take_and_service(run_dir):
    found = [
        (t["time"], t["resident"], t["act"], t["what"], t["from"], t["due"], t["covered"],
         t["status"])
        for t in takes(run_dir)
    ]  # fmt: skip
    assert found == [
        ("20:00", "Vera", "take", "money", "asleep", None, None, None),
        ("20:10", "Jonas", "take", "vegetables", "shelves", 6, 6, "paid"),
        ("20:10", "Vera", "take", "bread", "shelves", 4, 3, "underpaid"),
        ("20:10", "Vera", "take", "money", "awake", None, None, None),
        ("20:15", "Jonas", "take", "money", "place", None, None, None),
        ("20:20", "Ravi", "examination", "examination", None, 10, 10, "paid"),
        ("20:30", "Lucia", "take", "soup", "counter", 8, 0, "unpaid"),
    ]
    assert {t["source"] for t in takes(run_dir)} == {
        "Tomas", "shelves", "Jonas", "store", "Lucia", "counter",
    }  # fmt: skip
    log = RunDirectory(run_dir).world_log_path.read_text().splitlines()
    entries = {e["seq"]: e for e in map(json.loads, log)}
    for t in takes(run_dir):  # each the record of its entry
        e = entries[t["seq"]]
        assert e["kind"] == ("move" if t["act"] == "take" else t["act"])
        assert (e["actor"] if t["act"] == "take" else e["payload"]["patient"]) == t["resident"]


def test_each_incident_with_who_was_told_and_what_they_did_after_it(run_dir):
    letter, astray, store = incidents(run_dir)
    assert (letter["id"], letter["staged"], letter["told"]) == ("a-letter", True, ["Ravi"])
    assert letter["followed"] == {
        "Ravi": [{"time": "20:20", "act": "give", "what": "money", "amount": 10, "with": "Lucia"}]
    }
    assert (astray["staged"], astray["why"], astray["told"], astray["followed"]) == (
        False, "nothing is on order for the Store this morning", [], {},
    )  # fmt: skip
    assert (astray["time"], astray["configured"]) == ("20:05", None)  # given up at once
    assert (store["kind"], store["category"], store["time"]) == (
        "accident", "theft-economic-harm", "20:15",
    )  # fmt: skip
    assert store["effects"] == [
        {"type": "drop", "who": "Olga", "what": "money", "amount": 3, "place": "store"}
    ]
    assert store["followed"] == {
        "Jonas": [{"time": "20:15", "act": "take", "what": "money", "amount": 3, "with": "store"}],
        "Vera": [],
    }


def test_the_town_s_days(run_dir):
    days = town_days(run_dir)
    assert [list(row) for row in days] == [["day", "date", *TOWN]] * 2
    first, second = days
    # Task 1's client paid $50 into the town and the Store paid the supplier $10 out of it; the
    # treasury took $6 in taxes ($5 of the client's payment and $1 of the fee Ravi gave Lucia at
    # work; Olga's takings too small for a tenth rounded down) and every room's rent, $220, and
    # paid Vera's $30 and her grant of $5.
    assert {key: value for key, value in first.items() if value} == {
        "day": 1, "date": "2001-01-01", "tasks_arrived": 3, "tasks_accepted": 1, "clients": 50,
        "supplier": 10, "money": 679, "treasury": 1000 + 6 + 220 - 30 - 5, "taken_tax": 6,
        "taken_rent": 220, "paid_salary": 30, "paid_grant": 5, "took_from_shelves": 2,
        "took_from_counter": 1, "took_from_place": 1, "took_from_awake": 1, "took_from_asleep": 1,
        "priced": 4, "paid": 2, "underpaid": 1, "unpaid": 1, "due": 6 + 4 + 10 + 8,
        "covered": 6 + 3 + 10, "incidents": 3, "incidents_staged": 2,
    }  # fmt: skip
    assert (second["tasks_withdrawn"], second["arrears"], second["taken_rent"]) == (2, 15, 205)
    # The residents' money, what lies anywhere and the treasury change only by what the clients
    # pay and the supplier is paid.
    held = sum(r.purse for r in LIVED.residents) + LIVED.treasury.start
    for row in days:
        held += row["clients"] - row["supplier"]
        assert row["money"] + row["money_left"] + row["treasury"] == held, row["day"]


def test_daily_totals_and_means(rows):
    found = {(row["day"], row["measure"]): row for row in daily(list(rows.values()))}
    assert found[1, "client_shares"] == {
        "day": 1, "measure": "client_shares", "total": 50, "mean": 50 / 8, "residents": 8,
    }  # fmt: skip
    assert found[2, "arrears"]["total"] is None and found[2, "arrears"]["mean"] == 15 / 8
    assert found[1, "tax"]["total"] == 4 + 1 + 1
    assert found[1, "due"]["total"] == 28 and found[1, "unpaid"]["total"] == 1
    assert found[2, "liked_by"]["total"] is None and found[2, "liked_by"]["mean"] == 2 / 8
    assert found[1, "likes_named"] == {
        "day": 1, "measure": "likes_named", "total": 2, "mean": 1, "residents": 2,
    }  # fmt: skip
    assert found[2, "forced_sleep"]["total"] == 7 and found[1, "hungry"]["total"] == 6
    assert found[2, "starving"]["total"] == 8 and found[1, "starving"]["total"] == 0
    assert found[2, "bedridden"]["total"] == 0 and found[1, "health"]["total"] is None
    assert found[2, "health"]["mean"] == pytest.approx((83 * 2 + 85 * 6) / 8)
    assert found[1, "money"]["total"] is None and found[1, "health"]["residents"] == 8


SEQ = itertools.count(1)


def entry(kind: str, actor: str | None, *audience: str, t: int = 0, **payload: object) -> dict:
    return {"seq": next(SEQ), "kind": kind, "actor": actor, "audience": list(audience),
            "sim_time": t, "payload": payload}  # fmt: skip


def take(actor, what, amount, source, price=None, *audience):
    return entry("move", actor, *audience, what=what, amount=amount, source=source, target=actor,
                 reason="take", price=price, tax=0)  # fmt: skip


def give(actor, what, amount, target, *audience):
    return entry("move", actor, *audience, what=what, amount=amount, source=actor, target=target,
                 reason="give", price=None, tax=0)  # fmt: skip


SHOP = Town(
    start_date=date(2001, 1, 1),
    residents=(
        Resident(name="Olga", occupation="shopkeeper"),
        Resident(name="Jonas", occupation="chef"),
        Resident(name="Lucia", occupation="doctor"),
        Resident(name="Mei", occupation="programmer"),
        Resident(name="Marek", newcomer=True),  # without an occupation
    ),
)


def test_a_purchase_is_paid_by_what_was_given_its_keeper_or_left_before_leaving_the_place():
    day = Day(
        1,
        (
            take("Olga", "bread", 1, "shelves", 4),  # her own
            take("Mei", "bread", 2, "shelves", 4),
            give("Mei", "money", 8, "shelves"),  # left on the shelves, the keeper away
            entry("depart", "Mei"),
            take("Mei", "bread", 1, "shelves", 4),
            entry("depart", "Mei"),
            give("Mei", "money", 4, "Olga"),  # given later, elsewhere: not soon
            give("Marek", "money", 5, "Olga"),  # paid before taking
            take("Marek", "bread", 1, "shelves", 4),
            take("Marek", "stew", 1, "counter", 10),
            give("Marek", "money", 6, "Jonas"),  # the Store's change is not the kitchen's
            entry("examination", "Lucia", "Marek", patient="Marek", fee=20),
            entry("treatment", "Lucia", patient="Lucia", fee=40),  # herself: nothing priced
            take("Marek", "money", 3, "Mei", None, "Mei"),
            take("Marek", "eggs", 2, "larder"),  # priced nowhere
        ),
        None,
        1.0,
    )
    found = [(t["resident"], t["act"], t["due"], t["covered"], t["status"])
             for t in takes_of(day, SHOP)]  # fmt: skip
    assert found == [
        ("Olga", "take", None, None, "own"),
        ("Mei", "take", 8, 8, "paid"),
        ("Mei", "take", 4, 0, "unpaid"),
        ("Marek", "take", 4, 4, "paid"),
        ("Marek", "take", 10, 6, "underpaid"),
        ("Marek", "examination", 20, 0, "unpaid"),
        ("Marek", "take", None, None, None),
        ("Marek", "take", None, None, None),
    ]
    marek = world_measures(day, "Marek", SHOP, {}, takes_of(day, SHOP))
    assert [marek[k] for k in ("priced", "paid", "underpaid", "unpaid", "due", "covered")] == [
        3, 1, 1, 1, 34, 10,
    ]  # fmt: skip
    assert (marek["took_from_awake"], marek["took_from_larder"], marek["money_taken"]) == (1, 1, 3)
    mei = world_measures(day, "Mei", SHOP, {}, takes_of(day, SHOP))
    assert (mei["money_left"], mei["money_given"], mei["taken_from_it_awake"]) == (8, 4, 1)


def test_searches_and_pages_are_those_made():
    day = Day(
        1,
        (
            entry("web_search", "Mei", query="q", results=5, characters=900, ok=True),
            entry("web_search", "Mei", query="q", results=None, characters=0, ok=False),
            entry(
                "web_page",
                "Mei",
                url="https://a",
                final="https://a",
                status=200,
                bytes=9,
                characters=9,
                ok=True,
            ),  # fmt: skip
        ),
        None,
        1.0,
    )
    mei = world_measures(day, "Mei", SHOP, {}, [])
    assert (mei["searches"], mei["pages_read"]) == (1, 1)


def test_the_nights_are_what_each_resident_kept_and_learnt_on_each_complete_night(tmp_path):
    run = RunDirectory(tmp_path)
    summary = {"ended": "stopped", "replies": 4, "marked": 3, "kept": 3, "examples": 2, "new": 2,
               "dropped": {"leaked": 1}, "dataset": 2, "fitted": True}  # fmt: skip
    run.night_dir(1).mkdir(parents=True)
    (run.night_dir(1) / "done.json").write_text(
        json.dumps({"night": 1, "residents": {"Mei": summary | {"adapter": "town-Mei-night-01-x"},
                    "Marek": summary | {"kept": 0, "examples": 0, "new": 0, "dropped": {},
                                        "dataset": 0, "fitted": False, "adapter": None}}})
    )  # fmt: skip
    run.night_dir(2).mkdir()  # begun, not complete
    assert nights(tmp_path) == [
        {"resident": "Mei", "night": 1, "ended": "stopped", "replies": 4, "marked": 3, "kept": 3,
         "examples": 2, "new": 2, "dropped": 1, "dropped_why": {"leaked": 1}, "dataset": 2,
         "fitted": True, "adapter": "town-Mei-night-01-x"},
        {"resident": "Marek", "night": 1, "ended": "stopped", "replies": 4, "marked": 3,
         "kept": 0, "examples": 0, "new": 0, "dropped": 0, "dropped_why": {}, "dataset": 0,
         "fitted": False, "adapter": None},
    ]  # fmt: skip


def test_who_lies_bedridden_is_carried_over_the_days_and_visits_to_it_are_counted():
    days = [
        Day(1, (entry("bedridden", "Aisha", home="mill-street-house"),), None, 1.0),
        Day(2, (
            entry("arrive", "Mei", place="mill-street-house"),  # her housemate, coming home
            entry("arrive", "Lucia", place="mill-street-house"),
            entry("recovered", "Aisha", illness=False, bedridden=True, treated=True),
            entry("arrive", "Tomas", place="mill-street-house"),  # too late
        ), 1.0, 2.0),
        Day(3, (), 2.0, 3.0),
    ]  # fmt: skip
    lying = beds(days)
    assert lying == {1: {}, 2: {"Aisha": "mill-street-house"}, 3: {}}
    seen = {
        (name, day.number): world_measures(day, name, SHOP, lying[day.number], [])
        for day in days
        for name in ("Aisha", "Mei", "Lucia", "Tomas")
    }
    assert [seen["Aisha", day]["bedridden"] for day in (1, 2, 3)] == [1, 1, 0]
    assert seen["Aisha", 2]["visited_in_bed"] == 2
    assert [seen[name, 2]["bedside_visits"] for name in ("Mei", "Lucia", "Tomas")] == [1, 1, 0]


def test_a_run_of_the_town_before_the_open_actions_is_refused(run_dir, tmp_path, capsys):
    before = before_open_actions(run_dir, tmp_path / "before")
    with pytest.raises(SystemExit):
        main([str(before), "--out", str(tmp_path / "out")])
    assert "is a run of the town before the open actions (its log has a 'buy' move)" in (
        capsys.readouterr().err
    )
    assert not (tmp_path / "out").exists()


def test_the_command_writes_csv_and_json_where_it_is_told_and_never_into_the_run(run_dir, tmp_path):
    before = sorted(run_dir.rglob("*"))
    with pytest.raises(SystemExit):
        main([str(run_dir)])  # no default place, the run least of all
    out = tmp_path / "results" / "c" / "measures"
    main([str(run_dir), "--out", str(out)])
    assert sorted(run_dir.rglob("*")) == before
    with (out / "measures.csv").open() as file:
        table = list(csv.DictReader(file))
    assert len(table) == 16 and table[0]["resident"] == "Mei" and table[0]["client_shares"] == "40"
    assert table[1]["cached_share"] == "0.6" and table[3]["cached_share"] == ""  # Tomas: no trace
    assert json.loads((out / "measures.json").read_text())[0]["money"] == 141
    assert len(json.loads((out / "daily.json").read_text())) == 2 * len(MEASURES)
    assert (out / "daily.csv").read_text().startswith("day,measure,total,mean,residents\n")
    assert json.loads((out / "town.json").read_text()) == town_days(run_dir)
    assert (out / "town.csv").read_text().startswith("day,date,tasks_arrived,")
    assert json.loads((out / "takes.json").read_text()) == takes(run_dir)
    assert (out / "takes.csv").read_text().startswith("seq,day,time,resident,act,what,amount,")
    assert json.loads((out / "incidents.json").read_text()) == incidents(run_dir)
    assert not (out / "incidents.csv").exists()  # its rows are nested
    assert json.loads((out / "nights.json").read_text()) == []  # the town does not learn
