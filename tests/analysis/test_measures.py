"""The measures of a lived run (`tests.support.lived`), checked by hand against its story."""

from __future__ import annotations

import asyncio
import csv
import json

import pytest

from analysis.measures import MEASURES, TOWN, beds, daily, main, measure, town_days, world_measures
from evaluation.records import Day
from tests.support.lived import LIVED, OTHERS, before_occupations, live

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
    assert list(mei) == ["resident", "occupation", "day", "date", *MEASURES]
    assert (mei["occupation"], rows["Ravi", 2]["occupation"]) == ("programmer", "team-leader")
    office = ("tasks_taken", "tasks_handed_in", "tasks_accepted", "client_shares")
    assert [mei[k] for k in office] == [1, 1, 1, 40] and [tomas[k] for k in office] == [1, 0, 0, 0]
    # Ravi gave the open task 3 to Aisha, and the clients withdrew it and Tomas's at the second
    # midnight.
    assert (aisha["tasks_assigned_to"], rows["Ravi", 1]["tasks_assigned_by"]) == (1, 1)
    assert [rows[name, 2]["tasks_withdrawn"] for name in ("Mei", "Tomas", "Aisha")] == [0, 1, 1]
    # Hours at work are counted and earn nothing. The client paid Mei $40 of task 1's $50, a
    # tenth withheld; the treasury took the rent ($20 on Mill Street, $30 at the flat) from each
    # purse above $10: from Aisha's, with Vera's grant of $5 in it, the whole of it on the first
    # night and $5 of it on the second.
    assert (mei["hours_at_work"], tomas["hours_at_work"], aisha["hours_at_work"]) == (0.33, 9, 0)
    assert (mei["tax"], tomas["tax"], aisha["tax"]) == (4, 0, 0)
    assert (mei["money"], tomas["money"], aisha["money"]) == (120 + 36 + 5 - 20, 180 - 5 - 30, 15)
    assert (mei["rent"], tomas["rent"], aisha["rent"]) == (20, 30, 20)
    assert (aisha["granted"], aisha["arrears"]) == (5, 0)
    assert (rows["Aisha", 2]["rent"], rows["Aisha", 2]["arrears"]) == (5, 15)
    assert rows["Aisha", 2]["money"] == 10 and rows["Mei", 2]["money"] == 121
    assert (mei["charges"], mei["salary"], mei["spent"], mei["hungry"]) == (0, 0, 0, 1)
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
    assert (tomas["gifts_given"], tomas["money_given"]) == (1, 5)
    assert (mei["gifts_received"], mei["money_received"]) == (1, 5)


def test_the_evenings_trades_as_the_town_lived_them(rows):
    ravi, olga, jonas = rows["Ravi", 1], rows["Olga", 1], rows["Jonas", 1]
    lucia, vera = rows["Lucia", 1], rows["Vera", 1]
    # Olga, at the counter from 20:10, sold Jonas $6 of vegetables for the kitchen and Vera $4 of
    # bread, $1 of it in tax, and paid the supplier $10; Jonas bought for the kitchen, cooked a
    # portion and served it for $8, $1 in tax; Lucia examined Ravi for $10, $1 in tax, and paid
    # $8 for her soup; Vera bought bread, announced and granted Aisha $5 from the treasury.
    assert [olga[k] for k in ("hours_at_work", "sales_made", "orders", "takings", "costs")] == [
        3.83, 2, 1, 10, 10,
    ]  # fmt: skip
    assert [olga[k] for k in ("tax", "rent", "money", "arrears")] == [1, 30, 100 - 30 - 1, 0]
    trade = ("bought_for_kitchen", "portions_cooked", "dishes_served", "takings", "costs", "tax")
    assert [jonas[k] for k in trade] == [1, 1, 1, 8, 6, 1] and jonas["money"] == 100 - 6 + 7 - 30
    assert [lucia[k] for k in ("examinations_given", "dishes_eaten", "spent", "takings")] == [
        1, 1, 8, 10,
    ]  # fmt: skip
    assert (lucia["tax"], lucia["money"]) == (1, 100 + 9 - 8 - 30)
    assert [vera[k] for k in ("bought", "spent", "announcements", "grants_made", "money")] == [
        1, 4, 1, 5, 100 - 4 + 30 - 30,
    ]  # fmt: skip
    # The treasury pays her $30 a day, settled last, the day's rents in.
    assert [vera[k] for k in ("salary", "salary_owed", "arrears")] == [30, 0, 0]
    # Ravi's share of Mei's task, as the leader, $10 of which $1 in tax; he paid $10 to be seen.
    assert [ravi[k] for k in ("client_shares", "tax", "examinations_received", "spent")] == [
        10, 1, 1, 10,
    ]  # fmt: skip
    assert ravi["money"] == 100 + 9 - 10 - 30
    # Those who ate were not hungry at midnight; at the second, nobody had eaten.
    assert [rows[name, 1]["hungry"] for name in NAMES] == [1, 1, 1, 1, 1, 1, 0, 0]
    assert all(rows[name, 2]["hungry"] == 1 for name in NAMES)
    assert sum(rows[name, 1]["treatments_given"] for name in NAMES) == 0
    assert all(rows[name, 1]["reports_read"] == 0 for name in NAMES)
    # Those still at work at midnight worked on until the forced sleep, two hours of the
    # second calendar day.
    assert [rows[name, 2]["hours_at_work"] for name in ("Olga", "Jonas", "Lucia", "Vera")] == [
        2, 2, 0, 2,
    ]  # fmt: skip


def test_the_town_s_days(run_dir):
    days = town_days(run_dir)
    assert [list(row) for row in days] == [["day", "date", *TOWN]] * 2
    first, second = days
    # Task 1's client paid $50 into the town and the Store paid the supplier $10 out of it; the
    # treasury took $8 in taxes ($5 of the client's payment, $1 each of the sales, the dish and
    # the fee) and every room's rent, $220, and paid Vera's $30 and her grant of $5.
    assert {key: value for key, value in first.items() if value} == {
        "day": 1, "date": "2001-01-01", "tasks_arrived": 3, "tasks_accepted": 1, "clients": 50,
        "supplier": 10, "money": 677, "treasury": 1000 + 8 + 220 - 30 - 5, "taken_tax": 8,
        "taken_rent": 220, "paid_salary": 30, "paid_grant": 5, "store_takings": 10,
        "kitchen_takings": 8, "kitchen_costs": 6, "surgery_takings": 10,
    }  # fmt: skip
    assert (second["tasks_withdrawn"], second["arrears"], second["taken_rent"]) == (2, 15, 205)
    # The residents' money and the treasury change only by what the clients pay and the
    # supplier is paid.
    held = sum(r.purse for r in LIVED.residents) + LIVED.treasury.start
    for row in days:
        held += row["clients"] - row["supplier"]
        assert row["money"] + row["treasury"] == held, row["day"]


def test_daily_totals_and_means(rows):
    found = {(row["day"], row["measure"]): row for row in daily(list(rows.values()))}
    assert found[1, "client_shares"] == {
        "day": 1, "measure": "client_shares", "total": 50, "mean": 50 / 8, "residents": 8,
    }  # fmt: skip
    assert found[2, "arrears"]["total"] is None and found[2, "arrears"]["mean"] == 15 / 8
    assert found[1, "tax"]["total"] == 4 + 1 + 1 + 1 + 1
    assert found[1, "takings"]["total"] == 10 + 8 + 10
    assert found[2, "forced_sleep"]["total"] == 7 and found[1, "hungry"]["total"] == 6
    assert found[2, "starving"]["total"] == 8 and found[1, "starving"]["total"] == 0
    assert found[2, "bedridden"]["total"] == 0 and found[1, "health"]["total"] is None
    assert found[2, "health"]["mean"] == pytest.approx((83 * 2 + 85 * 6) / 8)
    assert found[1, "money"]["total"] is None and found[1, "health"]["residents"] == 8


def entry(kind: str, actor: str, **payload: object) -> dict:
    return {"kind": kind, "actor": actor, "audience": [], "payload": payload}


def test_the_chefs_own_dish_from_the_kitchen_is_no_gift():
    def served(to: str) -> dict:
        return entry("move", "Jonas", item="soup", units=1, source="portions", target=to,
                     money=0, reason="pass", seller=None, tax=0)  # fmt: skip

    day = Day(1, (served("Jonas"), served("Mei")), None, 1.0)
    jonas, mei = (world_measures(day, name, {}) for name in ("Jonas", "Mei"))
    assert (jonas["gifts_given"], jonas["gifts_received"], mei["gifts_received"]) == (1, 0, 1)


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
        (name, day.number): world_measures(day, name, lying[day.number])
        for day in days
        for name in ("Aisha", "Mei", "Lucia", "Tomas")
    }
    assert [seen["Aisha", day]["bedridden"] for day in (1, 2, 3)] == [1, 1, 0]
    assert seen["Aisha", 2]["visited_in_bed"] == 2
    assert [seen[name, 2]["bedside_visits"] for name in ("Mei", "Lucia", "Tomas")] == [1, 1, 0]


def test_a_run_of_the_town_before_occupations_has_none_of_these_measures(run_dir, tmp_path, capsys):
    before = before_occupations(run_dir, tmp_path / "before")
    with pytest.raises(SystemExit):
        main([str(before), "--out", str(tmp_path / "out")])
    assert "is a run of the town before occupations" in capsys.readouterr().err
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
